"""Listado y generación de dossiers persistidos en PostgreSQL (tabla `dossiers` del schema migrado)."""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.api.auth_routes import (
    OrgAuthContext,
    get_db_if_configured,
    get_org_auth_context,
    require_mutator,
)
from dossier.billing.credit_policy import assert_sufficient_credits, person_research_credit_cost
from dossier.billing.entitlements import (
    assert_corporate_dossier_allowed,
    assert_depth_allowed,
    corporate_dossier_module_flags,
)
from dossier.cache.corporate_dossier_redis import (
    build_corporate_cache_key_hash,
    cached_until_from_now,
    corporate_cache_redis_key,
    get_corporate_cached_markdown,
    redis_corporate_cache_available,
    run_with_corporate_cache_lock,
    set_corporate_cached_markdown,
)
from dossier.db.models import Dossier, Organization
from dossier.graphs.corporate_dossier_graph import (
    JurisdictionScope,
    infer_jurisdiction_scope,
    run_corporate_dossier_langgraph,
)
from dossier.org_dossier_context import format_dossier_context_for_prompt
from dossier.schemas.dossier_executive_payload import resumen_contenido_dossier
from dossier.schemas.dossier_generation import (
    DEPTH_CREDITS,
    CreateCorporateDossierRequest,
    build_corporate_generation_strings,
)
from dossier.schemas.dossier_share import DossierShareCreate
from dossier.schemas.person_research import PersonResearchRequest
from dossier.security.rbac import normalize_org_role
from dossier.services.calendar_event_dossiers import calendar_meeting_summary_from_dossier_data
from dossier.services.corporate_company_search import search_corporate_company_candidates
from dossier.services.dossier_deletion_service import (
    delete_dossier_record,
    delete_dossiers_in_folder,
    finalize_dossier_deletions,
)
from dossier.services.dossier_folder_utils import (
    build_dossier_list_entries,
    serialize_dossier_list_item,
    serialize_folder,
)
from dossier.services.dossier_generation_job_service import enqueue_person_research_job
from dossier.services.dossier_share_service import (
    dossier_permissions_payload,
    list_dossier_shares,
)
from dossier.services.dossier_visibility import (
    apply_dossier_visibility,
    get_visible_dossier_or_404,
    user_can_delete_dossier,
)
from dossier.services.output_language import effective_output_language
from dossier.services.person_research_pipeline import run_person_research_and_persist
from dossier.utils.html_text import strip_html_to_plain_line

router = APIRouter(tags=["Dossiers"])
logger = logging.getLogger(__name__)


def _serialize_dossier_list_item(d: Dossier) -> dict:
    return serialize_dossier_list_item(d)


def _corporate_credit_charging_enabled() -> bool:
    """
    Cobro por generación corporativa (profundidad → créditos vía `DEPTH_CREDITS`).

    El descuento de saldo lo hace el trigger PostgreSQL `fn_debit_credits_on_dossier`
    (Migración) cuando `dossier_data->>'billing' != 'none'`. No duplicar descuento en Python.

    Desactivar cobro (p. ej. demos): `DOSSIER_CHARGE_CREDITS=0` en `.env`.
    """

    raw = os.getenv("DOSSIER_CHARGE_CREDITS", "true")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _enterprise_effectively_unlimited(org: Organization) -> bool:
    """Plan Enterprise: sin bloqueo por saldo bajo (informe: créditos ilimitados)."""
    return (org.plan or "").strip().lower() == "enterprise"


def _append_corporate_org_context(markdown: str, org_context_block: str) -> str:
    """Anexa el contexto de la org solicitante (no forma parte de la clave Redis)."""
    o = (org_context_block or "").strip()
    if not o:
        return markdown
    return (
        markdown.rstrip()
        + "\n\n---\n\n### Contexto de la organización solicitante\n\n"
        + o
    )


# Ruta bajo `/dossiers/corporate/...` para no colisionar con `GET /dossiers/{dossier_id}` (un solo segmento).


