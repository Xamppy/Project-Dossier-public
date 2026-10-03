"""
Resumen de indicadores de /dashboard (UX-KPI-01).

Reúne los datos —calendarios conectados, dossiers vigentes, hechos de generación, saldo— y
delega las reglas en ``meeting_prep_kpi``. Consultar es de solo lectura: no genera dossiers,
no programa automatizaciones, no cobra créditos y no crea eventos internos.

Un fallo nunca se esconde detrás de un número: sin calendario conectado, lectura incompleta,
proveedor caído y evidencia ausente son estados distintos, y los créditos siguen visibles
mientras su fuente (la fila de la organización) responda.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from dossier.db.models import CalendarIntegration, Dossier, Organization, User
from dossier.services.calendar_event_filters import owner_email_domain
from dossier.services.calendar_range import ErrorProveedorCalendario, RangoConsulta, ResultadoRango
from dossier.services.google_calendar_api import listar_reuniones_google_rango
from dossier.services.google_calendar_token import get_google_calendar_access_token_for_user
from dossier.services.graph_calendar import listar_reuniones_rango
from dossier.services.meeting_identity import meeting_key, role_for_person
from dossier.services.meeting_prep_evidence import FACT_RETENTION_DAYS, load_facts, recording_started_at
from dossier.services.meeting_prep_kpi import (
    PERIODO_FUTURO,
    PERIODO_HISTORIAL,
    CalendarEntry,
    Meeting,
    collect_meetings,
    summarize_history,
    summarize_upcoming,
)
from dossier.services.microsoft_calendar_token import get_microsoft_graph_access_token_for_user
from dossier.services.summary_cache import SUMMARY_CACHE

__all__ = ["SUMMARY_CACHE", "build_dashboard_summary"]

logger = logging.getLogger(__name__)

PLAZO_PROVEEDORES_SEGUNDOS = 25.0
ESPERA_CUPO_SEGUNDOS = 10.0
MAX_CALCULOS_SIMULTANEOS = 4
_CUPO = threading.BoundedSemaphore(MAX_CALCULOS_SIMULTANEOS)

PROVEEDORES = ("google", "microsoft")

# Códigos estables que traduce el frontend.
R_SIN_CALENDARIO = "no_calendar_connected"
R_SIN_REUNIONES = "no_meetings_in_period"
R_REAUTENTICAR = "calendar_reauth_required"
R_NO_DISPONIBLE = "calendar_unavailable"
R_INCOMPLETO = "calendar_incomplete"
R_OCUPADO = "calendar_busy"
R_HISTORIAL_PARCIAL = "history_partial_evidence"
R_SIN_EVIDENCIA = "evidence_unavailable"

_PRIORIDAD_MOTIVOS = (R_REAUTENTICAR, R_INCOMPLETO, R_NO_DISPONIBLE)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt is not None else None


@dataclass
class _Lectura:
    estado: str  # ok | not_connected | unavailable
    motivo: str | None = None
    entradas: list[CalendarEntry] | None = None


def _motivo_de_token(exc: HTTPException) -> str:
    return R_REAUTENTICAR if exc.status_code in (401, 403, 404) else R_NO_DISPONIBLE


def _leer_proveedor(provider: str, token: str, rango: RangoConsulta) -> ResultadoRango:
    if provider == "google":
        return listar_reuniones_google_rango(token, rango)
    return listar_reuniones_rango(token, rango)


def _leer_calendarios(db: Session, user: User, rango: RangoConsulta) -> _Lectura:
    integraciones = list(
        db.scalars(
            select(CalendarIntegration).where(
                CalendarIntegration.user_id == user.id,
                CalendarIntegration.revoked_at.is_(None),
                CalendarIntegration.provider.in_(PROVEEDORES),
            )
        ).all()
    )
    if not integraciones:
        return _Lectura("not_connected", R_SIN_CALENDARIO)

    fallos: list[str] = []
    trabajos: list[tuple[CalendarIntegration, str]] = []
    for integ in integraciones:
        try:
            if integ.provider == "google":
                token = get_google_calendar_access_token_for_user(db, user.id)
            else:
                token = get_microsoft_graph_access_token_for_user(db, user.id)
        except HTTPException as e:
            fallos.append(_motivo_de_token(e))
            continue
        trabajos.append((integ, token))
    if fallos:  # sin intervalo completo de todos los calendarios no hay porcentaje
        return _Lectura("unavailable", _elegir_motivo(fallos))

    entradas: list[CalendarEntry] = []
    # Sin ``with``: su salida espera a los hilos y anularía el plazo. Un hilo lento termina
    # solo (cada lectura tiene su propio presupuesto) y su resultado se descarta.
    pool = ThreadPoolExecutor(max_workers=len(trabajos))
    try:
        futuros = {pool.submit(_leer_proveedor, i.provider, t, rango): i for i, t in trabajos}
        hechos, pendientes = wait(futuros, timeout=PLAZO_PROVEEDORES_SEGUNDOS)
        if pendientes:
            fallos.append(R_NO_DISPONIBLE)
        for f in hechos:
            integ = futuros[f]
            try:
                resultado = f.result()
            except ErrorProveedorCalendario as e:
                fallos.append(R_REAUTENTICAR if e.reautenticar else R_NO_DISPONIBLE)
                continue
            except Exception:
                logger.warning("Resumen: fallo leyendo %s", integ.provider, exc_info=True)
                fallos.append(R_NO_DISPONIBLE)
                continue
            if not resultado.completo:
                fallos.append(R_INCOMPLETO)
                continue
            dominio = owner_email_domain(integ, user)
            entradas.extend(
                CalendarEntry(integ.provider, "primary", dominio, r) for r in resultado.reuniones
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if fallos:
        return _Lectura("unavailable", _elegir_motivo(fallos))
    return _Lectura("ok", entradas=entradas)


def _elegir_motivo(motivos: list[str]) -> str:
    for m in _PRIORIDAD_MOTIVOS:
        if m in motivos:
            return m
    return R_NO_DISPONIBLE


def _roles_vigentes(
    db: Session, *, org_id, user_id, meetings: list[Meeting]
) -> dict[str, frozenset[str]]:
    """Roles con dossier completo y vigente del propio usuario, por clave de reunión."""
    por_proveedor: dict[str, set[str]] = {}
    for m in meetings:
        for clave in m.keys:
            provider, _calendar, ext = clave.split("|", 2)
            por_proveedor.setdefault(provider, set()).add(ext)
    disponible: dict[str, set[str]] = {}
    cal = Dossier.dossier_data["calendar"]
    for provider, ids in por_proveedor.items():
        lista = sorted(ids)
        for i in range(0, len(lista), 500):
            filas = db.execute(
                select(
                    cal["external_event_id"].astext,
                    Dossier.dossier_data["calendar_folder_role"].astext,
                    Dossier.dossier_data["person_filters"]["contact_index"].astext,
                ).where(
                    Dossier.organization_id == org_id,
                    Dossier.requested_by_user_id == user_id,
                    Dossier.status == "complete",
                    cal["provider"].astext == provider,
                    cal["external_event_id"].astext.in_(lista[i : i + 500]),
                )
            ).all()
            for ext, rol, indice in filas:
                if rol == "corporate":
                    clave_rol = "corporate"
                elif rol == "person":
                    try:
                        clave_rol = role_for_person(int(indice) if indice else 1)
                    except ValueError:
                        clave_rol = role_for_person(1)
                else:
                    continue
                disponible.setdefault(meeting_key(provider, ext), set()).add(clave_rol)
    return {k: frozenset(v) for k, v in disponible.items()}


def _seccion_no_calculable(lectura: _Lectura, desde: datetime, hasta: datetime, campos: dict) -> dict:
    return {
        "state": lectura.estado,
        "reason": lectura.motivo,
        "measured_from": None,
        "measured_to": None,
        "from": _iso(desde),
        "to": _iso(hasta),
        **dict.fromkeys(campos),
    }


_CAMPOS_FUTURO = ("eligible_meetings", "prepared_meetings", "pending_meetings", "coverage_percent")
_CAMPOS_HISTORIAL = (
    "eligible_meetings",
    "manually_prepared_on_time_meetings",
    "on_time_percent",
    "manual_on_time_dossiers",
)


def _reliable_since(user: User, db: Session) -> datetime | None:
    """Desde cuándo hay evidencia fiable; ``None`` = sin límite por purga.

    Quien conserva sus dossiers indefinidamente no perdió nada por retención. Con retención
    numérica, lo anterior al inicio del registro pudo purgarse sin dejar rastro.
    """
    if user.dossier_retention_days is None:
        return None
    return recording_started_at(db)


def _compute_calendar_sections(db: Session, user: User, org: Organization, as_of: datetime) -> tuple[dict, bool]:
    f_ini, f_fin = as_of, as_of + PERIODO_FUTURO
    h_ini, h_fin = as_of - PERIODO_HISTORIAL, as_of
    if not _CUPO.acquire(timeout=ESPERA_CUPO_SEGUNDOS):
        ocupado = _Lectura("unavailable", R_OCUPADO)
        return {
            "upcoming": _seccion_no_calculable(ocupado, f_ini, f_fin, dict.fromkeys(_CAMPOS_FUTURO)),
            "history": _seccion_no_calculable(ocupado, h_ini, h_fin, dict.fromkeys(_CAMPOS_HISTORIAL)),
        }, True
    try:
        lectura = _leer_calendarios(db, user, RangoConsulta(desde=h_ini, hasta=f_fin))
    finally:
        _CUPO.release()

    if lectura.estado != "ok":
        return {
            "upcoming": _seccion_no_calculable(lectura, f_ini, f_fin, dict.fromkeys(_CAMPOS_FUTURO)),
            "history": _seccion_no_calculable(lectura, h_ini, h_fin, dict.fromkeys(_CAMPOS_HISTORIAL)),
        }, lectura.estado == "unavailable"

    snap = collect_meetings(lectura.entradas or [], plan=org.plan)

    # próximas reuniones: dossiers vigentes del propio usuario
    futuras = [m for m in snap.meetings if f_ini <= m.starts_at < f_fin]
    disponible = _roles_vigentes(db, org_id=org.id, user_id=user.id, meetings=futuras)
    up = summarize_upcoming(snap.meetings, disponible, as_of=as_of)
    upcoming = {
        "state": "ok" if up.eligible else "empty",
        "reason": None if up.eligible else R_SIN_REUNIONES,
        "measured_from": _iso(f_ini),
        "measured_to": _iso(f_fin),
        "from": _iso(f_ini),
        "to": _iso(f_fin),
        "eligible_meetings": up.eligible,
        "prepared_meetings": up.prepared,
        "pending_meetings": up.pending,
        "coverage_percent": up.percent,
    }

    # historial: hechos de generación (sobreviven a la retención del documento)
    def _historial_sin_evidencia() -> tuple[dict, bool]:
        sin_evidencia = _Lectura("unavailable", R_SIN_EVIDENCIA)
        return {
            "upcoming": upcoming,
            "history": _seccion_no_calculable(sin_evidencia, h_ini, h_fin, dict.fromkeys(_CAMPOS_HISTORIAL)),
        }, True

    try:
        fiable = _reliable_since(user, db)
        hechos = load_facts(
            db,
            organization_id=org.id,
            user_id=user.id,
            since=as_of - timedelta(days=FACT_RETENTION_DAYS),
        )
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Resumen: evidencia de generación no disponible", exc_info=True)
        return _historial_sin_evidencia()
    if user.dossier_retention_days is not None and fiable is None:
        return _historial_sin_evidencia()  # sin fecha de inicio del registro no hay intervalo verificable
    medido_desde = max(h_ini, fiable) if fiable is not None else h_ini

    h = summarize_history(
        snap.meetings, snap.seen, hechos, measured_from=medido_desde, as_of=as_of,
        fetched_from=h_ini, fetched_to=f_fin,
    )
    parcial = medido_desde > h_ini
    if h.eligible == 0:
        estado, motivo = "empty", R_SIN_REUNIONES
    elif parcial:
        estado, motivo = "partial", R_HISTORIAL_PARCIAL
    else:
        estado, motivo = "ok", None
    history = {
        "state": estado,
        "reason": motivo,
        "measured_from": _iso(medido_desde),
        "measured_to": _iso(h_fin),
        "from": _iso(h_ini),
        "to": _iso(h_fin),
        "eligible_meetings": h.eligible,
        "manually_prepared_on_time_meetings": h.on_time_meetings,
        "on_time_percent": h.percent,
        "manual_on_time_dossiers": h.on_time_dossiers,
    }
    return {"upcoming": upcoming, "history": history}, False


def build_dashboard_summary(
    db: Session, *, user: User, org: Organization, now: datetime | None = None
) -> dict[str, Any]:
    as_of = (now or _utcnow()).astimezone(UTC)
    secciones = SUMMARY_CACHE.get_or_compute(
        (user.id, org.id), lambda: _compute_calendar_sections(db, user, org, as_of)
    )
    return {
        "as_of": _iso(as_of),
        "timezone": user.timezone or "UTC",
        "upcoming": secciones["upcoming"],
        "history": secciones["history"],
        "credits": {
            "state": "ok",
            "reason": None,
            "measured_from": None,
            "measured_to": None,
            "balance": int(org.credits_balance),
            "monthly_limit": int(org.credits_monthly_limit),
        },
    }
