"""Pruebas de estrés - S4.2: síntesis estructurada con reintento asistido.

Ver docs/dev/testing-policy.md §4: volumen, concurrencia, degradación.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from dossier.llm.structured_synthesis import (
    StructuredSynthesisError,
    synthesize_executive_payload,
)

SISTEMA = "Eres un analista."


def _payload_json(resumen: str) -> str:
    return json.dumps(
        {
            "meeting_context": {},
            "executive_summary": resumen,
            "participants": [],
            "conversation_starters": [],
            "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
            "confidence_assessment": {"high_confidence": ["Cargo actual (PDL)."]},
        }
    )


# --------------------------------------------------------------------------
# Volumen: una respuesta inválida enorme no debe inflar el prompt de reintento.
# --------------------------------------------------------------------------


def test_volumen_respuesta_invalida_de_un_mega_no_se_reenvia_entera(llm_falso):
    basura = "x" * 1_000_000
    llm = llm_falso(basura, _payload_json("Resumen ejecutivo válido tras reparar."))

    synthesize_executive_payload("datos", system_instruction=SISTEMA)

    assert len(llm.llamadas[1]["prompt"]) < 30_000


def test_volumen_cientos_de_errores_de_validacion_se_resumen(llm_falso):
    """500 menciones sin campos obligatorios generan miles de errores Pydantic."""
    invalido = json.dumps(
        {
            "meeting_context": {},
            "executive_summary": "Resumen ejecutivo suficientemente largo.",
            "participants": [],
            "conversation_starters": [],
            "press_mentions": [{}] * 500,
        }
    )
    llm = llm_falso(invalido, "tampoco")

    with pytest.raises(StructuredSynthesisError) as info:
        synthesize_executive_payload("datos", system_instruction=SISTEMA)

    assert len(llm.llamadas[1]["prompt"]) < 30_000
    assert len(info.value.errors) <= 20


# --------------------------------------------------------------------------
# Concurrencia: síntesis en paralelo no comparten estado.
# --------------------------------------------------------------------------


def test_concurrencia_sintesis_paralelas_no_se_mezclan(llm_falso):
    n = 30
    llm_falso(*[lambda prompt: _payload_json(f"Resumen para {prompt} con largo suficiente.")] * n)

    def sintetizar(i: int) -> str:
        return synthesize_executive_payload(f"sujeto-{i}", system_instruction=SISTEMA).executive_summary

    with ThreadPoolExecutor(max_workers=10) as pool:
        resumenes = list(pool.map(sintetizar, range(n)))

    for i, resumen in enumerate(resumenes):
        assert f"sujeto-{i} " in resumen


# --------------------------------------------------------------------------
# Degradación: si el proveedor falla, no se suman reintentos de reparación.
# --------------------------------------------------------------------------


def test_degradacion_proveedor_que_expira_falla_rapido_sin_reintentos_extra(llm_falso):
    llm = llm_falso(TimeoutError("DeepSeek no respondió"), _payload_json("no debería llegar aquí"))

    with pytest.raises(TimeoutError):
        synthesize_executive_payload("datos", system_instruction=SISTEMA)

    assert len(llm.llamadas) == 1