@router.get("/dossiers/corporate/company-search")
def corporate_company_search(
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    q: str = Query(..., min_length=2, max_length=200),
):
    """Búsqueda UK (Companies House) + US (SEC tickers) para desambiguar nombres de empresa."""
    assert_corporate_dossier_allowed(ctx.org)
    return search_corporate_company_candidates(q)


@router.post("/dossiers/person/research")
def person_professional_research(
    body: PersonResearchRequest,
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    db: Session = Depends(get_db_if_configured),
):
    """
    Investigación de persona: por defecto **PDL** (`research_source=pdl`).
    Alternativa: `gemini_web` (IA + Google Search). Requiere `PDL_API_KEY` para enriquecimiento.

    Con ``async_mode=true`` encola el trabajo y responde de inmediato con ``job_id`` (podés
    navegar por la app; el aviso aparece en el toast global).

    Si se genera texto de informe, se persiste en `dossiers` (misma organización que el JWT),
    como los dossiers corporativos; la respuesta incluye `saved_dossier` con el `id` creado.

    Con ``REDIS_URL`` configurado, reutiliza el informe en Redis para la misma organización
    y mismos filtros. ``dossier_source``: ``redis_cache`` (hit) o ``generated`` (miss).
    """
    user, org = ctx.user, ctx.org
    db.refresh(org)

    if body.async_mode:
        job = enqueue_person_research_job(db, user=user, org=org, body=body)
        return {
            "async": True,
            "job_id": str(job.id),
            "status": job.status,
            "meeting_label": job.meeting_label,
            "credits_estimated": job.credits_estimated,
            "mensaje": (
                "Generación encolada. Podés seguir navegando; te avisaremos cuando termine."
            ),
        }

    if body.replace_dossier_id is None:
        assert_sufficient_credits(org, person_research_credit_cost())

    try:
        return run_person_research_and_persist(db, user=user, org=org, body=body)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/dossiers/corporate/generate")
