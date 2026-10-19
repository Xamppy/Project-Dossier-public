"""S4.3, integración: la investigación de persona produce payload validado + Markdown derivado.

Recorre ``run_person_research`` real con PDL y el proveedor LLM como dobles.
"""
from __future__ import annotations

import json

import pytest

from dossier.schemas.person_research import PersonResearchRequest
from dossier.services import person_research_service
from dossier.services.person_dossier_dedup import (
    person_research_cache_payload_from_result,
    person_research_response_from_redis_cache,
)

PERFIL = {
    "full_name": "Ana Prueba",
    "job_title": "Gerente general",
    "job_company_name": "Empresa de Prueba SA",
    "linkedin_urls": ["https://example.test/ana"],
}


def _respuesta_valida() -> str:
    return json.dumps(
        {
            "meeting_context": {},
            "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
            "participants": [{"name": "Ana Prueba"}],
            "conversation_starters": [],
            "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
            "confidence_assessment": {"high_confidence": ["Cargo actual (PDL)."]},
        }
    )


@pytest.fixture
def entorno_pdl(monkeypatch):
    """PDL devuelve un perfil; hay clave de DeepSeek; la búsqueda web queda apagada."""
    monkeypatch.setattr(
        person_research_service, "fetch_pdl_profiles", lambda req, **_: ([dict(PERFIL)], [], [])
    )
    monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "clave-de-prueba")
    monkeypatch.setenv("DEEPSEEK_DISABLE_PERSON_WEB", "1")

    markdown_llamadas: list[dict] = []

    def _markdown(**kwargs):
        markdown_llamadas.append(kwargs)
        return "# Informe Markdown de respaldo"

    monkeypatch.setattr(person_research_service, "analyze_person_profile_bundle", _markdown)
    return markdown_llamadas


def _investigar():
    return person_research_service.run_person_research(
        PersonResearchRequest(full_name="Ana Prueba", company="Empresa de Prueba SA")
    )


def test_resultado_trae_el_payload_y_el_markdown_derivado_de_el(entorno_pdl, llm_falso):
    llm = llm_falso(_respuesta_valida())

    resultado = _investigar()

    assert resultado["executive_payload"]["executive_summary"].startswith("Ana Prueba dirige")
    assert "Ana Prueba dirige Empresa de Prueba SA desde 2019." in resultado["llm_analysis_markdown"]
    assert len(llm.llamadas) == 1
    assert entorno_pdl == [], "no debe gastarse una segunda llamada en el informe Markdown"


def test_json_invalido_tras_reintento_cae_al_informe_markdown(entorno_pdl, llm_falso):
    llm_falso("no es JSON", "tampoco")

    resultado = _investigar()

    assert resultado["executive_payload"] is None
    assert resultado["llm_analysis_markdown"] == "# Informe Markdown de respaldo"
    assert len(entorno_pdl) == 1
    assert any("JSON" in w for w in resultado["warnings"])


def test_proveedor_caido_no_dispara_el_respaldo_markdown(entorno_pdl, llm_falso):
    """Si DeepSeek no responde, la llamada Markdown fallaría igual: solo gastaría tiempo."""
    llm_falso(RuntimeError("DeepSeek caído"))

    resultado = _investigar()

    assert entorno_pdl == []
    assert resultado["executive_payload"] is None
    assert resultado["llm_analysis_markdown"] is None
    assert any("DeepSeek caído" in w for w in resultado["warnings"])


def test_la_cache_conserva_el_payload(entorno_pdl, llm_falso):
    llm_falso(_respuesta_valida())
    resultado = _investigar()

    guardado = {
        "markdown": resultado["llm_analysis_markdown"],
        **person_research_cache_payload_from_result(resultado),
    }
    recuperado = person_research_response_from_redis_cache(
        PersonResearchRequest(full_name="Ana Prueba"),
        organization_context_block=None,
        cached_payload=json.loads(json.dumps(guardado)),
    )

    assert recuperado["executive_payload"] == resultado["executive_payload"]


def test_pipeline_guarda_el_payload_sin_tocar_body_ni_billing(pg_vacia, alembic_cfg, monkeypatch):
    """Contra Postgres real: el trigger de cobro sigue leyendo ``billing`` en la raíz."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from alembic import command
    from dossier.db.models import Organization, User
    from dossier.services import person_research_pipeline

    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name, slug) VALUES ('Org', 'org-s43') RETURNING id")
        ).scalar_one()
        user_id = conn.execute(
            text("INSERT INTO users (email) VALUES ('s43@example.test') RETURNING id")
        ).scalar_one()

    payload = {
        "schema_version": "2.0.0",
        "meeting_context": {},
        "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
        "participants": [],
        "conversation_starters": [],
    }
    monkeypatch.setattr(
        person_research_pipeline,
        "run_person_research",
        lambda *a, **k: {
            "filters_applied": {"research_source": "pdl"},
            "profiles": [dict(PERFIL)],
            "profile_urls": [],
            "warnings": [],
            "llm_analysis_markdown": "## Resumen ejecutivo\n\nAna Prueba dirige Empresa de Prueba SA.",
            "executive_payload": payload,
        },
    )

    with Session(pg_vacia) as db:
        org = db.get(Organization, org_id)
        user = db.get(User, user_id)
        respuesta = person_research_pipeline.run_person_research_and_persist(
            db, user=user, org=org, body=PersonResearchRequest(full_name="Ana Prueba")
        )

    with pg_vacia.connect() as conn:
        guardado = conn.execute(
            text("SELECT dossier_data FROM dossiers WHERE id = :d"),
            {"d": respuesta["saved_dossier"]["id"]},
        ).scalar_one()

    assert guardado["executive_payload"] == payload
    assert guardado["format"] == "markdown"
    assert guardado["body"].startswith("## Resumen ejecutivo")
    assert guardado["billing"] in ("charged", "none")
