"""Análisis narrativo (Gemini) a partir de datos de perfiles públicos."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from dossier.llm.text_generate import generate_text_with_llm
from dossier.services.lusha_profile_facts import format_lusha_verified_facts_block
from dossier.services.person_analysis_prompts import (
    format_meeting_context_block,
    person_dossier_system_prompt,
)
from dossier.services.person_dossier_locales import (
    person_bundle_user_header,
    person_bundle_user_instructions,
)


def _truncate_json(payload: Any, max_chars: int) -> str:
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(raw) <= max_chars:
        return raw
    return raw[: max_chars - 80] + "\n\n… [entrada truncada por tamaño] …\n"


def _header_line(filters: dict[str, Any]) -> str:
    name = str(filters.get("full_name") or "").strip() or "No indicado"
    company = str(filters.get("company") or "").strip() or "No indicada"
    country = str(filters.get("country") or "").strip() or "No indicado"
    city = str(filters.get("city") or "").strip()
    if city:
        country = f"{country} — {city}" if country != "No indicado" else city
    return f"{name} / {company} / {country}"


def _build_user_prompt(
    *,
    filters: dict[str, Any],
    bundle_json: str,
    meeting_context: dict[str, Any] | None = None,
    lusha_verified_facts: dict[str, Any] | None = None,
    enrichment_provider: str = "lusha",
    output_language: str = "es",
) -> str:
    fecha = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    cabecera = _header_line(filters)
    reunion_block = format_meeting_context_block(meeting_context, output_language)
    verified_block = format_lusha_verified_facts_block(
        lusha_verified_facts or {},
        provider=enrichment_provider,
        output_language=output_language,
    )
    src = enrichment_provider.upper()
    header_block = person_bundle_user_header(
        output_language,
        header=cabecera,
        date=fecha,
    )
    instructions = person_bundle_user_instructions(output_language, src)

    return f"""{header_block}

{reunion_block}{verified_block}{instructions}

{bundle_json}
"""


def analyze_person_profile_bundle(
    *,
    filters: dict[str, Any],
    profiles: list[dict[str, Any]],
    posts_by_url: dict[str, Any],
    meeting_context: dict[str, Any] | None = None,
    lusha_verified_facts: dict[str, Any] | None = None,
    enrichment_provider: str = "lusha",
    output_language: str = "es",
) -> str:
    max_chars = int(os.getenv("DEEPSEEK_PERSON_MAX_JSON_CHARS", os.getenv("GEMINI_PERSON_MAX_JSON_CHARS", "120000")))
    bundle: dict[str, Any] = {
        "criterios_de_busqueda": filters,
        "perfiles": profiles,
        "publicaciones_por_url": posts_by_url or {},
    }
    if meeting_context:
        bundle["contexto_reunion"] = meeting_context
    bundle_json = _truncate_json(bundle, max_chars)
    user_prompt = _build_user_prompt(
        filters=filters,
        bundle_json=bundle_json,
        meeting_context=meeting_context,
        lusha_verified_facts=lusha_verified_facts,
        enrichment_provider=enrichment_provider,
        output_language=output_language,
    )
    return generate_text_with_llm(
        user_prompt,
        system_instruction=person_dossier_system_prompt(
            meeting_context=meeting_context,
            output_language=output_language,
        ),
    )
