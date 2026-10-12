"""S4.7, integración: ``_synthesize_person_report`` normaliza la procedencia antes de renderizar.

Recorre ``run_person_research`` real con PDL y el proveedor LLM como dobles
(mismo patrón que ``test_person_research_structured.py``, S4.3). El LLM
devuelve citas inventadas — nombre genérico, fuente no consultada, fecha que
nunca ocurrió —; la prueba comprueba que ni ``executive_payload`` ni el
Markdown derivado se quedan con esas citas: usan la hora real de consulta a
PDL, y la alerta que citaba una fuente no consultada se descarta.
"""
from __future__ import annotations

import json

import pytest

from dossier.schemas.person_research import PersonResearchRequest
from dossier.services import person_research_service

PERFIL = {
    "full_name": "Ana Prueba",
    "job_title": "Gerente general",
    "job_company_name": "Empresa de Prueba SA",
    "linkedin_urls": ["https://example.test/ana"],
}

RETRIEVED_INVENTADO = "2019-01-01T00:00:00Z"


def _cita_inventada(**overrides) -> dict:
    base = {
        "source_type": "gdelt_news",
        "source_name": "Datos proporcionados",
        "url": None,
        "retrieved_at": RETRIEVED_INVENTADO,
    }
    base.update(overrides)
    return base


def _respuesta_con_citas_inventadas() -> str:
    return json.dumps(
        {
            "meeting_context": {},
            "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
            "participants": [{"name": "Ana Prueba"}],
            "career_trajectory": [
                {
                    "role_title": "Gerente general",
                    "company_name": "Empresa de Prueba SA",
                    "is_current": True,
                    "source": None,
                }
            ],
            "risk_alerts": [
                {
                    "title": "Mención negativa en prensa",
                    "severity": "medium",
                    "description": "El LLM citó prensa aunque no se consultó ningún proveedor de noticias.",
                    "sources": [_cita_inventada()],
                }
            ],
            "data_sources_used": [_cita_inventada(source_type="pdl", source_name="Fuente inventada")],
            "conversation_starters": [],
            "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
            "confidence_assessment": {"high_confidence": ["Cargo actual (PDL)."]},
        }
    )


@pytest.fixture
def entorno_pdl(monkeypatch):
    """PDL devuelve un perfil; hay clave de DeepSeek; la búsqueda web queda apagada."""
    monkeypatch.setattr(
        person_research_service, "fetch_pdl_profiles", lambda req: ([dict(PERFIL)], [], [])
    )
    monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "clave-de-prueba")
    monkeypatch.setenv("DEEPSEEK_DISABLE_PERSON_WEB", "1")


def _investigar():
    return person_research_service.run_person_research(
        PersonResearchRequest(full_name="Ana Prueba", company="Empresa de Prueba SA")
    )


def test_las_citas_inventadas_por_el_llm_no_llegan_al_payload_ni_al_markdown(
    entorno_pdl, llm_falso
):
    llm_falso(_respuesta_con_citas_inventadas())

    resultado = _investigar()
    payload = resultado["executive_payload"]

    # data_sources_used queda fijo a la fuente real (PDL), no a la que inventó el LLM.
    assert len(payload["data_sources_used"]) == 1
    fuente = payload["data_sources_used"][0]
    assert fuente["source_type"] == "pdl"
    assert fuente["source_name"] == "People Data Labs"
    retrieved_at = fuente["retrieved_at"]
    assert not retrieved_at.startswith("2019")

    # La alerta que citaba prensa (no consultada) se descarta.
    assert payload["risk_alerts"] == []

    # La trayectoria, sin cita propia, se completa con la cita PDL real.
    assert payload["career_trajectory"][0]["source"]["source_name"] == "People Data Labs"

    # El Markdown derivado usa la misma fuente real en su sección de fuentes
    # (normalize_person_report_text sustituye "People Data Labs" por un
    # nombre genérico de cara al usuario final; ver dossier.llm.common).
    assert "registros profesionales" in resultado["llm_analysis_markdown"]
    assert "Datos proporcionados" not in resultado["llm_analysis_markdown"]
    assert "Mención negativa en prensa" not in resultado["llm_analysis_markdown"]


def test_sin_citas_del_llm_career_trajectory_igual_recibe_la_cita_pdl(entorno_pdl, llm_falso):
    llm_falso(
        json.dumps(
            {
                "meeting_context": {},
                "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
                "participants": [{"name": "Ana Prueba"}],
                "career_trajectory": [
                    {
                        "role_title": "Gerente general",
                        "company_name": "Empresa de Prueba SA",
                        "is_current": True,
                    }
                ],
                "conversation_starters": [],
                "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
                "confidence_assessment": {"high_confidence": ["Cargo actual (PDL)."]},
            }
        )
    )

    resultado = _investigar()

    fuente = resultado["executive_payload"]["career_trajectory"][0]["source"]
    assert fuente["source_name"] == "People Data Labs"
