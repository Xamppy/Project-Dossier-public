"""S4.2: la síntesis emite JSON conforme a ``DossierExecutivePayload`` (spec S0.9).

Mitigación de R3 (JSON no conforme emitido por el LLM): el esquema va en el
prompt de sistema, se pide modo JSON al proveedor, y si la respuesta no valida
se reintenta devolviéndole al modelo los errores concretos.
"""
from __future__ import annotations

import json

import pytest

from dossier.llm.structured_synthesis import (
    StructuredSynthesisError,
    executive_payload_example,
    executive_payload_instructions,
    synthesize_executive_payload,
)
from dossier.schemas.dossier_executive_payload import DossierExecutivePayload

SISTEMA_BASE = "Eres un analista de due diligence."


# Desde la ampliación de S0.9 (2026-09-26) una respuesta de síntesis válida
# incluye la recomendación final y el nivel de confianza (CA6).
CIERRE = {
    "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
    "confidence_assessment": {"high_confidence": ["Cargo actual (PDL)."]},
}


def _payload_json(**overrides) -> str:
    base = {
        "meeting_context": {},
        "executive_summary": "Resumen ejecutivo suficientemente largo para validar.",
        "participants": [],
        "conversation_starters": [],
        **CIERRE,
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


# --- Caso normal -------------------------------------------------------------


def test_respuesta_valida_devuelve_el_payload_en_una_sola_llamada(llm_falso):
    llm = llm_falso(_payload_json())

    payload = synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE)

    assert isinstance(payload, DossierExecutivePayload)
    assert payload.executive_summary.startswith("Resumen ejecutivo")
    assert len(llm.llamadas) == 1


def test_pide_modo_json_e_inyecta_el_esquema_sin_perder_el_sistema_base(llm_falso):
    llm = llm_falso(_payload_json())

    synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE)

    llamada = llm.llamadas[0]
    assert llamada["json_mode"] is True
    assert llamada["system"].startswith(SISTEMA_BASE)
    for campo in ("executive_summary", "conversation_starters", "risk_alerts", "retrieved_at"):
        assert campo in llamada["system"], campo
    assert llamada["prompt"] == "datos"


def test_instrucciones_traen_un_ejemplo_de_instancia_valida_no_solo_el_esquema():
    """Con solo el JSON Schema, DeepSeek real devolvía el esquema copiado."""
    ejemplo = executive_payload_example()

    assert "$schema" not in ejemplo and '"properties"' not in ejemplo
    DossierExecutivePayload.model_validate_json(ejemplo)
    assert ejemplo in executive_payload_instructions()


def test_el_ejemplo_incluye_recomendacion_y_confianza():
    ejemplo = json.loads(executive_payload_example())

    assert ejemplo["final_recommendation"]["decision"]
    assert "high_confidence" in ejemplo["confidence_assessment"]


@pytest.mark.parametrize("faltante", ["final_recommendation", "confidence_assessment"])
def test_sin_recomendacion_o_confianza_el_reintento_pide_el_campo(llm_falso, faltante):
    """CA6: opcionales en el contrato (CA5), obligatorios al sintetizar."""
    sin_campo = json.loads(_payload_json())
    del sin_campo[faltante]
    llm = llm_falso(json.dumps(sin_campo), _payload_json())

    payload = synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE)

    assert len(llm.llamadas) == 2
    assert faltante in llm.llamadas[1]["prompt"]
    assert getattr(payload, faltante) is not None


# --- Bordes ------------------------------------------------------------------


def test_tolera_el_json_envuelto_en_bloque_de_codigo(llm_falso):
    llm_falso(f"```json\n{_payload_json()}\n```")

    payload = synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE)

    assert isinstance(payload, DossierExecutivePayload)


def test_reintento_asistido_devuelve_al_modelo_el_error_concreto(llm_falso):
    invalido = json.dumps({"meeting_context": {}, "participants": [], "conversation_starters": []})
    llm = llm_falso(invalido, _payload_json())

    payload = synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE)

    assert isinstance(payload, DossierExecutivePayload)
    assert len(llm.llamadas) == 2
    reintento = llm.llamadas[1]["prompt"]
    assert reintento.startswith("datos")
    assert "executive_summary" in reintento
    assert invalido in reintento


# --- Errores -----------------------------------------------------------------


def test_sin_json_valido_tras_los_reintentos_lanza_error_tipado(llm_falso):
    llm = llm_falso("esto no es JSON", "sigue sin serlo")

    with pytest.raises(StructuredSynthesisError) as info:
        synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE)

    assert len(llm.llamadas) == 2
    assert info.value.raw == "sigue sin serlo"
    assert info.value.errors


def test_sin_reintentos_hace_una_sola_llamada(llm_falso):
    llm = llm_falso("esto no es JSON")

    with pytest.raises(StructuredSynthesisError):
        synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE, max_repairs=0)

    assert len(llm.llamadas) == 1


def test_error_del_proveedor_no_se_confunde_con_json_invalido(llm_falso):
    """Los reintentos por red/429 ya los hace ``chat_completion``; aquí solo se repara JSON."""
    llm = llm_falso(RuntimeError("DeepSeek caído"), _payload_json())

    with pytest.raises(RuntimeError, match="DeepSeek caído"):
        synthesize_executive_payload("datos", system_instruction=SISTEMA_BASE)

    assert len(llm.llamadas) == 1


# --- Cliente: modo JSON ------------------------------------------------------


@pytest.mark.parametrize(("json_mode", "esperado"), [(True, {"type": "json_object"}), (False, None)])
def test_chat_completion_solo_pide_json_object_cuando_se_indica(monkeypatch, json_mode, esperado):
    import openai

    capturado: dict = {}

    class _Completions:
        def create(self, **kwargs):
            # Igual que el SDK real: los argumentos en `omit` no viajan en la petición.
            capturado.update({k: v for k, v in kwargs.items() if not isinstance(v, openai.Omit)})
            mensaje = type("M", (), {"content": "{}"})()
            eleccion = type("C", (), {"message": mensaje})()
            return type("R", (), {"choices": [eleccion]})()

    class _OpenAIFalso:
        def __init__(self, **_):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(openai, "OpenAI", _OpenAIFalso)

    from dossier.llm.client import chat_completion

    chat_completion("hola", json_mode=json_mode)

    assert capturado.get("response_format") == esperado
