"""
Resumen de indicadores de /dashboard (UX-KPI-01).

Reúne los datos —calendarios conectados, dossiers vigentes, reglas de cobro, saldo— y
delega las reglas en ``meeting_prep_kpi``. Consultar es de solo lectura: no genera dossiers,
no programa automatizaciones, no cobra créditos y no crea eventos internos.

Un fallo nunca se esconde detrás de un número: sin calendario conectado, lectura incompleta,
y proveedor caído son estados distintos, y los créditos siguen visibles
mientras su fuente (la fila de la organización) responda.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.billing.credit_policy import credit_charging_enabled, enterprise_unlimited
from dossier.db.models import CalendarIntegration, Dossier, Organization, User
from dossier.services.calendar_event_filters import owner_email_domain
from dossier.services.calendar_range import ErrorProveedorCalendario, RangoConsulta, ResultadoRango
from dossier.services.google_calendar_api import listar_reuniones_google_rango
from dossier.services.google_calendar_token import get_google_calendar_access_token_for_user
from dossier.services.graph_calendar import listar_reuniones_rango
from dossier.services.meeting_identity import meeting_key, role_for_person
from dossier.services.meeting_prep_kpi import (
    PERIODO_FUTURO,
    CalendarEntry,
    Meeting,
    collect_meetings,
    preparation_role_cost,
    summarize_preparation_cost,
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


def _seccion_no_calculable(lectura: _Lectura, desde: datetime, hasta: datetime, campos: tuple) -> dict:
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
_CAMPOS_COSTO = ("estimated_credits", "meetings_to_generate")


def _billing(org: Organization) -> str:
    """Cómo se cobra hoy en esta organización: decide si el estimado tiene costo real."""
    if not credit_charging_enabled():
        return "disabled"
    if enterprise_unlimited(org):
        return "unlimited"
    return "charged"


def _compute_calendar_sections(db: Session, user: User, org: Organization, as_of: datetime) -> tuple[dict, bool]:
    """Lo que depende del calendario (cacheable). El saldo se añade fuera, siempre fresco."""
    f_ini, f_fin = as_of, as_of + PERIODO_FUTURO
    billing = _billing(org)

    def _no_calculable(lectura: _Lectura) -> dict:
        return {
            "upcoming": _seccion_no_calculable(lectura, f_ini, f_fin, _CAMPOS_FUTURO),
            "preparation_cost": {**_seccion_no_calculable(lectura, f_ini, f_fin, _CAMPOS_COSTO), "billing": billing},
        }

    if not _CUPO.acquire(timeout=ESPERA_CUPO_SEGUNDOS):
        return _no_calculable(_Lectura("unavailable", R_OCUPADO)), True
    try:
        lectura = _leer_calendarios(db, user, RangoConsulta(desde=f_ini, hasta=f_fin))
    finally:
        _CUPO.release()
    if lectura.estado != "ok":
        return _no_calculable(lectura), lectura.estado == "unavailable"

    snap = collect_meetings(lectura.entradas or [], plan=org.plan)
    futuras = [m for m in snap.meetings if f_ini <= m.starts_at < f_fin]
    disponible = _roles_vigentes(db, org_id=org.id, user_id=user.id, meetings=futuras)

    up = summarize_upcoming(snap.meetings, disponible, as_of=as_of)
    estado = "ok" if up.eligible else "empty"
    motivo = None if up.eligible else R_SIN_REUNIONES
    upcoming = {
        "state": estado,
        "reason": motivo,
        "measured_from": _iso(f_ini),
        "measured_to": _iso(f_fin),
        "from": _iso(f_ini),
        "to": _iso(f_fin),
        "eligible_meetings": up.eligible,
        "prepared_meetings": up.prepared,
        "pending_meetings": up.pending,
        "coverage_percent": up.percent,
    }

    costo = summarize_preparation_cost(
        snap.meetings, disponible, as_of=as_of, role_cost=preparation_role_cost(org.plan)
    )
    preparation_cost = {
        "state": estado,
        "reason": motivo,
        "measured_from": _iso(f_ini),
        "measured_to": _iso(f_fin),
        "from": _iso(f_ini),
        "to": _iso(f_fin),
        "estimated_credits": costo.estimated_credits if billing == "charged" else 0,
        "meetings_to_generate": costo.meetings_to_generate,
        "billing": billing,
    }
    return {"upcoming": upcoming, "preparation_cost": preparation_cost}, False


def build_dashboard_summary(
    db: Session, *, user: User, org: Organization, now: datetime | None = None
) -> dict[str, Any]:
    as_of = (now or _utcnow()).astimezone(UTC)
    secciones = SUMMARY_CACHE.get_or_compute(
        (user.id, org.id), lambda: _compute_calendar_sections(db, user, org, as_of)
    )
    saldo = int(org.credits_balance)
    costo = dict(secciones["preparation_cost"])
    estimado = costo.get("estimated_credits")
    # Con el saldo de esta consulta (no el de la caché): ¿alcanza para preparar lo que falta?
    if isinstance(estimado, int):
        costo["exceeds_balance"] = costo["billing"] == "charged" and estimado > saldo
    else:
        costo["exceeds_balance"] = None
    return {
        "as_of": _iso(as_of),
        "timezone": user.timezone or "UTC",
        "upcoming": secciones["upcoming"],
        "preparation_cost": costo,
        "credits": {
            "state": "ok",
            "reason": None,
            "measured_from": None,
            "measured_to": None,
            "balance": saldo,
            "monthly_limit": int(org.credits_monthly_limit),
        },
    }
