"""Síntesis del dossier como JSON validado contra ``DossierExecutivePayload`` (S4.2).

Mitiga R3 de la spec S0.9 (JSON no conforme emitido por el LLM): el esquema va
en el prompt de sistema, se pide modo JSON al proveedor y, si la respuesta no
valida, se reintenta devolviéndole al modelo los errores concretos.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from pydantic import ValidationError

from dossier.llm.client import chat_completion
from dossier.schemas.dossier_executive_payload import (
    CareerPosition,
    ConversationStarter,
    DossierExecutivePayload,
    RiskAlert,
    RiskSeverity,
    SourceCitation,
    SourceType,
)

# Topes para que una respuesta inválida enorme no infle el prompt del reintento.
MAX_ERRORES_REINTENTO = 20
MAX_ECO_RESPUESTA = 8_000

_BLOQUE_DE_CODIGO = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class StructuredSynthesisError(RuntimeError):
    """El LLM no produjo un payload válido tras los reintentos asistidos."""

    def __init__(self, errors: list[str], raw: str) -> None:
        super().__init__(
            "La síntesis no produjo JSON conforme al esquema: " + "; ".join(errors[:3])
        )
        self.errors = errors
        self.raw = raw


def executive_payload_example() -> str:
    """Instancia de ejemplo construida con los propios modelos, así siempre valida."""
    cita = SourceCitation(
        source_type=SourceType.pdl,
        source_name="<proveedor que aparece en los datos>",
        url="<url que aparece en los datos, o null>",
        retrieved_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    ejemplo = DossierExecutivePayload(
        meeting_context={"title": "<título de la reunión, si se entregó>"},
        executive_summary="<3-5 frases: quién es, rol actual y por qué importa para la reunión>",
        participants=[{"name": "<nombre>", "role": "<cargo>", "company": "<empresa>"}],
        career_trajectory=[
            CareerPosition(
                role_title="<cargo>",
                company_name="<empresa>",
                start_date="<AAAA o AAAA-MM>",
                is_current=True,
                source=cita,
            )
        ],
        press_mentions=[],
        risk_alerts=[
            RiskAlert(
                title="<riesgo concreto>",
                severity=RiskSeverity.medium,
                description="<evidencia que lo sustenta>",
                sources=[cita],
            )
        ],
        conversation_starters=[
            ConversationStarter(
                topic="<tema>",
                rationale="<por qué es relevante, según los datos>",
                suggested_opener="<frase para abrir la conversación>",
            )
        ],
        data_sources_used=[cita],
    )
    return ejemplo.model_dump_json()


def executive_payload_instructions() -> str:
    esquema = json.dumps(DossierExecutivePayload.model_json_schema(), ensure_ascii=False)
    return (
        "FORMATO DE SALIDA: responde únicamente con un objeto JSON (sin Markdown ni texto "
        "antes o después) con exactamente la forma de este ejemplo, reemplazando cada "
        "<marcador> por datos reales:\n"
        f"{executive_payload_example()}\n\n"
        "Referencia de tipos y campos obligatorios (JSON Schema). No lo copies: tu respuesta "
        f"es una instancia como el ejemplo, no un esquema:\n{esquema}\n\n"
        "Reglas:\n"
        '- "schema_version" es "2.0.0".\n'
        "- Cita solo fuentes que aparezcan en los datos entregados; nunca inventes URLs.\n"
        '- "retrieved_at" es la fecha y hora de consulta indicada en los datos, en ISO 8601 UTC.\n'
        "- Si no hay datos para una sección, deja su lista vacía en vez de suponer.\n"
        '- Como máximo 3 elementos en "conversation_starters".'
    )


def _sin_bloque_de_codigo(texto: str) -> str:
    m = _BLOQUE_DE_CODIGO.match(texto)
    return m.group(1) if m else texto


def _resumir_errores(error: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in e['loc']) or '(raíz)'}: {e['msg']}"
        for e in error.errors(include_url=False)[:MAX_ERRORES_REINTENTO]
    ]


def _prompt_de_reparacion(user_prompt: str, raw: str, errores: list[str]) -> str:
    eco = raw if len(raw) <= MAX_ECO_RESPUESTA else raw[:MAX_ECO_RESPUESTA] + "\n… [truncada] …"
    lista = "\n".join(f"- {e}" for e in errores)
    return (
        f"{user_prompt}\n\n"
        "Tu respuesta anterior no validó contra el JSON Schema. Errores:\n"
        f"{lista}\n\n"
        f"Respuesta anterior:\n{eco}\n\n"
        "Devuelve el objeto JSON completo y corregido."
    )


def synthesize_executive_payload(
    user_prompt: str,
    *,
    system_instruction: str,
    max_repairs: int = 1,
) -> DossierExecutivePayload:
    sistema = f"{system_instruction}\n\n{executive_payload_instructions()}"
    prompt = user_prompt
    for _ in range(max_repairs + 1):
        raw = chat_completion(prompt, system_instruction=sistema, json_mode=True)
        try:
            return DossierExecutivePayload.model_validate_json(_sin_bloque_de_codigo(raw))
        except ValidationError as e:
            errores = _resumir_errores(e)
        prompt = _prompt_de_reparacion(user_prompt, raw, errores)
    raise StructuredSynthesisError(errores, raw)
