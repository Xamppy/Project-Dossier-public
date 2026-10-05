"""
Huella estable para caché Redis de investigación de persona.

Estrategia: reutilizar por **nombre de persona dentro de la organización** (ignora cargo,
país, ciudad, keywords, etc.). El nombre se normaliza quitando tildes/acentos y
mayúsculas, de modo que «Víctor», «Victor» o «VÍCTOR» comparten la misma caché.

Si el encargo incluye empresa, email o LinkedIn, esos campos forman parte de la huella
para no reutilizar un informe generado solo con el nombre cuando el usuario añade datos.

Incluye ``organization_id`` porque el pipeline inyecta contexto de organización en el análisis;
sin eso, dos organizaciones con un mismo nombre compartirían informe (fuga de contexto).

Para invalidar manualmente toda la caché de persona: sube ``DOSSIER_PERSON_CACHE_VERSION`` en ``.env``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import uuid
from typing import Any

from dossier.schemas.person_research import PersonResearchRequest
from dossier.services.output_language import normalize_output_language
from dossier.services.person_research_service import _merge_geo


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _norm_name(s: str | None) -> str:
    """Nombre normalizado: sin acentos, sin mayúsculas, espacios colapsados."""
    if s is None:
        return ""
    t = _strip_accents(str(s)).strip()
    return re.sub(r"\s+", " ", t).casefold()


def _norm_email(s: str | None) -> str:
    if s is None:
        return ""
    return str(s).strip().casefold()


def _norm_linkedin(s: str | None) -> str:
    u = (s or "").strip().lower().rstrip("/")
    if not u:
        return ""
    if not u.startswith("http"):
        u = f"https://{u.lstrip('/')}"
    return u


def _normalized_output_language(req: PersonResearchRequest, explicit: str | None) -> str:
    return normalize_output_language(explicit or req.output_language)


def person_research_fingerprint(
    req: PersonResearchRequest,
    organization_id: uuid.UUID,
    *,
    output_language: str | None = None,
) -> str:
    """
    Hash SHA-256 (hex) para clave Redis ``dossier:person:payload:{hash}``.

    Depende de nombre normalizado, organización, idioma de salida, versión de caché y,
    si existen, empresa / email / LinkedIn del encargo.
    """
    payload: dict[str, Any] = {
        "full_name": _norm_name(req.full_name),
        "organization_id": str(organization_id),
        "output_language": _normalized_output_language(req, output_language),
        "research_source": req.research_source.value,
        "company": _norm_name(req.company),
        "email": _norm_email(req.email),
        "linkedin_url": _norm_linkedin(req.linkedin_url),
        "person_cache_version": (os.getenv("DOSSIER_PERSON_CACHE_VERSION") or "1").strip(),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def person_research_cache_payload_from_result(result: dict[str, Any]) -> dict[str, Any]:
    """Campos de enriquecimiento a persistir junto al markdown en Redis."""
    profiles = result.get("profiles") or []
    warnings = result.get("warnings") or []
    return {
        "profiles_count": len(profiles),
        "profile_urls": list(result.get("profile_urls") or []),
        "warnings": [w for w in warnings if isinstance(w, str) and w.strip()],
        "executive_payload": result.get("executive_payload"),
    }


def should_cache_person_research_result(
    result: dict[str, Any],
    *,
    gemini_only: bool,
) -> bool:
    """Evita cachear búsquedas PDL sin match (el usuario puede reintentar con más datos)."""
    md = (result.get("llm_analysis_markdown") or "").strip()
    if not md or md.lstrip().startswith("# Error"):
        return False
    if gemini_only:
        return True
    return len(result.get("profiles") or []) > 0


def person_research_response_from_redis_cache(
    req: PersonResearchRequest,
    *,
    organization_context_block: str | None,
    cached_payload: dict[str, Any],
) -> dict[str, Any]:
    """Forma compatible con ``run_person_research`` para hits de Redis."""
    markdown = str(cached_payload.get("markdown") or "")
    profiles_count = int(cached_payload.get("profiles_count") or 0)
    profile_urls = cached_payload.get("profile_urls") or []
    warnings = cached_payload.get("warnings") or []
    if not isinstance(profile_urls, list):
        profile_urls = []
    if not isinstance(warnings, list):
        warnings = []
    profile_urls = [u for u in profile_urls if isinstance(u, str) and u.strip()]
    warnings = [w for w in warnings if isinstance(w, str) and w.strip()]
    return {
        "filters_applied": {
            "full_name": req.full_name,
            "job_area": req.job_area,
            "company": req.company,
            "country": req.country,
            "city": req.city,
            "email": req.email,
            "linkedin_url": req.linkedin_url,
            "extra_keywords": req.extra_keywords,
            "contexto_organizacion_cliente": (organization_context_block or "").strip() or None,
            "geo_effective": _merge_geo(req.country, req.city),
            "start": req.start,
            "max_profiles": req.max_profiles,
            "include_posts": req.include_posts,
            "research_source": req.research_source.value,
            "research_mode": "redis_cache",
            "profiles_count": profiles_count,
        },
        "search_attempts": [],
        "profile_urls": profile_urls,
        "profiles": [],
        "posts_by_url": {},
        "llm_analysis_markdown": markdown.strip() or None,
        "executive_payload": cached_payload.get("executive_payload"),
        "gemini_google_search_used": cached_payload.get("gemini_google_search_used"),
        "warnings": warnings,
    }


def profiles_count_from_research_result(result: dict[str, Any]) -> int:
    fa = result.get("filters_applied")
    if isinstance(fa, dict) and isinstance(fa.get("profiles_count"), int):
        return int(fa["profiles_count"])
    return len(result.get("profiles") or [])
