"""Pipeline de investigación de persona con persistencia en PostgreSQL."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from dossier.billing.credit_policy import (
    assert_sufficient_credits,
    credit_charging_enabled,
    person_research_credit_cost,
)
from dossier.cache.corporate_dossier_redis import cached_until_from_now
from dossier.cache.person_dossier_redis import (
    get_person_cached_payload,
    person_cache_redis_key,
    redis_person_cache_available,
    run_with_person_cache_lock,
    set_person_cached_payload,
)
from dossier.db.models import Dossier, Organization, User
from dossier.llm.common import normalize_person_report_text
from dossier.org_dossier_context import format_dossier_context_for_prompt
from dossier.schemas.person_research import PersonResearchRequest
from dossier.services.calendar_event_dossiers import _person_failure_message
from dossier.services.dossier_entities_writer import escribir_entidades_ejecutivas
from dossier.services.dossier_job_progress import NULL_SCOPE
from dossier.services.output_language import effective_output_language
from dossier.services.person_dossier_dedup import (
    person_research_cache_payload_from_result,
    person_research_fingerprint,
    person_research_response_from_redis_cache,
    profiles_count_from_research_result,
    should_cache_person_research_result,
)
from dossier.services.person_research_progress import (
    CACHE_LOOKUP,
    PERSIST,
    report_cache_hit,
    report_generated,
    report_persisted,
    scope_copy,
)
from dossier.services.person_research_service import run_person_research

logger = logging.getLogger(__name__)


def _preserve_calendar_dossier_metadata(
    existing_data: dict[str, Any] | None,
    new_data: dict[str, Any],
) -> dict[str, Any]:
    """Mantiene vínculo con carpeta de reunión al regenerar un dossier persona."""
    if not isinstance(existing_data, dict):
        return new_data
    for key in ("calendar", "calendar_folder", "calendar_folder_role"):
        val = existing_data.get(key)
        if val is not None:
            new_data[key] = val
    return new_data


def run_person_research_and_persist(
    db: Session,
    *,
    user: User,
    org: Organization,
    body: PersonResearchRequest,
    progress: Any = None,
) -> dict[str, Any]:
    """
    Ejecuta investigación de persona, persiste en ``dossiers`` y devuelve la respuesta API.

    ``progress`` (S5.10) es el scope ``person:0`` del job: recibe la consulta a la
    caché, las etapas de la investigación y el guardado.
    """
    progress = progress if progress is not None else NULL_SCOPE
    org_ctx = format_dossier_context_for_prompt(org)
    out_lang = effective_output_language(user, body.output_language)
    fp = person_research_fingerprint(body, org.id, output_language=out_lang)
    skip_cache = bool(body.force_refresh)
    charge = credit_charging_enabled()
    person_cost = person_research_credit_cost()
    is_refinement = body.replace_dossier_id is not None
    db.refresh(org)

    cache_hit = False
    cached_payload: dict[str, Any] | None = None
    redis_disponible = redis_person_cache_available()
    if skip_cache:
        progress.stage(CACHE_LOOKUP, "skipped", "force_refresh")
    elif not redis_disponible:
        progress.stage(CACHE_LOOKUP, "skipped", "cache_unavailable")
    else:
        progress.stage(CACHE_LOOKUP, "running")
        hit = get_person_cached_payload(fp)
        if hit is not None:
            cached_payload = hit
            cache_hit = True
            progress.stage(CACHE_LOOKUP, "completed", "cache_hit")

    result: dict[str, Any] | None = None
    elapsed_ms = 0
    research_error: str | None = None

    if not cache_hit:
        if not is_refinement:
            assert_sufficient_credits(org, person_cost, charge=charge)

        def _compute() -> None:
            nonlocal cache_hit, cached_payload, result, elapsed_ms, research_error
            if not skip_cache:
                h2 = get_person_cached_payload(fp)
                if h2 is not None:
                    cached_payload = h2
                    cache_hit = True
                    progress.stage(CACHE_LOOKUP, "completed", "cache_hit")
                    return
                if redis_disponible:
                    progress.stage(CACHE_LOOKUP, "completed", "cache_miss")
            t_run = time.perf_counter()
            try:
                nr = run_person_research(
                    body,
                    organization_context_block=org_ctx,
                    output_language=out_lang,
                    progress=progress,
                )
            except ValueError as e:
                research_error = str(e)
                return
            result = nr
            elapsed_ms = int((time.perf_counter() - t_run) * 1000)
            md_new = (result.get("llm_analysis_markdown") or "").strip()
            if should_cache_person_research_result(
                result,
                gemini_only=body.research_source.value == "gemini_web",
            ):
                set_person_cached_payload(
                    fp,
                    {
                        "markdown": md_new,
                        "gemini_google_search_used": result.get("gemini_google_search_used"),
                        **person_research_cache_payload_from_result(result),
                    },
                )
            cache_hit = False

        run_with_person_cache_lock(fp, _compute)
        if research_error is not None:
            raise ValueError(research_error)
    else:
        elapsed_ms = 0

    if cache_hit and cached_payload is not None:
        result = person_research_response_from_redis_cache(
            body,
            organization_context_block=org_ctx,
            cached_payload=cached_payload,
        )
        elapsed_ms = 0
        report_cache_hit(progress, research_source=body.research_source.value, cached_payload=cached_payload)
    elif result is not None:
        report_generated(progress, result)

    if result is None:
        raise RuntimeError(
            "Respuesta de investigación vacía; revisa logs del servidor."
        )

    logger.info(
        "person_research pipeline cache=%s redis=%s force_refresh=%s key_prefix=%s",
        "hit" if cache_hit else "miss",
        redis_person_cache_available(),
        skip_cache,
        fp[:16],
    )

    md = normalize_person_report_text((result.get("llm_analysis_markdown") or "").strip())
    now = datetime.now(UTC)
    cache_row_key = person_cache_redis_key(fp) if cache_hit else None
    cache_expires = cached_until_from_now() if cache_hit else None

    existing: Dossier | None = None
    if body.replace_dossier_id is not None:
        existing = db.get(Dossier, body.replace_dossier_id)
        if existing is None or existing.organization_id != org.id:
            raise ValueError("El dossier a actualizar no existe o no pertenece a tu organización.")

    lusha_diag = None
    person_research_source = "pdl"
    fa = result.get("filters_applied")
    if isinstance(fa, dict) and fa.get("research_source"):
        person_research_source = str(fa["research_source"])
    lusha_diag = {
        "profiles_count": profiles_count_from_research_result(result),
        "profile_urls": result.get("profile_urls") or [],
        "warnings": result.get("warnings") or [],
        "gemini_google_search_used": result.get("gemini_google_search_used"),
        "filters_applied": result.get("filters_applied"),
    }

    progress.stage(PERSIST, "running")
    if md:
        is_err = md.lstrip().startswith("# Error")
        status = "failed" if is_err else "complete"
        will_charge = (
            charge
            and person_cost > 0
            and not is_err
            and not cache_hit
            and existing is None
        )
        dossier_data_body: dict[str, Any] = {
            "format": "markdown",
            "body": md,
            "pipeline": "person_research",
            "success": not is_err,
            "billing": "charged" if will_charge else "none",
            "person_dedup_key": fp,
            "gemini_google_search_used": result.get("gemini_google_search_used"),
            "cache": {
                "hit": cache_hit,
                "redis": redis_person_cache_available(),
            },
            "person_filters": {
                "full_name": body.full_name,
                "job_area": body.job_area,
                "company": body.company,
                "country": body.country,
                "city": body.city,
                "extra_keywords": body.extra_keywords,
                "email": body.email,
                "linkedin_url": body.linkedin_url,
                "research_source": body.research_source.value,
            },
            "lusha_diagnostics": lusha_diag,
            "output_language": out_lang,
            **_progress_copy(progress),
        }
        # S4.3: el contrato validado va junto al Markdown derivado de él; `format`,
        # `body` y `billing` no cambian (los leen el dashboard y el trigger de cobro).
        if result.get("executive_payload"):
            dossier_data_body["executive_payload"] = result["executive_payload"]
        if existing is not None:
            prev = existing.dossier_data if isinstance(existing.dossier_data, dict) else {}
            dossier_data_body = _preserve_calendar_dossier_metadata(prev, dossier_data_body)
            contact_index = (prev.get("person_filters") or {}).get("contact_index")
            if contact_index is not None and isinstance(dossier_data_body.get("person_filters"), dict):
                dossier_data_body["person_filters"]["contact_index"] = contact_index

            existing.subject_name = body.full_name.strip()[:255]
            existing.subject_email = (body.email or "")[:255] or None
            existing.status = status
            existing.status_message = "Error en el informe generado." if is_err else None
            existing.dossier_data = dossier_data_body
            existing.agents_failed = (["deepseek_person_analysis"] if is_err else [])
            existing.generation_started_at = now
            existing.generation_completed_at = now
            existing.generation_duration_ms = elapsed_ms
            existing.cache_key = cache_row_key
            existing.cached_until = cache_expires
            # S4.6: alertas e ideas de conversación en la misma transacción que el dossier.
            escribir_entidades_ejecutivas(
                db,
                dossier_id=existing.id,
                payload=dossier_data_body.get("executive_payload"),
                reemplazo=True,
            )
            db.commit()
            db.refresh(existing)
            dossier = existing
        else:
            dossier_id = uuid.uuid4()
            dossier = Dossier(
                id=dossier_id,
                organization_id=org.id,
                requested_by_user_id=user.id,
                contact_id=None,
                subject_name=body.full_name.strip()[:255],
                subject_email=(body.email or "")[:255] or None,
                module_identity=True,
                module_corporate=False,
                module_media=False,
                depth_level="basic",
                credits_consumed=person_cost if will_charge else 0,
                status=status,
                status_message="Error en el informe generado." if is_err else None,
                dossier_data=dossier_data_body,
                agents_activated=[],
                agents_failed=(["deepseek_person_analysis"] if is_err else []),
                data_sources_used=[person_research_source, "deepseek"],
                generation_started_at=now,
                generation_completed_at=now,
                generation_duration_ms=elapsed_ms,
                cache_key=cache_row_key,
                cached_until=cache_expires,
                trigger_source="manual",
            )
            db.add(dossier)
            # S4.6: alertas e ideas de conversación en la misma transacción que el dossier.
            escribir_entidades_ejecutivas(
                db,
                dossier_id=dossier_id,
                payload=dossier_data_body.get("executive_payload"),
                reemplazo=False,
            )
            db.commit()
            db.refresh(dossier)
            db.refresh(org)

        saved = {
            "id": str(dossier.id),
            "organization_id": str(org.id),
            "status": dossier.status,
            "credits_consumed": dossier.credits_consumed,
            "generation_duration_ms": dossier.generation_duration_ms,
            "replaced": existing is not None,
            "organization_credits_balance": org.credits_balance,
        }
    else:
        status_message = _person_failure_message(
            person_payload=result,
            errors=None,
            person_md=None,
        )
        fail_data: dict[str, Any] = {
            "format": "markdown",
            "body": "",
            "pipeline": "person_research",
            "success": False,
            "billing": "none",
            "person_dedup_key": fp,
            "cache": {
                "hit": cache_hit,
                "redis": redis_person_cache_available(),
            },
            "person_filters": {
                "full_name": body.full_name,
                "job_area": body.job_area,
                "company": body.company,
                "country": body.country,
                "city": body.city,
                "extra_keywords": body.extra_keywords,
                "email": body.email,
                "linkedin_url": body.linkedin_url,
                "research_source": body.research_source.value,
            },
            "lusha_diagnostics": lusha_diag,
            "output_language": out_lang,
            **_progress_copy(progress),
        }
        if existing is not None:
            prev = existing.dossier_data if isinstance(existing.dossier_data, dict) else {}
            fail_data = _preserve_calendar_dossier_metadata(prev, fail_data)
            existing.subject_name = body.full_name.strip()[:255]
            existing.subject_email = (body.email or "")[:255] or None
            existing.status = "failed"
            existing.status_message = status_message
            existing.dossier_data = fail_data
            existing.agents_failed = (["deepseek_person_analysis"])
            existing.generation_started_at = now
            existing.generation_completed_at = now
            existing.generation_duration_ms = elapsed_ms
            existing.cache_key = cache_row_key
            existing.cached_until = cache_expires
            db.commit()
            db.refresh(existing)
            dossier = existing
        else:
            dossier_id = uuid.uuid4()
            dossier = Dossier(
                id=dossier_id,
                organization_id=org.id,
                requested_by_user_id=user.id,
                contact_id=None,
                subject_name=body.full_name.strip()[:255],
                subject_email=(body.email or "")[:255] or None,
                module_identity=True,
                module_corporate=False,
                module_media=False,
                depth_level="basic",
                credits_consumed=0,
                status="failed",
                status_message=status_message,
                dossier_data=fail_data,
                agents_activated=[],
                agents_failed=(["deepseek_person_analysis"]),
                data_sources_used=[person_research_source, "deepseek"],
                generation_started_at=now,
                generation_completed_at=now,
                generation_duration_ms=elapsed_ms,
                trigger_source="manual",
            )
            db.add(dossier)
            db.commit()
            db.refresh(dossier)

        saved = {
            "id": str(dossier.id),
            "organization_id": str(org.id),
            "status": dossier.status,
            "status_message": dossier.status_message,
            "credits_consumed": dossier.credits_consumed,
            "generation_duration_ms": dossier.generation_duration_ms,
            "replaced": existing is not None,
        }
    report_persisted(progress, dossier_id=str(saved["id"]), dossier_status=str(saved["status"]))

    result["saved_dossier"] = saved
    result["dossier_source"] = "generated" if skip_cache else ("redis_cache" if cache_hit else "generated")
    result["force_refresh"] = skip_cache
    return result


def _progress_copy(progress: Any) -> dict[str, Any]:
    """``{"_progress": …}`` para ``dossier_data``, o nada fuera de un job (ADR 0009)."""
    copia = scope_copy(progress)
    return {"_progress": copia} if copia else {}