def generate_corporate_dossier(
    body: CreateCorporateDossierRequest,
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    db: Session = Depends(get_db_if_configured),
):
    """
    Genera un dossier con el **agente corporativo** (LangGraph: UK + USA en paralelo,
    síntesis Gemini) y lo guarda en `dossiers`.

    Si ``REDIS_URL`` está configurado, reutiliza el Markdown de un encargo equivalente
    sin volver a ejecutar el grafo: **no consume créditos** en ese caso.

    Créditos (informe de producto): basic=1, standard=3, deep=5 — solo en generación nueva.
    El saldo se descuenta en PostgreSQL (trigger) salvo `billing: none` o cobro desactivado
    (`DOSSIER_CHARGE_CREDITS=0`). Si el pipeline devuelve error, no se cobra.
    """
    user, org = ctx.user, ctx.org
    charge = _corporate_credit_charging_enabled()
    assert_corporate_dossier_allowed(org)
    assert_depth_allowed(org, body.depth)
    cost = DEPTH_CREDITS[body.depth] if charge else 0
    out_lang = effective_output_language(user, body.output_language)

    db.refresh(org)

    participantes, subject_display = build_corporate_generation_strings(body)

    explicit_scope: JurisdictionScope | None = None
    if body.resolution is not None:
        explicit_scope = (
            "uk_only" if body.resolution.source == "companies_house" else "us_only"
        )
    scope_for_graph: JurisdictionScope = (
        explicit_scope if explicit_scope is not None else infer_jurisdiction_scope(participantes)
    )

    key_hash = build_corporate_cache_key_hash(
        body=body,
        participantes=participantes,
        jurisdiction_scope=scope_for_graph,
        output_language=out_lang,
    )

    cache_hit = False
    markdown_neutral: str | None = None
    if redis_corporate_cache_available():
        hit = get_corporate_cached_markdown(key_hash)
        if hit is not None:
            markdown_neutral = hit
            cache_hit = True

    if not cache_hit:
        assert_sufficient_credits(org, cost, charge=charge)

    descripcion_neutral_parts: list[str] = []
    if body.subject_email:
        descripcion_neutral_parts.append(f"Email participante: {body.subject_email}")
    descripcion_neutral = "\n".join(descripcion_neutral_parts)
    org_ctx = format_dossier_context_for_prompt(org)

    t0 = time.perf_counter()
    if not cache_hit:

        def _compute_under_lock() -> None:
            nonlocal markdown_neutral, cache_hit
            hit2 = get_corporate_cached_markdown(key_hash)
            if hit2 is not None:
                markdown_neutral = hit2
                cache_hit = True
                return
            md = run_corporate_dossier_langgraph(
                tema_reunion=f"Dossier corporativo — {participantes[:200]}",
                participantes=participantes,
                descripcion=descripcion_neutral,
                jurisdiction_scope=explicit_scope,
                output_language=out_lang,
            )
            if not md.lstrip().startswith("# Error"):
                set_corporate_cached_markdown(key_hash, md)
            markdown_neutral = md
            cache_hit = False

        run_with_corporate_cache_lock(key_hash, _compute_under_lock)

    elapsed_ms = 0 if cache_hit else int((time.perf_counter() - t0) * 1000)
    markdown = _append_corporate_org_context(markdown_neutral or "", org_ctx)
    now = datetime.now(UTC)

    is_err = markdown.lstrip().startswith("# Error")
    status = "failed" if is_err else "complete"

    will_charge = charge and cost > 0 and not is_err and not cache_hit

    dossier_id = uuid.uuid4()
    dossier_data_body: dict = {
        "format": "markdown",
        "body": markdown,
        "pipeline": "langgraph_corporate",
        "depth_requested": body.depth,
        "success": not is_err,
        "billing": "charged" if will_charge else "none",
        "cache": {
            "hit": cache_hit,
            "redis_configured": redis_corporate_cache_available(),
            "pipeline_version": (os.getenv("DOSSIER_CACHE_PIPELINE_VERSION") or "1").strip(),
        },
        "output_language": out_lang,
    }
    if body.resolution is not None:
        dossier_data_body["resolution"] = body.resolution.model_dump(mode="json")

    module_flags = corporate_dossier_module_flags(body.depth)
    dossier = Dossier(
        id=dossier_id,
        organization_id=org.id,
        requested_by_user_id=user.id,
        contact_id=None,
        subject_name=subject_display,
        subject_email=body.subject_email,
        module_identity=module_flags["module_identity"],
        module_corporate=module_flags["module_corporate"],
        module_media=module_flags["module_media"],
        depth_level=body.depth,
        credits_consumed=cost if will_charge else 0,
        status=status,
        status_message="Error en síntesis o en el pipeline." if is_err else None,
        dossier_data=dossier_data_body,
        agents_activated=["agent_corporate_uk", "agent_corporate_usa", "synthesize_llm"],
        agents_failed=(["synthesize_llm"] if is_err else []),
        data_sources_used=["companies_house", "sec_edgar", "sec_company_facts", "gemini"],
        generation_started_at=now,
        generation_completed_at=now,
        generation_duration_ms=elapsed_ms,
        cache_key=corporate_cache_redis_key(key_hash) if cache_hit else None,
        cached_until=cached_until_from_now() if cache_hit else None,
        trigger_source="manual",
    )

    db.add(dossier)
    db.commit()
    db.refresh(dossier)
    db.refresh(org)

    return {
        "id": str(dossier.id),
        "organization_id": str(org.id),
        "status": dossier.status,
        "credits_consumed": dossier.credits_consumed,
        "organization_credits_balance": org.credits_balance,
        "generation_duration_ms": dossier.generation_duration_ms,
        "cache_hit": cache_hit,
    }


@router.get("/dossiers/folders/{folder_id}")
def get_dossier_folder(
    folder_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    db: Session = Depends(get_db_if_configured),
):
    """Carpeta con los dossiers (empresa + persona) de un mismo evento de calendario."""
    user, org, role = ctx.user, ctx.org, ctx.role
    stmt = apply_dossier_visibility(
        select(Dossier).where(Dossier.dossier_folder_id == folder_id),
        user_id=user.id,
        organization_id=org.id,
        role=role,
    ).order_by(Dossier.created_at.asc())
    rows = list(db.execute(stmt).scalars().all())
    if not rows:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada.")
    return serialize_folder(rows)


