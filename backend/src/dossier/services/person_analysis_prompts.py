"""Instrucciones para el informe de dossier de persona (salida al cliente)."""
from __future__ import annotations

from typing import Any

from dossier.services.person_dossier_locales import (
    person_dossier_meeting_addendum,
    person_dossier_system_template,
    person_meeting_context_config,
)

# Compatibilidad con imports existentes
PERSON_EXHAUSTIVE_SYSTEM_PROMPT = person_dossier_system_template("es")


def person_dossier_system_prompt(
    *,
    meeting_context: dict[str, Any] | None = None,
    output_language: str = "es",
) -> str:
    """Prompt de sistema para dossier de persona (Lusha + OSINT / DeepSeek)."""
    from dossier.services.output_language import apply_output_language_to_system_prompt

    base = person_dossier_system_template(output_language)
    if meeting_context and _meeting_context_active(meeting_context):
        base += person_dossier_meeting_addendum(output_language)
    return apply_output_language_to_system_prompt(base, output_language)


_PERSON_STRUCTURED_SYSTEM = (
    "Eres analista de inteligencia comercial. Preparas un dossier ejecutivo sobre una persona "
    "antes de una reunión de negocios, usando SOLO los datos entregados en el mensaje "
    "(perfiles, publicaciones, hechos verificados y contexto de reunión).\n\n"
    "- Los hechos verificados prevalecen sobre cualquier otra fuente.\n"
    "- No inventes cargos, fechas, empresas, noticias ni URLs: si un dato no está, omítelo.\n"
    "- Cada alerta de riesgo se apoya en evidencia de los datos; si no hay, la lista va vacía.\n"
    "- Los rompehielos salen del contexto de la reunión y de intereses visibles en los datos.\n"
    "- Las claves del JSON van siempre en inglés, tal como en el formato; solo se traducen "
    "los valores."
)


def person_structured_system_prompt(
    *,
    meeting_context: dict[str, Any] | None = None,
    output_language: str = "es",
) -> str:
    """Prompt de sistema de la síntesis JSON (S4.2), sin las secciones del informe Markdown."""
    from dossier.services.output_language import dossier_language_instruction

    base = _PERSON_STRUCTURED_SYSTEM
    if meeting_context and _meeting_context_active(meeting_context):
        base += "\n- Orienta el resumen y los rompehielos al objetivo de la reunión."
    return base + dossier_language_instruction(output_language)


def _meeting_context_active(ctx: dict[str, Any]) -> bool:
    for key in ("tema", "descripcion", "participantes", "empresa_reunion", "inicio"):
        val = ctx.get(key)
        if val is not None and str(val).strip():
            return True
    return False


def format_meeting_context_block(
    meeting_context: dict[str, Any] | None,
    output_language: str = "es",
) -> str:
    """Bloque de texto para el prompt de usuario con datos de la reunión."""
    if not meeting_context or not _meeting_context_active(meeting_context):
        return ""

    header, mapping = person_meeting_context_config(output_language)
    lines = [header]
    for label, key in mapping:
        val = meeting_context.get(key)
        if val is not None and str(val).strip():
            lines.append(f"- {label}: {str(val).strip()[:1200]}")
    return "\n".join(lines) + "\n\n"
