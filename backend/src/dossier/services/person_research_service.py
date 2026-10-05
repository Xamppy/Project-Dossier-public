"""Orquestación: investigación de persona con PDL (People Data Labs) o búsqueda web (IA)."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from dossier.llm.client import deepseek_api_key
from dossier.llm.common import normalize_person_report_text
from dossier.llm.structured_synthesis import StructuredSynthesisError
from dossier.schemas.dossier_executive_payload import SourceCitation, SourceType
from dossier.schemas.person_research import PersonResearchRequest, PersonResearchSource
from dossier.services.executive_markdown import render_executive_markdown
from dossier.services.lusha_profile_facts import (
    merge_lusha_profiles_facts,
)
from dossier.services.pdl_research import fetch_pdl_profiles
from dossier.services.person_gemini_analysis import (
    analyze_person_profile_bundle,
    analyze_person_profile_bundle_structured,
)
from dossier.services.person_gemini_web_research import analyze_person_with_google_search
from dossier.services.source_provenance import normalizar_procedencia_fuentes


def _s(v: str | None) -> str | None:
    if v is None:
        return None
    t = v.strip()
    return t or None


def _merge_geo(country: str | None, city: str | None) -> str | None:
    c = _s(country)
    ci = _s(city)
    if ci and c:
        return f"{ci}, {c}"
    return c or ci


def _filters_for_person_gemini(
    req: PersonResearchRequest, organization_context_block: str | None
) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "full_name": req.full_name,
        "job_area": req.job_area,
        "company": req.company,
        "country": req.country,
        "city": req.city,
        "extra_keywords": req.extra_keywords,
    }
    oc = (organization_context_block or "").strip()
    if oc:
        filters["contexto_organizacion_cliente"] = oc
    return filters


def _person_web_disabled() -> bool:
    return (os.getenv("DEEPSEEK_DISABLE_PERSON_WEB") or os.getenv("GEMINI_DISABLE_GOOGLE_SEARCH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _person_web_always() -> bool:
    """Si true, ejecuta también DeepSeek web aunque PDL haya devuelto perfiles."""
    v = (os.getenv("DEEPSEEK_PERSON_WEB_ALWAYS") or os.getenv("GEMINI_PERSON_WEB_ALWAYS") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def _synthesize_person_report(
    *,
    filters: dict[str, Any],
    profiles: list[dict[str, Any]],
    meeting_context: dict[str, Any] | None,
    verified_facts: dict[str, Any],
    output_language: str,
    warnings: list[str],
    fuentes_consultadas: list[SourceCitation],
) -> tuple[str | None, dict[str, Any] | None]:
    """Una llamada JSON (S4.2) con el Markdown derivado por código.

    Si el JSON no valida tras el reintento asistido, se genera el informe Markdown
    de siempre. Los errores del proveedor no se reintentan aquí: fallarían igual.
    """
    try:
        payload = analyze_person_profile_bundle_structured(
            filters=filters,
            profiles=profiles,
            posts_by_url={},
            meeting_context=meeting_context,
            lusha_verified_facts=verified_facts,
            enrichment_provider="pdl",
            output_language=output_language,
        )
    except StructuredSynthesisError as e:
        warnings.append(f"La síntesis JSON no validó ({e}); se generó el informe en Markdown.")
        markdown = analyze_person_profile_bundle(
            filters=filters,
            profiles=profiles,
            posts_by_url={},
            meeting_context=meeting_context,
            lusha_verified_facts=verified_facts,
            enrichment_provider="pdl",
            output_language=output_language,
        )
        return markdown, None
    # OE5/S4.7: el LLM no decide la procedencia. Se reescribe con las fuentes
    # realmente consultadas antes de renderizar el Markdown y de persistir el
    # payload, para que ambos coincidan.
    payload = normalizar_procedencia_fuentes(payload, fuentes_consultadas)
    return render_executive_markdown(payload, output_language), payload.model_dump(mode="json")


def run_person_research(
    req: PersonResearchRequest,
    *,
    organization_context_block: str | None = None,
    meeting_context: dict[str, Any] | None = None,
    output_language: str | None = None,
) -> dict[str, Any]:
    from dossier.services.output_language import normalize_output_language

    out_lang = normalize_output_language(output_language or req.output_language)
    warnings: list[str] = []
    gemini_only = req.research_source == PersonResearchSource.gemini_web
    research_mode: str = "gemini_web" if gemini_only else "pdl_plus_gemini"

    attempts: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    profile_urls: list[str] = []
    source_citations: list[SourceCitation] = []

    if not gemini_only:
        profiles, attempts, pdl_warnings = fetch_pdl_profiles(req)
        warnings.extend(pdl_warnings)
        if profiles:
            # OE5/S4.7: la hora de consulta la fija el código al momento de
            # llamar a PDL, no el LLM de síntesis (que la inventaría).
            source_citations.append(
                SourceCitation(
                    source_type=SourceType.pdl,
                    source_name="People Data Labs",
                    retrieved_at=datetime.now(UTC),
                    url=None,
                    record_id=None,
                )
            )
        for p in profiles:
            profile_urls.extend(u for u in (p.get("linkedin_urls") or []) if u not in profile_urls)

    if req.include_posts and not gemini_only:
        warnings.append("La opción «incluir posts» no está disponible; se ignoró.")

    llm_md: str | None = None
    executive_payload: dict[str, Any] | None = None
    gemini_google_search_used = False
    has_llm_key = bool(deepseek_api_key())
    filters_gem = _filters_for_person_gemini(req, organization_context_block)
    verified_facts = merge_lusha_profiles_facts(profiles) if profiles else {}

    md_web: str | None = None
    run_web = has_llm_key and not _person_web_disabled() and (
        gemini_only or (not profiles) or _person_web_always()
    )
    if run_web and profiles and not gemini_only and not _person_web_always():
        run_web = False
    if run_web:
        try:
            md_web = analyze_person_with_google_search(
                filters=filters_gem,
                meeting_context=meeting_context,
                output_language=out_lang,
            )
            gemini_google_search_used = True
        except RuntimeError as e:
            warnings.append(str(e))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Error en análisis complementario con DeepSeek: {e!s}")

    if gemini_only:
        if md_web:
            llm_md = md_web
        elif not has_llm_key:
            warnings.append(
                "Sin DEEPSEEK_API_KEY no se puede ejecutar la búsqueda por IA."
            )
        elif _person_web_disabled():
            warnings.append(
                "DEEPSEEK_DISABLE_PERSON_WEB=1: con «búsqueda por IA» no hay otra fuente; no se generó informe."
            )
    elif profiles and not has_llm_key:
        warnings.append(
            "DEEPSEEK_API_KEY no configurada: se omitió el análisis con IA sobre los datos encontrados."
        )
    elif profiles:
        try:
            llm_md, executive_payload = _synthesize_person_report(
                filters=filters_gem,
                profiles=profiles,
                meeting_context=meeting_context,
                verified_facts=verified_facts,
                output_language=out_lang,
                warnings=warnings,
                fuentes_consultadas=source_citations,
            )
            if md_web and not llm_md:
                llm_md = md_web
            elif md_web and llm_md:
                warnings.append(
                    "Búsqueda web complementaria omitida: el análisis principal "
                    "ya incluye la estructura completa."
                )
        except RuntimeError as e:
            warnings.append(str(e))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Error en análisis sobre perfiles: {e!s}")
        if llm_md is None and md_web:
            llm_md = md_web
    elif not gemini_only and not profiles:
        if md_web:
            llm_md = md_web
        elif not has_llm_key:
            warnings.append(
                "Sin datos de enriquecimiento y sin DEEPSEEK_API_KEY: no se pudo ejecutar el análisis con IA."
            )
        elif _person_web_disabled():
            warnings.append(
                "Sin datos de enriquecimiento y DEEPSEEK_DISABLE_PERSON_WEB=1: no se ejecutó el análisis con IA."
            )

    llm_md = normalize_person_report_text(llm_md)

    return {
        "filters_applied": {
            "full_name": req.full_name,
            "job_area": req.job_area,
            "company": req.company,
            "email": req.email,
            "linkedin_url": req.linkedin_url,
            "country": req.country,
            "city": req.city,
            "extra_keywords": req.extra_keywords,
            "contexto_organizacion_cliente": (organization_context_block or "").strip()
            or None,
            "geo_effective": _merge_geo(req.country, req.city),
            "start": req.start,
            "max_profiles": req.max_profiles,
            "reveal_contact_details": req.reveal_contact_details,
            "include_posts": req.include_posts,
            "research_source": req.research_source.value,
            "research_mode": research_mode,
            "output_language": out_lang,
            "enrichment_provider": "pdl" if not gemini_only else None,
            "pdl_used": not gemini_only,
            "profiles_count": len(profiles),
            "verified_facts": verified_facts if profiles else None,
            "lusha_verified_facts": verified_facts if profiles else None,
        },
        "search_attempts": attempts,
        "profile_urls": profile_urls[: req.max_profiles],
        "profiles": profiles,
        "posts_by_url": {},
        "llm_analysis_markdown": llm_md,
        "executive_payload": executive_payload,
        "gemini_google_search_used": gemini_google_search_used,
        "warnings": warnings,
    }