@router.get("/dossiers/{dossier_id}")
def get_dossier_by_id(
    dossier_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    db: Session = Depends(get_db_if_configured),
):
    """Devuelve un dossier si el usuario tiene permiso de lectura."""
    user, org, role = ctx.user, ctx.org, ctx.role
    d = get_visible_dossier_or_404(
        db,
        dossier_id=dossier_id,
        user_id=user.id,
        organization_id=org.id,
        role=role,
    )
    contenido = resumen_contenido_dossier(d.dossier_data)
    return {
        "id": str(d.id),
        "organization_id": str(d.organization_id),
        "requested_by_user_id": str(d.requested_by_user_id),
        "subject_name": strip_html_to_plain_line(d.subject_name, max_len=255) or d.subject_name,
        "subject_email": d.subject_email,
        "status": d.status,
        "depth_level": d.depth_level,
        "credits_consumed": d.credits_consumed,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "dossier_data": d.dossier_data,
        # S4.4: aditivo, no sustituye `dossier_data` (el frontend sigue leyendo `.body`).
        "content_kind": contenido["content_kind"],
        "executive_payload": contenido["executive_payload"],
        "alerts": d.alerts,
        "agents_activated": list(d.agents_activated or []),
        "agents_failed": list(d.agents_failed or []),
        "data_sources_used": list(d.data_sources_used or []),
        "generation_duration_ms": d.generation_duration_ms,
        "status_message": d.status_message,
        "trigger_source": d.trigger_source,
        "dossier_folder_id": str(d.dossier_folder_id) if d.dossier_folder_id else None,
        "calendar_meeting": calendar_meeting_summary_from_dossier_data(
            d.dossier_data if isinstance(d.dossier_data, dict) else None,
            trigger_source=d.trigger_source,
            tz_name=getattr(user, "timezone", None),
        ),
        "permissions": dossier_permissions_payload(
            db,
            dossier=d,
            user_id=user.id,
            organization_id=org.id,
            role=role,
        ),
        "shares": list_dossier_shares(db, dossier_id=d.id),
    }


@router.get("/dossiers/{dossier_id}/shares")
def get_dossier_shares(
    dossier_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    db: Session = Depends(get_db_if_configured),
):
    """Lista usuarios con los que se compartió el dossier."""
    user, org, role = ctx.user, ctx.org, ctx.role
    d = get_visible_dossier_or_404(
        db,
        dossier_id=dossier_id,
        user_id=user.id,
        organization_id=org.id,
        role=role,
    )
    from dossier.org_workspace import read_workspace_kind
    from dossier.services.dossier_share_service import (
        list_dossier_shares,
        user_can_share_dossier,
    )

    if not user_can_share_dossier(
        dossier=d,
        user_id=user.id,
        role=role,
        workspace_kind=read_workspace_kind(org),
    ):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver las comparticiones.")
    return {"dossier_id": str(d.id), "items": list_dossier_shares(db, dossier_id=d.id)}


@router.post("/dossiers/{dossier_id}/shares", status_code=201)
def create_dossier_share(
    dossier_id: UUID,
    body: DossierShareCreate,
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    db: Session = Depends(get_db_if_configured),
):
    """Comparte un dossier con otro miembro de la organización."""
    from dossier.org_workspace import read_workspace_kind
    from dossier.services.dossier_share_service import (
        list_dossier_shares,
        share_dossier_with_user,
        user_can_share_dossier,
    )

    user, org, role = ctx.user, ctx.org, ctx.role
    d = get_visible_dossier_or_404(
        db,
        dossier_id=dossier_id,
        user_id=user.id,
        organization_id=org.id,
        role=role,
    )
    if not user_can_share_dossier(
        dossier=d,
        user_id=user.id,
        role=role,
        workspace_kind=read_workspace_kind(org),
    ):
        raise HTTPException(status_code=403, detail="No tienes permiso para compartir este dossier.")

    share_dossier_with_user(
        db,
        dossier=d,
        shared_with_user_id=body.user_id,
        shared_by_user_id=user.id,
        organization_id=org.id,
    )
    db.commit()
    items = list_dossier_shares(db, dossier_id=d.id)
    created = next((i for i in items if i["user_id"] == str(body.user_id)), items[-1] if items else None)
    return {"dossier_id": str(d.id), "share": created, "items": items}


