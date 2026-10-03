"""
Automatizaci?n de calendario: sincroniza reuniones pr?ximas y genera dossiers
unos minutos antes del inicio (por defecto 20 min), sin intervenci?n manual.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from dossier.billing.entitlements import plan_allows_automation
from dossier.db.models import CalendarEvent, CalendarIntegration, Dossier, Organization, User
from dossier.org_dossier_context import format_dossier_context_for_prompt
from dossier.services.calendar_event_dossiers import (
    generate_dossiers_from_calendar_event,
    persist_calendar_dossiers,
)
from dossier.services.calendar_event_filters import calendar_event_passes_filters
from dossier.services.google_calendar_api import (
    listar_reuniones_google,
    obtener_reunion_google_por_id,
)
from dossier.services.google_calendar_token import get_google_calendar_access_token_for_user
from dossier.services.graph_calendar import (
    coerce_reunion_payload,
    listar_reuniones,
    obtener_reunion_por_id,
)
from dossier.services.microsoft_calendar_token import get_microsoft_graph_access_token_for_user
from dossier.services.org_membership_service import active_organization_id_for_user
from dossier.services.output_language import resolve_dossier_output_language_for_user

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

ALLOWED_ADVANCE_MINUTES = frozenset({15, 20, 30, 60, 1440})


def automation_enabled() -> bool:
    raw = os.getenv("CALENDAR_AUTOMATION_ENABLED", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def poll_interval_seconds() -> int:
    raw = os.getenv("CALENDAR_AUTOMATION_POLL_SECONDS", "60").strip()
    try:
        return max(15, int(raw))
    except ValueError:
        return 60


def default_advance_minutes() -> int:
    """Valor por defecto del servidor (nuevas integraciones o preferencia inv?lida)."""
    raw = os.getenv("CALENDAR_DEFAULT_ADVANCE_MINUTES", "20").strip()
    try:
        value = max(1, min(int(raw), 7 * 24 * 60))
    except ValueError:
        value = 20
    return value if value in ALLOWED_ADVANCE_MINUTES else 20


def normalize_advance_minutes(value: int | None) -> int:
    """Devuelve minutos v?lidos guardados o el default del servidor."""
    if value is not None and value in ALLOWED_ADVANCE_MINUTES:
        return value
    return default_advance_minutes()


def effective_advance_minutes(integration: CalendarIntegration) -> int:
    """Anticipaci?n que usa la automatizaci?n para esta integraci?n (preferencia del usuario)."""
    return normalize_advance_minutes(integration.advance_minutes)


def user_advance_minutes(integrations: list[CalendarIntegration]) -> int:
    """Anticipaci?n efectiva del usuario (primera integraci?n activa o default)."""
    for row in integrations:
        if row.revoked_at is None and row.is_enabled:
            return effective_advance_minutes(row)
    if integrations:
        return normalize_advance_minutes(integrations[0].advance_minutes)
    return default_advance_minutes()


def parse_event_datetime(value: str | None) -> datetime | None:
    if not value or not str(value).strip():
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _attendees_from_participantes(participantes: str) -> list[dict[str, str]]:
    emails = _EMAIL_RE.findall(participantes or "")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for em in emails:
        low = em.lower()
        if low in seen:
            continue
        seen.add(low)
        domain = low.split("@")[-1] if "@" in low else ""
        out.append({"email": em, "domain": domain})
    return out


def _list_upcoming_reuniones(integration: CalendarIntegration, db: Session) -> list[dict[str, Any]]:
    token: str
    if integration.provider == "google":
        token = get_google_calendar_access_token_for_user(db, integration.user_id)
        return listar_reuniones_google(token, top=40, dias_adelante=3, incluir_pasadas=False)
    if integration.provider == "microsoft":
        token = get_microsoft_graph_access_token_for_user(db, integration.user_id)
        return listar_reuniones(token, top=40, dias_adelante=3, incluir_pasadas=False)
    return []


def _fetch_reunion(
    integration: CalendarIntegration,
    db: Session,
    external_event_id: str,
) -> dict[str, Any] | None:
    if integration.provider == "google":
        token = get_google_calendar_access_token_for_user(db, integration.user_id)
        return obtener_reunion_google_por_id(token, external_event_id)
    if integration.provider == "microsoft":
        token = get_microsoft_graph_access_token_for_user(db, integration.user_id)
        return obtener_reunion_por_id(token, external_event_id)
    return None


def _reunion_for_processing(
    integration: CalendarIntegration,
    db: Session,
    event: CalendarEvent,
) -> dict[str, Any] | None:
    """Combina snapshot con datos frescos del proveedor (paridad con generación manual)."""
    from dossier.services.graph_calendar import merge_reunion_payload

    base: dict[str, Any] = {}
    snap = event.event_snapshot
    if isinstance(snap, dict):
        base = dict(snap)

    fresh = _fetch_reunion(integration, db, event.external_event_id)
    if fresh:
        merged = merge_reunion_payload(base, fresh)
        if merged:
            out = dict(merged)
            user = db.get(User, event.user_id)
            out["_output_language"] = (
                base.get("_output_language")
                or (resolve_dossier_output_language_for_user(user) if user else "es")
            )
            return out

    return coerce_reunion_payload(base)


def reschedule_user_calendar_events(
    db: Session,
    user_id: UUID,
    advance_minutes: int,
) -> int:
    """Recalcula ``dossier_scheduled_at`` para reuniones futuras a?n no procesadas."""
    now = datetime.now(UTC)
    rows = db.execute(
        select(CalendarEvent).where(
            CalendarEvent.user_id == user_id,
            CalendarEvent.processing_status == "scheduled",
            CalendarEvent.starts_at > now,
        )
    ).scalars().all()
    for row in rows:
        row.dossier_scheduled_at = row.starts_at - timedelta(minutes=advance_minutes)
    if rows:
        db.commit()
    return len(rows)


def _event_snapshot_with_output_language(
    reunion: dict[str, Any],
    user: User | None,
) -> dict[str, Any]:
    snap = dict(reunion)
    snap["_output_language"] = (
        resolve_dossier_output_language_for_user(user) if user else "es"
    )
    return snap

_FILTER_SKIP_MARKERS = (
    "día completo",
    "Sin señales de reunión de trabajo",
    "Solo participantes con correo personal",
    "Todos los participantes comparten",
)


def _skipped_by_calendar_filter(skip_reason: str | None) -> bool:
    if not skip_reason:
        return False
    return any(marker in skip_reason for marker in _FILTER_SKIP_MARKERS)


def _resolve_calendar_org_id(
    db: Session,
    user_id: UUID,
    integration: CalendarIntegration,
) -> UUID:
    """
    Org donde deben guardarse dossiers automáticos: la activa del usuario (JWT),
    no necesariamente la org fijada al conectar el calendario.
    """
    active = active_organization_id_for_user(
        db, user_id, fallback=integration.organization_id
    )
    org_id = active or integration.organization_id
    if integration.organization_id != org_id:
        integration.organization_id = org_id
        db.add(integration)
    return org_id


def sync_calendar_events_for_integration(db: Session, integration: CalendarIntegration) -> int:
    """Importa/actualiza eventos futuros en ``calendar_events``. Devuelve cu?ntos se tocaron."""
    if not integration.is_enabled or integration.revoked_at is not None:
        return 0

    try:
        reuniones = _list_upcoming_reuniones(integration, db)
    except Exception as e:  # noqa: BLE001 - sync en background: un fallo no debe tumbar el worker
        logger.warning(
            "Sync calendario fall? user=%s provider=%s: %s",
            integration.user_id,
            integration.provider,
            e,
        )
        return 0

    advance = effective_advance_minutes(integration)
    now = datetime.now(UTC)
    touched = 0
    user = db.get(User, integration.user_id)
    org_id = _resolve_calendar_org_id(db, integration.user_id, integration)
    org = db.get(Organization, org_id)
    automation_ok = org is not None and plan_allows_automation(org.plan)

    for reunion in reuniones:
        ext_id = (reunion.get("id") or "").strip()
        if not ext_id:
            continue
        starts = parse_event_datetime(reunion.get("inicio"))
        if starts is None or starts <= now:
            continue

        passes, filter_reason = calendar_event_passes_filters(reunion, integration, user)

        ends = parse_event_datetime(reunion.get("fin"))
        scheduled_at = starts - timedelta(minutes=advance)

        row = db.execute(
            select(CalendarEvent).where(
                CalendarEvent.calendar_integration_id == integration.id,
                CalendarEvent.external_event_id == ext_id,
            )
        ).scalar_one_or_none()

        if not passes:
            if row is not None and row.processing_status in ("scheduled", "detected"):
                row.title = (reunion.get("tema") or row.title or "")[:500]
                row.starts_at = starts
                row.ends_at = ends
                row.external_attendees = _attendees_from_participantes(reunion.get("participantes") or "")
                row.event_snapshot = reunion
                row.processing_status = "skipped"
                row.skip_reason = filter_reason
                touched += 1
            continue

        if not automation_ok:
            if row is None:
                row = CalendarEvent(
                    calendar_integration_id=integration.id,
                    organization_id=org_id,
                    user_id=integration.user_id,
                    external_event_id=ext_id,
                    processing_status="skipped",
                )
                db.add(row)
            row.title = (reunion.get("tema") or "")[:500]
            row.starts_at = starts
            row.ends_at = ends
            row.meeting_url = (reunion.get("ubicacion") or None)
            row.external_attendees = _attendees_from_participantes(reunion.get("participantes") or "")
            row.event_snapshot = _event_snapshot_with_output_language(reunion, user)
            row.dossier_scheduled_at = None
            row.processing_status = "skipped"
            row.skip_reason = "Plan Free: la automatización requiere Pro o Enterprise."
            touched += 1
            continue

        if row is not None and row.processing_status == "skipped" and _skipped_by_calendar_filter(
            row.skip_reason
        ):
            row.processing_status = "scheduled"
            row.skip_reason = None
            row.dossier_scheduled_at = scheduled_at

        if row is not None and row.processing_status in ("completed", "processing"):
            row.title = (reunion.get("tema") or row.title or "")[:500]
            row.starts_at = starts
            row.ends_at = ends
            row.external_attendees = _attendees_from_participantes(reunion.get("participantes") or "")
            row.event_snapshot = _event_snapshot_with_output_language(reunion, user)
            touched += 1
            continue

        if row is None:
            row = CalendarEvent(
                calendar_integration_id=integration.id,
                organization_id=org_id,
                user_id=integration.user_id,
                external_event_id=ext_id,
                processing_status="scheduled",
            )
            db.add(row)

        row.organization_id = org_id
        row.title = (reunion.get("tema") or "")[:500]
        row.starts_at = starts
        row.ends_at = ends
        row.meeting_url = (reunion.get("ubicacion") or None)
        row.external_attendees = _attendees_from_participantes(reunion.get("participantes") or "")
        row.event_snapshot = _event_snapshot_with_output_language(reunion, user)
        row.dossier_scheduled_at = scheduled_at
        row.processing_status = "scheduled"
        row.skip_reason = None
        touched += 1

    db.commit()
    return touched


def _mark_past_unprocessed_skipped(db: Session) -> int:
    now = datetime.now(UTC)
    rows = db.execute(
        select(CalendarEvent).where(
            CalendarEvent.processing_status.in_(("scheduled", "detected")),
            CalendarEvent.starts_at <= now,
        )
    ).scalars().all()
    for row in rows:
        row.processing_status = "skipped"
        row.skip_reason = "La reuni?n ya comenz? antes de generar el dossier."
    if rows:
        db.commit()
    return len(rows)


def _generation_skip_reason(result: dict[str, Any]) -> str:
    errors = result.get("errors") or []
    if errors:
        return "; ".join(str(e) for e in errors)[:500]

    parsed = result.get("parse") or {}
    if not (parsed.get("company_corporate") or parsed.get("person_name") or parsed.get("persons")):
        return (
            "No se detect? empresa ni contacto. "
            "Usa ?Empresa: ?? y ?Contacto: ?? / ?Contacto 1: ?? en la descripci?n."
        )

    for key, label in (
        ("dossier_corporativo", "corporativo"),
        ("dossier_persona", "persona"),
    ):
        md = (result.get(key) or "").lstrip()
        if md.startswith("# Error"):
            return f"Error al generar dossier {label}."
        if md.startswith("No se pudo generar ning?n dossier"):
            return "Formato del evento incompleto para generar dossiers."

    for pentry in result.get("dossier_personas") or []:
        md = (pentry.get("md") or "").lstrip()
        if md.startswith("# Error"):
            name = pentry.get("full_name") or "persona"
            return f"Error al generar dossier de {name}."

    return "La generaci?n termin? pero no hubo informe v?lido para guardar."


def _requeue_completed_without_dossiers(db: Session) -> int:
    """Reprograma eventos marcados completed sin filas en ``dossiers`` (fallos de persistencia).

    No aplica a eventos en ``skipped`` (p. ej. dossier eliminado por el usuario).
    """
    now = datetime.now(UTC)
    rows = db.execute(
        select(CalendarEvent).where(
            CalendarEvent.processing_status == "completed",
            CalendarEvent.starts_at > now,
            ~exists(
                select(Dossier.id).where(Dossier.calendar_event_id == CalendarEvent.id)
            ),
        )
    ).scalars().all()
    for row in rows:
        row.processing_status = "scheduled"
        row.skip_reason = None
        row.dossier_scheduled_at = now
    if rows:
        db.commit()
        logger.info("Automatizaci?n: %s evento(s) reprogramados (completed sin dossier)", len(rows))
    return len(rows)


def suppress_calendar_event_if_no_dossiers_remain(
    db: Session,
    calendar_event_id: UUID | None,
) -> None:
    """
    Tras borrar dossiers de calendario: evita que la automatizaci?n los regenere.

    Si el usuario elimin? todos los dossiers ligados al evento, pasa el evento a
    ``skipped`` en lugar de dejarlo en ``completed`` (lo que dispara reintentos).
    """
    if not calendar_event_id:
        return
    remaining = db.execute(
        select(func.count())
        .select_from(Dossier)
        .where(Dossier.calendar_event_id == calendar_event_id)
    ).scalar_one()
    if int(remaining or 0) > 0:
        return
    event = db.get(CalendarEvent, calendar_event_id)
    if event is None:
        return
    event.processing_status = "skipped"
    event.skip_reason = "Dossier eliminado por el usuario; no se regenerar? autom?ticamente."
    logger.info(
        "Calendario: evento %s marcado skipped tras borrado manual de dossiers",
        calendar_event_id,
    )


def process_due_calendar_events(db: Session) -> dict[str, int]:
    """Genera dossiers para eventos cuya ventana de anticipación ya venció."""
    now = datetime.now(UTC)
    stats = {"processed": 0, "failed": 0, "skipped": 0, "requeued": 0}

    stats["requeued"] = _requeue_completed_without_dossiers(db)

    due = db.execute(
        select(CalendarEvent, CalendarIntegration)
        .join(
            CalendarIntegration,
            CalendarEvent.calendar_integration_id == CalendarIntegration.id,
        )
        .where(
            CalendarEvent.processing_status == "scheduled",
            CalendarEvent.dossier_scheduled_at.is_not(None),
            CalendarEvent.dossier_scheduled_at <= now,
            CalendarEvent.starts_at > now,
            CalendarIntegration.is_enabled.is_(True),
            CalendarIntegration.revoked_at.is_(None),
        )
        .order_by(CalendarEvent.dossier_scheduled_at.asc())
        .limit(5)
    ).all()

    stats["due"] = len(due)

    for event, integration in due:
        event.processing_status = "processing"
        db.commit()

        reunion = _reunion_for_processing(integration, db, event)
        if not reunion:
            event.processing_status = "failed"
            event.skip_reason = "No se pudo leer el evento en el calendario."
            stats["failed"] += 1
            db.commit()
            continue

        user = db.get(User, event.user_id)
        org_id = _resolve_calendar_org_id(db, event.user_id, integration)
        if event.organization_id != org_id:
            event.organization_id = org_id
        org = db.get(Organization, org_id)
        if org is None or not plan_allows_automation(org.plan):
            event.processing_status = "skipped"
            event.skip_reason = "Plan Free: la automatización requiere Pro o Enterprise."
            stats["skipped"] += 1
            db.commit()
            continue

        passes, filter_reason = calendar_event_passes_filters(reunion, integration, user)
        if not passes:
            event.processing_status = "skipped"
            event.skip_reason = filter_reason
            stats["skipped"] += 1
            db.commit()
            continue

        org_ctx = format_dossier_context_for_prompt(org) if org else ""
        out_lang = (
            resolve_dossier_output_language_for_user(user) if user else "es"
        )

        t0 = time.perf_counter()
        try:
            result = generate_dossiers_from_calendar_event(
                reunion,
                organization_context_block=org_ctx or None,
                organization_id=org_id,
                organization_plan=org.plan if org else None,
                output_language=out_lang,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            persist_calendar_dossiers(
                db,
                user_id=event.user_id,
                org_id=org_id,
                result=result,
                calendar_provider=integration.provider,
                generation_duration_ms=elapsed_ms,
                calendar_event_id=event.id,
                generation_origin="automatic",
            )
            saved = result.get("saved_dossiers") or {}
            if saved:
                event.processing_status = "completed"
                event.skip_reason = None
                stats["processed"] += 1
            else:
                event.processing_status = "failed"
                event.skip_reason = _generation_skip_reason(result)
                stats["failed"] += 1
                logger.warning(
                    "Automatizaci?n: event=%s sin dossier guardado: %s",
                    event.id,
                    event.skip_reason,
                )
        except Exception as e:
            logger.exception("Automatizaci?n: fallo dossier event=%s", event.id)
            event.processing_status = "failed"
            event.skip_reason = str(e)[:500]
            stats["failed"] += 1

        db.commit()

    stats["skipped"] = _mark_past_unprocessed_skipped(db)
    return stats


def run_calendar_automation_tick(db: Session) -> dict[str, Any]:
    """Un ciclo: sincronizar integraciones activas y procesar eventos pendientes."""
    integrations = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.is_enabled.is_(True),
            CalendarIntegration.revoked_at.is_(None),
        )
    ).scalars().all()

    synced = 0
    for integration in integrations:
        synced += sync_calendar_events_for_integration(db, integration)

    stats = process_due_calendar_events(db)
    advances = {
        effective_advance_minutes(i)
        for i in integrations
        if i.is_enabled and i.revoked_at is None
    }
    advance_report = min(advances) if advances else default_advance_minutes()
    return {
        "integrations": len(integrations),
        "events_synced": synced,
        **stats,
        "advance_minutes": advance_report,
    }
