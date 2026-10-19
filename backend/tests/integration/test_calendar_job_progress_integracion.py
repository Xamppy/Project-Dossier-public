"""S5.10 · BE1, BE3, BE7 y BE12 contra Postgres: un job de Calendario de punta a punta.

Worker, grafo corporativo, investigación de dos asistentes y guardado reales;
Companies House, SEC, Europa, prensa, PDL y el LLM son dobles. El agente UK
falla a propósito: el resto completa y el dossier corporativo se guarda.
Requiere ``TEST_DATABASE_URL``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import Dossier, DossierGenerationJob
from dossier.eu_registry.agent import ResultadoAgenteEuropeo
from dossier.news.agent import ResultadoRecoleccionPrensa
from dossier.services import calendar_event_dossiers as cal
from dossier.services import dossier_generation_job_service as servicio
from dossier.services import dossier_progress_events as bus
from dossier.services import pdl_research, person_research_service

REUNION = {
    "tema": "Kick-off con Acme Corp",
    "descripcion": "Empresa: Acme Corp\nContacto 1: Ana Prueba\nCargo 1: Directora\nContacto 2: Beto Prueba",
    "participantes": "",
    "inicio": "2026-10-20T10:00:00Z",
}


def _payload_valido() -> str:
    return json.dumps(
        {
            "meeting_context": {},
            "executive_summary": "Ana Prueba dirige Acme Corp.",
            "participants": [{"name": "Ana Prueba"}],
            "conversation_starters": [],
            "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
            "confidence_assessment": {"high_confidence": ["Cargo actual."]},
        }
    )


class PdlFalso:
    """Encuentra a Ana; Beto no está en PDL."""

    def person_enrich(self, params):
        if "Ana" in json.dumps(params):
            return {"data": {"id": "pdl-ana", "full_name": "Ana Prueba", "job_title": "Directora"}, "likelihood": 8}
        return None

    def person_search(self, *, sql=None, query=None, size=5):
        return {"data": [], "total": 0}


@pytest.fixture
def entorno(pg_vacia, alembic_cfg, monkeypatch, llm_falso):
    import dossier.llm.text_generate as llm
    import dossier.services.corporate_registry_context as ctx

    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id = conn.execute(
            text(
                "INSERT INTO organizations (name, slug, plan, credits_balance) "
                "VALUES ('Org', 'org-cal', 'pro', 100) RETURNING id"
            )
        ).scalar_one()
        user_id = conn.execute(text("INSERT INTO users (email) VALUES ('cal@example.com') RETURNING id")).scalar_one()

    def uk_falla(_p):
        raise RuntimeError("Companies House caído")

    monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", uk_falla)
    monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", lambda p: "## USA\n\nregistro\n")
    monkeypatch.setattr("dossier.eu_registry.agent.run_eu_registry_agent", lambda e, **_: ResultadoAgenteEuropeo())
    monkeypatch.setattr(
        "dossier.news.agent.collect_press_mentions", lambda e, **_: ResultadoRecoleccionPrensa(mentions=[])
    )
    monkeypatch.setattr(
        llm, "generate_text_with_llm", lambda user, system_instruction=None: "# Dossier corporativo\n\nResumen."
    )
    monkeypatch.setattr(cal, "resolve_corporate_brief", lambda q: (q, "dual"))
    monkeypatch.setattr(pdl_research, "PdlClient", PdlFalso)
    monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "clave-de-prueba")
    monkeypatch.setenv("DEEPSEEK_DISABLE_PERSON_WEB", "1")
    monkeypatch.delenv("PERSON_RESEARCH_PROVIDER", raising=False)
    llm_falso(_payload_valido())

    with Session(pg_vacia) as db:
        job = DossierGenerationJob(
            organization_id=org_id,
            requested_by_user_id=user_id,
            status="queued",
            job_type="calendar_manual",
            calendar_provider="google",
            external_event_id=None,
            reunion_snapshot=dict(REUNION),
            depth_level="standard",
            credits_estimated=5,
        )
        db.add(job)
        db.commit()
        job_id = job.id

    with Session(pg_vacia) as db:
        servicio.process_dossier_generation_job(db, job_id)
    with Session(pg_vacia) as db:
        datos = servicio.serialize_job(db.get(DossierGenerationJob, job_id))
        dossiers = {
            d.subject_name: d
            for d in db.query(Dossier).filter(Dossier.organization_id == org_id).all()
        }
    yield SimpleNamespace(job_id=job_id, datos=datos, dossiers=dossiers, eventos=bus.events_since(job_id, 0))
    bus.forget(job_id)


def _scope(datos, scope_id):
    return next(s for s in datos["progress"]["scopes"] if s["scope_id"] == scope_id)


def test_job_completo_con_un_agente_caido_y_scopes_por_asistente(entorno):
    datos = entorno.datos

    assert datos["status"] == "completed"
    assert [s["scope_id"] for s in datos["progress"]["scopes"]] == ["corporate:0", "person:0", "person:1"]
    agentes = {a["agent_name"]: (a["status"], a["reason_code"]) for a in _scope(datos, "corporate:0")["agents"]}
    assert agentes == {
        "agent_corporate_uk": ("failed", "provider_error"),
        "agent_corporate_usa": ("completed", None),
        "agent_corporate_eu": ("completed", "no_matches"),
        "agent_news": ("completed", "no_matches"),
        "synthesize_llm": ("completed", None),
    }
    ana = {e["stage_id"]: e["status"] for e in _scope(datos, "person:0")["stages"]}
    beto = {e["stage_id"]: (e["status"], e["reason_code"]) for e in _scope(datos, "person:1")["stages"]}
    assert ana["person.profile_synthesis"] == "completed" and ana["person.persist"] == "completed"
    assert beto["person.pdl_enrich"] == ("completed", "no_matches")
    assert beto["person.persist"] == ("failed", "no_valid_report")


def test_cada_dossier_queda_enlazado_a_su_scope_y_se_conserva_s49(entorno):
    corporativo = entorno.dossiers["Acme Corp"]

    assert corporativo.agents_failed == ["agent_corporate_uk"]
    assert corporativo.dossier_data["_progress"]["scope"]["scope_id"] == "corporate:0"
    assert entorno.dossiers["Ana Prueba"].dossier_data["_progress"]["scope"]["scope_id"] == "person:0"
    assert entorno.dossiers["Beto Prueba"].status == "failed"
    assert _scope(entorno.datos, "corporate:0")["dossier"] == {"id": str(corporativo.id), "status": "complete"}


def test_agent_progress_tiene_el_formato_nuevo_y_llega_antes_del_terminal(entorno):
    nombres = [e for _, e, _ in entorno.eventos]
    agentes = [d for _, e, d in entorno.eventos if e == "agent_progress"]

    assert nombres[-1] == "job_completed"
    assert agentes, "el grafo informó a sus agentes"
    for d in agentes:
        assert d["schema_version"] == 1 and d["scope_id"] == "corporate:0"
        assert d["job_id"] == str(entorno.job_id)
        assert "dossier_id" not in d, "ya no se emite el formato de S4.9"
    fallo = next(d for d in agentes if d["agent_name"] == "agent_corporate_uk" and d["status"] == "failed")
    assert nombres.index("agent_progress") < nombres.index("job_completed")
    assert fallo["reason_code"] == "provider_error"


def test_resultado_y_progreso_viajan_separados_y_el_terminal_lleva_el_snapshot(entorno):
    datos = entorno.datos

    assert "_progress" not in datos["result"]
    assert datos["result"]["saved_dossiers"]["corporate"]["status"] == "complete"
    assert entorno.eventos[-1][2]["progress"] == datos["progress"]
    assert [p["section"] for p in _scope(datos, "corporate:0")["partial_results"]] == ["synthesis"]