@router.delete("/dossiers/{dossier_id}/shares/{target_user_id}", status_code=204)
def delete_dossier_share(
    dossier_id: UUID,
    target_user_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    db: Session = Depends(get_db_if_configured),
):
    """Dejar de compartir un dossier con un usuario."""
    from dossier.org_workspace import read_workspace_kind
    from dossier.services.dossier_share_service import (
        unshare_dossier_with_user,
        user_can_share_dossier,
    )

    user, org, role = ctx.user, ctx.org, ctx.role
    d = get_visible_dossier_or_404(
        db,
        dossier_id=dossier_id,
        user_id=user.id,
        organization_id=org.id,
        role=role,
    )
    if not user_can_share_dossier(
        dossier=d,
        user_id=user.id,
        role=role,
        workspace_kind=read_workspace_kind(org),
    ):
        raise HTTPException(status_code=403, detail="No tienes permiso para modificar las comparticiones.")

    if not unshare_dossier_with_user(
        db,
        dossier_id=d.id,
        shared_with_user_id=target_user_id,
    ):
        raise HTTPException(status_code=404, detail="Compartición no encontrada.")
    db.commit()
    return Response(status_code=204)


@router.delete("/dossiers/folders/{folder_id}", status_code=204)
def delete_dossier_folder(
    folder_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    db: Session = Depends(get_db_if_configured),
):
    """Elimina todos los dossiers de una carpeta (p. ej. reunión de calendario)."""
    user, org, role = ctx.user, ctx.org, ctx.role
    rows = db.execute(
        select(Dossier).where(
            Dossier.organization_id == org.id,
            Dossier.dossier_folder_id == folder_id,
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada.")

    if normalize_org_role(role) != "admin" and not all(
        user_can_delete_dossier(
            db,
            dossier=row,
            user_id=user.id,
            organization_id=org.id,
            role=role,
        )
        for row in rows
    ):
        raise HTTPException(
            status_code=403,
            detail="No puedes eliminar una carpeta que contiene dossiers de otros usuarios.",
        )

    deleted = delete_dossiers_in_folder(
        db,
        organization_id=org.id,
        folder_id=folder_id,
    )
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada.")
    db.commit()
    return Response(status_code=204)


@router.delete("/dossiers/{dossier_id}", status_code=204)
def delete_dossier_by_id(
    dossier_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    db: Session = Depends(get_db_if_configured),
):
    """Elimina un dossier si el usuario tiene permiso."""
    user, org, role = ctx.user, ctx.org, ctx.role
    d = db.get(Dossier, dossier_id)
    if d is None or d.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Dossier no encontrado.")
    if not user_can_delete_dossier(
        db,
        dossier=d,
        user_id=user.id,
        organization_id=org.id,
        role=role,
    ):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este dossier.")
    calendar_event_id = delete_dossier_record(db, d)
    db.flush()
    finalize_dossier_deletions(db, {calendar_event_id})
    db.commit()
    return Response(status_code=204)


@router.get("/dossiers")
def list_dossiers_for_org(
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    db: Session = Depends(get_db_if_configured),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Lista dossiers visibles para el usuario según su rol RBAC.

    - admin: todos los de la organización
    - user: propios + compartidos
    - viewer: solo compartidos
    """
    user, org, role = ctx.user, ctx.org, ctx.role
    stmt = apply_dossier_visibility(
        select(Dossier),
        user_id=user.id,
        organization_id=org.id,
        role=role,
    ).order_by(Dossier.created_at.desc()).limit(limit)
    rows = list(db.execute(stmt).scalars().all())
    user_tz = getattr(user, "timezone", None) or "UTC"
    return {
        "organization_id": str(org.id),
        "items": build_dossier_list_entries(rows, tz_name=user_tz),
    }
