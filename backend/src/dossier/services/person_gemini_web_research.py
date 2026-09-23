"""
Informe de persona con DeepSeek (sin búsqueda web en vivo).

Cuando PDL no devuelve perfiles, el modelo redacta el informe a partir del encargo
y del conocimiento del modelo (sin grounding en buscadores externos).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from dossier.config import load_env
from dossier.llm.client import chat_completion, deepseek_api_key, deepseek_model
from dossier.services.person_analysis_prompts import (
    format_meeting_context_block,
    person_dossier_system_prompt,
)
from dossier.services.person_dossier_locales import person_web_research_strings


def _fv(filters: dict[str, Any], key: str, default: str) -> str:
    v = filters.get(key)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _geo_line(filters: dict[str, Any], *, not_indicated: str) -> str:
    country = (filters.get("country") or "").strip()
    city = (filters.get("city") or "").strip()
    if not country and not city:
        return not_indicated
    if city and country:
        return f"{city}, {country}"
    return city or country


def _name_title_case_words(name: str) -> str:
    return " ".join((w[:1].upper() + w[1:].lower()) if w else "" for w in name.split())


def _context_line(filters: dict[str, Any], strings: dict[str, str]) -> str:
    not_indicated = strings["not_indicated"]
    parts: list[str] = []
    org = _fv(filters, "contexto_organizacion_cliente", not_indicated)
    if org != not_indicated:
        parts.append(f"{strings['org_context']}: {org}")
    extra = _fv(filters, "extra_keywords", not_indicated)
    if extra != not_indicated:
        parts.append(f"{strings['keywords']}: {extra}")
    if not parts:
        return not_indicated
    return " | ".join(parts)


def _build_user_prompt(
    filters: dict[str, Any],
    meeting_context: dict[str, Any] | None = None,
    output_language: str = "es",
) -> str:
    strings = person_web_research_strings(output_language)
    not_indicated = strings["not_indicated"]
    fecha = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    nombre = _fv(filters, "full_name", not_indicated)
    nombre_fmt = _name_title_case_words(nombre)
    empresa = _fv(filters, "company", not_indicated)
    cargo = _fv(filters, "job_area", not_indicated)
    geo = _geo_line(filters, not_indicated=not_indicated)
    ctx = _context_line(filters, strings)
    reunion_block = format_meeting_context_block(meeting_context, output_language)

    return f"""{strings['title'].format(date=fecha)}

- {strings['name']}: {nombre} ({strings['variant']}: {nombre_fmt})
- {strings['context']}: {ctx}
- {strings['geo']}: {geo}
- {strings['company']}: {empresa}
- {strings['role']}: {cargo}

{reunion_block}---

{strings['instructions']}

{strings['body']}"""


def analyze_person_with_google_search(
    *,
    filters: dict[str, Any],
    meeting_context: dict[str, Any] | None = None,
    model: str | None = None,
    max_retries: int = 3,
    output_language: str = "es",
) -> str:
    """
    Informe OSINT de persona vía DeepSeek (nombre histórico de la función).
    """
    load_env()
    if not deepseek_api_key():
        raise RuntimeError(
            "Falta DEEPSEEK_API_KEY en `.env` para el informe de persona con IA."
        )

    if (os.getenv("DEEPSEEK_DISABLE_PERSON_WEB") or os.getenv("GEMINI_DISABLE_GOOGLE_SEARCH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        raise RuntimeError(
            "El informe de persona por IA está desactivado (DEEPSEEK_DISABLE_PERSON_WEB=1)."
        )

    m = (
        model
        or os.getenv("DEEPSEEK_PERSON_WEB_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or deepseek_model()
    ).strip()

    user_prompt = _build_user_prompt(filters, meeting_context, output_language)
    return chat_completion(
        user_prompt,
        system_instruction=person_dossier_system_prompt(
            meeting_context=meeting_context,
            output_language=output_language,
        ),
        model=m,
        max_retries=max_retries,
    )
