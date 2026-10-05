"""Ampliación de S0.9 (2026-09-26): recomendación final y nivel de confianza en el contrato."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from dossier.schemas.dossier_executive_payload import (
    DossierExecutivePayload,
    FinalRecommendation,
    OverallRiskLevel,
    RecommendationDecision,
)

BASE = {
    "meeting_context": {},
    "executive_summary": "Resumen ejecutivo suficientemente largo para validar.",
    "participants": [],
    "conversation_starters": [],
}

CIERRE = {
    "final_recommendation": {
        "key_findings": ["Cargo actual confirmado por PDL."],
        "overall_risk": "low",
        "decision": "proceed",
        "next_steps": ["Confirmar el alcance de la reunión."],
    },
    "confidence_assessment": {
        "high_confidence": ["Cargo y empresa actuales (PDL)."],
        "inferences": ["Interés en proveedores locales."],
    },
}


# Caso normal
def test_payload_con_recomendacion_y_confianza_valida():
    payload = DossierExecutivePayload(**BASE, **CIERRE)

    assert payload.final_recommendation.decision is RecommendationDecision.proceed
    assert payload.final_recommendation.overall_risk is OverallRiskLevel.low
    assert payload.confidence_assessment.medium_confidence == []


# CA5: los payloads guardados antes de la ampliación siguen siendo válidos.
def test_payload_sin_recomendacion_ni_confianza_sigue_siendo_valido():
    payload = DossierExecutivePayload(**BASE)

    assert payload.final_recommendation is None
    assert payload.confidence_assessment is None


# Bordes y errores
def test_riesgo_global_admite_critico():
    assert OverallRiskLevel("critical") is OverallRiskLevel.critical


@pytest.mark.parametrize("decision", ["maybe", "Proceder", ""])
def test_decision_fuera_del_catalogo_se_rechaza(decision):
    with pytest.raises(ValidationError):
        FinalRecommendation(overall_risk="low", decision=decision)


def test_hallazgos_clave_maximo_cinco():
    with pytest.raises(ValidationError):
        FinalRecommendation(overall_risk="low", decision="proceed", key_findings=["x"] * 6)
