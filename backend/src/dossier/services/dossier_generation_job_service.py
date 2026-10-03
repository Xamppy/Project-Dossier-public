"""Servicio de jobs de generación asíncrona de dossiers."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.billing.credit_policy import (
    PERSON_IDENTITY_CREDITS,
    assert_sufficient_credits,
    calendar_event_credit_estimate,
    credit_charging_enabled,
    person_research_credit_cost,
)
from dossier.billing.entitlements import assert_depth_allowed, plan_allows_calendar_corporate_dossier
from dossier.db.models import (
    CalendarEvent,
    CalendarIntegration,
    DossierGenerationJob,
    Organization,
    User,
)
from dossier.org_dossier_context import format_dossier_context_for_prompt
from dossier.schemas.dossier_generation import DEPTH_CREDITS, DossierDepth
from dossier.schemas.person_research import PersonResearchRequest
from dossier.services.calendar_event_dossiers import (
    build_calendar_meeting_label,
    generate_dossiers_from_calendar_event,
    parse_calendar_event_for_dossiers,
    persist_calendar_dossiers,
)
from dossier.services.google_calendar_api import obtener_reunion_google_por_id
from dossier.services.google_calendar_token import get_google_calendar_access_token_for_user
from dossier.services.graph_calendar import merge_reunion_payload, obtener_reunion_por_id
from dossier.services.microsoft_calendar_token import get_microsoft_graph_access_token_for_user
from dossier.services.output_language import effective_output_language
from dossier.services.person_dossier_dedup import person_research_fingerprint
from dossier.services.person_research_pipeline import run_person_research_and_persist

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("queued", "running")
_CANCELLABLE_STATUSES = ("queued", "running")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat()


def serialize_job(job: DossierGenerationJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "status": job.status,
        "job_type": job.job_type,
        "calendar_provider": job.calendar_provider,
        "external_event_id": job.external_event_id,
        "meeting_label": job.meeting_label,
        "credits_estimated": job.credits_estimated,
        "credits_consumed": job.credits_consumed,
        "error_message": job.error_message,
        "result": job.result_payload,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "completed_at": _iso(job.completed_at),
    }


def estimate_reunion_credits(
    reunion: dict[str, Any],
    *,
    depth: DossierDepth = "standard",
    plan: str | None = None,
) -> int:
    parsed = parse_calendar_event_for_dossiers(reunion)
    has_corporate = bool(parsed.get("company_corporate") or parsed.get("participantes"))
    if not plan_allows_calendar_corporate_dossier(plan):
        has_corporate = False
    persons = parsed.get("persons") or []
    person_count = len(persons)
    if person_count == 0 and len((parsed.get("person_name") or "").strip()) >= 2:
        person_count = 1
    return calendar_event_credit_estimate(
        has_corporate=has_corporate,
        person_count=person_count,
        depth=depth,
    )


def find_internal_calendar_event_id(
    db: Session,
    *,
    user_id: UUID,
    provider: str,
    external_event_id: str | None,
) -> UUID | None:
    """Evento interno de la automatización que corresponde a la reunión, si existe.

    La identidad es proveedor + evento externo **del propio usuario**: el mismo id de otro
    usuario o de otro proveedor nunca se enlaza. No crea eventos: consultar no programa nada.
    """
    ext = (external_event_id or "").strip()
    if not ext:
        return None
    stmt = (
        select(CalendarEvent.id)
        .join(CalendarIntegration, CalendarEvent.calendar_integration_id == CalendarIntegration.id)
        .where(
            CalendarEvent.user_id == user_id,
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == provider,
            CalendarEvent.external_event_id == ext,
        )
        .limit(1)
    )
    return db.scalars(stmt).first()


def find_active_job_for_event(
    db: Session,
    *,
    user_id: UUID,
    external_event_id: str,
) -> DossierGenerationJob | None:
    stmt = (
        select(DossierGenerationJob)
        .where(
            DossierGenerationJob.requested_by_user_id == user_id,
            DossierGenerationJob.external_event_id == external_event_id,
            DossierGenerationJob.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(DossierGenerationJob.created_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def find_active_person_job(
    db: Session,
    *,
    user_id: UUID,
    dedup_key: str,
) -> DossierGenerationJob | None:
    stmt = (
        select(DossierGenerationJob)
        .where(
            DossierGenerationJob.requested_by_user_id == user_id,
            DossierGenerationJob.external_event_id == dedup_key,
            DossierGenerationJob.job_type == "person_manual",
            DossierGenerationJob.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(DossierGenerationJob.created_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def enqueue_person_research_job(
    db: Session,
    *,
    user: User,
    org: Organization,
    body: PersonResearchRequest,
) -> DossierGenerationJob:
    out_lang = effective_output_language(user, body.output_language)
    fp = person_research_fingerprint(body, org.id, output_language=out_lang)
    dedup_key = f"person:{fp}"
    existing = find_active_person_job(db, user_id=user.id, dedup_key=dedup_key)
    if existing:
        return existing

    label = body.full_name.strip()[:512] or "Persona"
    charge = credit_charging_enabled()
    is_refinement = body.replace_dossier_id is not None
    credits = 0 if is_refinement else person_research_credit_cost()
    db.refresh(org)
    if not is_refinement:
        assert_sufficient_credits(org, credits, charge=charge)

    job = DossierGenerationJob(
        id=uuid.uuid4(),
        organization_id=org.id,
        requested_by_user_id=user.id,
        status="queued",
        job_type="person_manual",
        calendar_provider=None,
        external_event_id=dedup_key,
        reunion_snapshot={"person_request": body.model_dump(mode="json")},
        depth_level="basic",
        meeting_label=label,
        credits_estimated=credits,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def cancel_dossier_generation_job(
    db: Session,
    *,
    job: DossierGenerationJob,
) -> DossierGenerationJob:
    if job.status not in _CANCELLABLE_STATUSES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=409,
            detail="Este dossier ya no se puede cancelar (terminó o falló).",
        )
    job.status = "cancelled"
    job.error_message = "Cancelado por el usuario"
    job.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job


def enqueue_calendar_dossier_job(
    db: Session,
    *,
    user: User,
    org: Organization,
    reunion: dict[str, Any],
    calendar_provider: str,
    depth: DossierDepth = "standard",
) -> DossierGenerationJob:
    event_id = (reunion.get("id") or "").strip() or None
    if event_id:
        existing = find_active_job_for_event(db, user_id=user.id, external_event_id=event_id)
        if existing:
            return existing

    charge = credit_charging_enabled()
    credits = estimate_reunion_credits(reunion, depth=depth, plan=org.plan)
    db.refresh(org)
    assert_depth_allowed(org, depth)
    assert_sufficient_credits(org, credits, charge=charge)

    meeting_label = build_calendar_meeting_label(reunion)
    job = DossierGenerationJob(
        id=uuid.uuid4(),
        organization_id=org.id,
        requested_by_user_id=user.id,
        status="queued",
        job_type="calendar_manual",
        calendar_provider=calendar_provider,
        external_event_id=event_id,
        reunion_snapshot=dict(reunion),
        depth_level=depth,
        meeting_label=meeting_label[:512] if meeting_label else None,
        credits_estimated=credits,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _refresh_reunion_for_job(
    db: Session,
    *,
    user_id: UUID,
    calendar_provider: str,
    external_event_id: str | None,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    base = dict(snapshot or {})
    if not external_event_id:
        return base
    try:
        if calendar_provider == "google":
            token = get_google_calendar_access_token_for_user(db, user_id)
            fresh = obtener_reunion_google_por_id(token, external_event_id)
        else:
            token = get_microsoft_graph_access_token_for_user(db, user_id)
            fresh = obtener_reunion_por_id(token, external_event_id)
        if fresh:
            merged = merge_reunion_payload(base, fresh)
            return merged if merged else fresh
    except Exception:
        logger.warning(
            "Job calendario: no se pudo refrescar evento %s (%s); se usa snapshot",
            external_event_id,
            calendar_provider,
            exc_info=True,
        )
    return base


def _credits_consumed_from_saved(
    saved: dict[str, Any],
    *,
    depth: DossierDepth,
    charge: bool,
    result: dict[str, Any] | None = None,
) -> int:
    if not charge:
        return 0
    r = result or {}
    total = 0
    corp = saved.get("corporate")
    if corp and corp.get("status") == "complete" and not r.get("corporate_cache_hit"):
        total += DEPTH_CREDITS[depth]
    person_refs = saved.get("persons") or []
    if not person_refs and saved.get("person"):
        person_refs = [saved["person"]]
    for pref in person_refs:
        if pref and pref.get("status") == "complete" and not pref.get("cache_hit"):
            total += PERSON_IDENTITY_CREDITS
    return total


def _calendar_job_failure_message(item: dict[str, Any]) -> str | None:
    """None si el job puede marcarse completed; mensaje si debe fallar."""
    saved = item.get("saved_dossiers") or {}
    corporate = saved.get("corporate")
    person_refs = saved.get("persons") or []
    person = saved.get("person")
    if not person_refs and person:
        person_refs = [person]
    if not corporate and not person_refs:
        errors = item.get("errors") or []
        if errors:
            return "; ".join(str(e) for e in errors)[:500]
        return "No se guardó ningún dossier para esta reunión."

    has_complete = any(
        ref and ref.get("status") == "complete"
        for ref in ([corporate] if corporate else []) + person_refs
        if ref
    )
    if has_complete:
        return None

    parts: list[str] = []
    if corporate and corporate.get("status") == "failed":
        parts.append("corporativo")
    failed_persons = [p for p in person_refs if p and p.get("status") == "failed"]
    if failed_persons:
        if len(person_refs) > 1:
            parts.append(f"persona ({len(failed_persons)} de {len(person_refs)})")
        else:
            parts.append("persona")
    if parts:
        return f"No se pudo generar el dossier {' ni '.join(parts)}."
    return "No se guardó ningún dossier válido para esta reunión."


def process_dossier_generation_job(db: Session, job_id: UUID) -> None:
    job = db.get(DossierGenerationJob, job_id)
    if job is None or job.status not in ("queued", "running"):
        return

    if job.status == "queued":
        now = datetime.now(UTC)
        job.status = "running"
        job.started_at = now
        db.commit()

    try:
        if job.job_type == "person_manual":
            _process_person_manual_job(db, job)
        else:
            _process_calendar_manual_job(db, job)
    except Exception as exc:
        logger.exception("Job dossier %s falló", job_id)
        db.rollback()
        job = db.get(DossierGenerationJob, job_id)
        if job is not None and job.status != "cancelled":
            job.status = "failed"
            job.error_message = str(exc)[:2000]
            job.completed_at = datetime.now(UTC)
            db.commit()


def _process_person_manual_job(db: Session, job: DossierGenerationJob) -> None:
    org = db.get(Organization, job.organization_id)
    user = db.get(User, job.requested_by_user_id)
    if org is None or user is None:
        raise RuntimeError("Organización o usuario del job no encontrados.")

    snapshot = job.reunion_snapshot or {}
    raw_req = snapshot.get("person_request")
    if not isinstance(raw_req, dict):
        raise RuntimeError("Snapshot de persona inválido en el job.")

    body = PersonResearchRequest.model_validate(raw_req)
    result = run_person_research_and_persist(db, user=user, org=org, body=body)

    db.refresh(job)
    if job.status == "cancelled":
        logger.info("Job persona %s cancelado; no se actualiza el resultado", job.id)
        return

    job.result_payload = result
    saved = result.get("saved_dossier")
    if not saved or not saved.get("id") or saved.get("status") == "failed":
        job.status = "failed"
        job.error_message = (
            (saved or {}).get("status_message")
            or "; ".join(str(w) for w in (result.get("warnings") or [])[:3])
            or "No se pudo guardar el dossier de persona."
        )[:2000]
    else:
        job.status = "completed"
        job.error_message = None
    job.completed_at = datetime.now(UTC)
    saved = result.get("saved_dossier") or {}
    job.credits_consumed = int(saved.get("credits_consumed") or 0)
    db.commit()
    logger.info("Job persona %s %s (subject=%s)", job.id, job.status, body.full_name[:80])


def _process_calendar_manual_job(db: Session, job: DossierGenerationJob) -> None:
    org = db.get(Organization, job.organization_id)
    user = db.get(User, job.requested_by_user_id)
    if org is None or user is None:
        raise RuntimeError("Organización o usuario del job no encontrados.")

    reunion = _refresh_reunion_for_job(
        db,
        user_id=user.id,
        calendar_provider=job.calendar_provider or "microsoft",
        external_event_id=job.external_event_id,
        snapshot=job.reunion_snapshot,
    )
    org_ctx = format_dossier_context_for_prompt(org)
    depth: DossierDepth = job.depth_level if job.depth_level in DEPTH_CREDITS else "standard"
    charge = credit_charging_enabled()
    assert_depth_allowed(org, depth)

    t0 = time.perf_counter()
    snap = job.reunion_snapshot if isinstance(job.reunion_snapshot, dict) else {}
    snap_lang = snap.get("_output_language") or (
        reunion.get("_output_language") if isinstance(reunion, dict) else None
    )
    out_lang = effective_output_language(user, snap_lang)
    item = generate_dossiers_from_calendar_event(
        reunion,
        organization_context_block=org_ctx,
        organization_id=org.id,
        organization_plan=org.plan,
        depth=depth,
        output_language=out_lang,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    db.refresh(job)
    if job.status == "cancelled":
        logger.info("Job calendario %s cancelado; se omite persistencia", job.id)
        return

    item = persist_calendar_dossiers(
        db,
        user_id=user.id,
        org_id=org.id,
        result=item,
        calendar_provider=job.calendar_provider or "microsoft",
        generation_duration_ms=elapsed_ms,
        depth=depth,
        charge_credits=charge,
        trigger_source="manual",
        calendar_event_id=find_internal_calendar_event_id(
            db,
            user_id=user.id,
            provider=job.calendar_provider or "microsoft",
            external_event_id=job.external_event_id,
        ),
        generation_origin="manual",
        generation_run_key=str(job.id),
    )

    saved = item.get("saved_dossiers") or {}
    job.credits_consumed = _credits_consumed_from_saved(
        saved, depth=depth, charge=charge, result=item
    )
    job.result_payload = item
    failure = _calendar_job_failure_message(item)
    if failure:
        job.status = "failed"
        job.error_message = failure
    else:
        job.status = "completed"
        job.error_message = None
    job.completed_at = datetime.now(UTC)
    db.commit()
    logger.info(
        "Job dossier %s %s (event=%s, credits=%s)",
        job.id,
        job.status,
        job.external_event_id,
        job.credits_consumed,
    )


def claim_next_queued_job(db: Session) -> DossierGenerationJob | None:
    """Claim atómico del job más antiguo en cola (seguro con varios workers)."""
    job = db.scalars(
        select(DossierGenerationJob)
        .where(DossierGenerationJob.status == "queued")
        .order_by(DossierGenerationJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    now = datetime.now(UTC)
    job.status = "running"
    job.started_at = now
    db.commit()
    db.refresh(job)
    return job


def list_jobs_for_user(
    db: Session,
    *,
    user_id: UUID,
    org_id: UUID,
    active_only: bool = False,
    limit: int = 30,
) -> list[DossierGenerationJob]:
    stmt = (
        select(DossierGenerationJob)
        .where(
            DossierGenerationJob.requested_by_user_id == user_id,
            DossierGenerationJob.organization_id == org_id,
        )
        .order_by(DossierGenerationJob.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    if active_only:
        stmt = stmt.where(DossierGenerationJob.status.in_(_ACTIVE_STATUSES))
    return list(db.scalars(stmt).all())
