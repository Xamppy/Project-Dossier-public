"""S5.10 · BE4, BE6, BE11 y BE13 contra Postgres: un job de Personas de punta a punta.

Worker real, ``run_person_research_and_persist`` real y progreso guardado en
``result_payload["_progress"]``; PDL y el LLM son dobles. Requiere
``TEST_DATABASE_URL`` (ver ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import Dossier, DossierGenerationJob
from dossier.services import dossier_generation_job_service as servicio
from dossier.services import dossier_progress_events as bus
from dossier.services import pdl_research, person_research_pipeline, person_research_service

PERSONA_PDL = {
    "id": "pdl-ana-1",
    "full_name": "Ana Prueba",
    "job_title": "Directora",
    "job_company_name": "Empresa de Prueba SA",
    "emails": [{"address": "ana@empresa.example"}],
    "mobile_phone": "+56 9 1111 2222",
}
CACHE_ANTIGUA = {
    "markdown": "## Informe en caché\n\nAna Prueba.",
    "profiles_count": 2,
    "profile_urls": [],
    "warnings": [],
}


def _payload_valido() -> str:
    return json.dumps(
        {
            "meeting_context": {},
            "executive_summary": "Ana Prueba dirige Empresa de Prueba SA.",
            "participants": [{"name": "Ana Prueba"}],
            "conversation_starters": [],
            "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
            "confidence_assessment": {"high_confidence": ["Cargo actual."]},
        }
    )


class PdlFalso:
    def __init__(self):
        self.llamadas = 0

    def person_enrich(self, params):
        self.llamadas += 1
        return {"data": dict(PERSONA_PDL), "likelihood": 8} if "email" in params else None

    def person_search(self, *, sql=None, query=None, size=5):
        self.llamadas += 1
        return {"data": [], "total": 0}


@pytest.fixture
def base(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id = conn.execute(
            text(
                "INSERT INTO organizations (name, slug, plan, credits_balance) "
                "VALUES ('Org', 'org-s510', 'pro', 100) RETURNING id"
            )
        ).scalar_one()
        user_id = conn.execute(
            text("INSERT INTO users (email) VALUES ('s510@example.com') RETURNING id")
        ).scalar_one()
    jobs: list[uuid.UUID] = []
    yield SimpleNamespace(engine=pg_vacia, org_id=org_id, user_id=user_id, jobs=jobs)
    for job_id in jobs:
        bus.forget(job_id)


@pytest.fixture
def proveedores(monkeypatch):
    """PDL encuentra a Ana por correo; hay clave de DeepSeek; nada sale a la red."""
    pdl = PdlFalso()
    monkeypatch.setattr(pdl_research, "PdlClient", lambda: pdl)
    monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "clave-de-prueba")
    monkeypatch.delenv("DEEPSEEK_DISABLE_PERSON_WEB", raising=False)
    monkeypatch.delenv("DEEPSEEK_PERSON_WEB_ALWAYS", raising=False)
    monkeypatch.setattr(
        person_research_service,
        "analyze_person_with_google_search",
        lambda **_: "## Informe con IA\n\nAna Prueba, según el encargo.",
    )
    monkeypatch.setattr(
        person_research_service, "analyze_person_profile_bundle", lambda **_: "## Respaldo\n\nAna Prueba."
    )
    return pdl


def _encolar(base, fuente="pdl", **extra) -> uuid.UUID:
    pedido = {
        "full_name": "Ana Prueba",
        "company": "Empresa de Prueba SA",
        "email": "ana@empresa.example",
        "research_source": fuente,
        "max_profiles": 1,
        **extra,
    }
    with Session(base.engine) as db:
        job = DossierGenerationJob(
            organization_id=base.org_id,
            requested_by_user_id=base.user_id,
            status="queued",
            job_type="person_manual",
            external_event_id=f"person:{uuid.uuid4().hex}",
            reunion_snapshot={"person_request": pedido},
            depth_level="basic",
            meeting_label="Ana Prueba",
            credits_estimated=1,
        )
        db.add(job)
        db.commit()
        base.jobs.append(job.id)
        return job.id


def _procesar(base, job_id) -> dict:
    with Session(base.engine) as db:
        servicio.process_dossier_generation_job(db, job_id)
    with Session(base.engine) as db:
        return servicio.serialize_job(db.get(DossierGenerationJob, job_id))


def _etapas(datos, scope_id="person:0"):
    scope = next(s for s in datos["progress"]["scopes"] if s["scope_id"] == scope_id)
    return {e["stage_id"]: (e["status"], e["reason_code"]) for e in scope["stages"]}, scope


def _eventos(job_id):
    return [(e, d) for _, e, d in bus.events_since(job_id, 0)]


def test_job_pdl_guarda_el_progreso_cerrado_y_lo_expone_aparte_del_resultado(base, proveedores, llm_falso):
    llm_falso(_payload_valido())
    job_id = _encolar(base)

    datos = _procesar(base, job_id)

    assert datos["status"] == "completed"
    assert "_progress" not in datos["result"]
    etapas, scope = _etapas(datos)
    assert etapas == {
        "person.cache_lookup": ("skipped", "cache_unavailable"),
        "person.pdl_enrich": ("completed", None),
        "person.pdl_search": ("skipped", "sufficient_profiles"),
        "person.profile_normalization": ("completed", None),
        "person.context_analysis": ("skipped", "mode_not_applicable"),
        "person.profile_synthesis": ("completed", None),
        "person.markdown_fallback": ("skipped", "not_required"),
        "person.report_finalize": ("completed", None),
        "person.persist": ("completed", None),
    }
    assert (scope["research_source"], scope["origin"], scope["profiles_count"]) == ("pdl", "generated", 1)
    dossier_id = datos["result"]["saved_dossier"]["id"]
    assert scope["dossier"] == {"id": dossier_id, "status": "complete"}

    with Session(base.engine) as db:
        copia = db.get(Dossier, uuid.UUID(dossier_id)).dossier_data["_progress"]
    assert (copia["job_id"], copia["scope"]["scope_id"]) == (str(job_id), "person:0")

    eventos = _eventos(job_id)
    nombres = [e for e, _ in eventos]
    assert nombres[-1] == "job_completed"
    assert eventos[-1][1]["progress"] == datos["progress"], "el terminal lleva el snapshot cerrado"
    assert {"stage_progress", "partial_result"} <= set(nombres)
    revisiones = [d["revision"] for e, d in eventos if e in ("stage_progress", "partial_result")]
    assert revisiones == sorted(revisiones), "el bus recibe los cambios en el orden de su revisión"


def test_perfiles_validos_sobreviven_a_un_informe_fallido(base, proveedores, monkeypatch):
    monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "")
    job_id = _encolar(base)

    datos = _procesar(base, job_id)

    assert datos["status"] == "failed"
    etapas, scope = _etapas(datos)
    assert etapas["person.persist"] == ("failed", "no_valid_report")
    perfiles = next(p for p in scope["partial_results"] if p["section"] == "person_profiles")
    assert perfiles["data"]["profiles"][0]["full_name"] == "Ana Prueba"
    with Session(base.engine) as db:
        fallido = db.get(Dossier, uuid.UUID(scope["dossier"]["id"]))
    assert fallido.status == "failed"
    secciones = [p["section"] for p in fallido.dossier_data["_progress"]["scope"]["partial_results"]]
    assert "person_profiles" in secciones, "«Ver información disponible» también desde el dossier"


def test_web_publica_de_punta_a_punta_sin_consultar_pdl(base, proveedores, monkeypatch):
    def no_construir():
        raise AssertionError("Web pública no consulta PDL")

    monkeypatch.setattr(pdl_research, "PdlClient", no_construir)
    job_id = _encolar(base, fuente="gemini_web")

    datos = _procesar(base, job_id)

    etapas, scope = _etapas(datos)
    assert etapas == {
        "person.cache_lookup": ("skipped", "cache_unavailable"),
        "person.context_analysis": ("completed", None),
        "person.report_finalize": ("completed", None),
        "person.persist": ("completed", None),
    }
    assert scope["live_web_search"] is False
    contexto = next(p for p in scope["partial_results"] if p["section"] == "person_context_report")
    assert contexto["provenance"]["basis"] == "model_only"


@pytest.fixture
def cache(monkeypatch):
    estado = {"respuestas": [], "consultas": 0, "guardados": []}

    def obtener(fp):
        estado["consultas"] += 1
        return estado["respuestas"].pop(0) if estado["respuestas"] else None

    monkeypatch.setattr(person_research_pipeline, "redis_person_cache_available", lambda: True)
    monkeypatch.setattr(person_research_pipeline, "get_person_cached_payload", obtener)
    monkeypatch.setattr(
        person_research_pipeline, "set_person_cached_payload", lambda fp, p: estado["guardados"].append(p)
    )
    monkeypatch.setattr(person_research_pipeline, "run_with_person_cache_lock", lambda fp, fn: fn())
    return estado


def test_acierto_de_cache_antigua_no_cobra_ni_inventa_etapas(base, proveedores, cache):
    cache["respuestas"] = [dict(CACHE_ANTIGUA)]
    job_id = _encolar(base)

    datos = _procesar(base, job_id)

    assert datos["status"] == "completed" and datos["credits_consumed"] == 0
    etapas, scope = _etapas(datos)
    assert etapas["person.cache_lookup"] == ("completed", "cache_hit")
    assert etapas["person.pdl_enrich"] == ("skipped", "cache_hit")
    assert etapas["person.persist"] == ("completed", None)
    assert (scope["origin"], scope["profiles_count"]) == ("redis_cache", 2)
    assert proveedores.llamadas == 0
    assert "person_profiles" not in {p["section"] for p in scope["partial_results"]}


def test_acierto_bajo_el_candado(base, proveedores, cache):
    cache["respuestas"] = [None, dict(CACHE_ANTIGUA)]
    job_id = _encolar(base)

    datos = _procesar(base, job_id)

    etapas, _ = _etapas(datos)
    assert etapas["person.cache_lookup"] == ("completed", "cache_hit")
    assert proveedores.llamadas == 0


def test_force_refresh_no_consulta_la_cache_y_no_guarda_ids_en_ella(base, proveedores, cache, llm_falso):
    llm_falso(_payload_valido())
    job_id = _encolar(base, force_refresh=True)

    datos = _procesar(base, job_id)

    etapas, _ = _etapas(datos)
    assert etapas["person.cache_lookup"] == ("skipped", "force_refresh")
    assert cache["consultas"] == 0
    assert cache["guardados"], "el informe nuevo se cachea como siempre"
    texto = json.dumps(cache["guardados"])
    assert str(job_id) not in texto and "_progress" not in texto and "person:0" not in texto


def test_refinamiento_actualiza_el_mismo_dossier(base, proveedores, llm_falso):
    with base.engine.begin() as conn:
        existente = conn.execute(
            text(
                "INSERT INTO dossiers (organization_id, requested_by_user_id, dossier_data, status) "
                "VALUES (:o, :u, CAST(:d AS JSONB), 'complete') RETURNING id"
            ),
            {"o": base.org_id, "u": base.user_id, "d": '{"billing": "none"}'},
        ).scalar_one()
    llm_falso(_payload_valido())
    job_id = _encolar(base, replace_dossier_id=str(existente))

    datos = _procesar(base, job_id)

    _, scope = _etapas(datos)
    assert scope["dossier"] == {"id": str(existente), "status": "complete"}
    assert datos["credits_consumed"] == 0


def test_si_guardar_falla_persist_queda_como_persistence_error(base, proveedores, llm_falso, monkeypatch):
    llm_falso(_payload_valido())

    def falla(*_a, **_k):
        raise RuntimeError("violación de restricción")

    monkeypatch.setattr(person_research_pipeline, "escribir_entidades_ejecutivas", falla)
    job_id = _encolar(base)

    datos = _procesar(base, job_id)

    assert datos["status"] == "failed"
    etapas, _ = _etapas(datos)
    assert etapas["person.persist"] == ("failed", "persistence_error")


def _cancelar(base, job_id):
    with Session(base.engine) as db:
        servicio.cancel_dossier_generation_job(db, job=db.get(DossierGenerationJob, job_id))


def test_cancelar_durante_la_investigacion_cierra_el_progreso_y_no_lo_revive(base, monkeypatch):
    job_id = _encolar(base)

    def investigar(body, **kwargs):
        progress = kwargs["progress"]
        progress.stage("person.pdl_enrich", "running")
        _cancelar(base, job_id)
        progress.stage("person.pdl_enrich", "completed")  # callback tardío
        return {
            "filters_applied": {"research_source": "pdl", "profiles_count": 0},
            "profiles": [],
            "profile_urls": [],
            "warnings": [],
            "llm_analysis_markdown": "## Informe\n\nAna Prueba.",
            "executive_payload": None,
        }

    monkeypatch.setattr(person_research_pipeline, "run_person_research", investigar)

    datos = _procesar(base, job_id)

    assert datos["status"] == "cancelled"
    etapas, _ = _etapas(datos)
    assert etapas["person.pdl_enrich"] == ("cancelled", None)
    assert etapas["person.persist"] == ("skipped", "not_reached")
    nombres = [e for e, _ in _eventos(job_id)]
    corte = nombres.index("job_failed")
    assert not {"stage_progress", "partial_result"} & set(nombres[corte:]), "nada se publica tras cancelar"
    with Session(base.engine) as db:
        guardados = db.query(Dossier).filter(Dossier.organization_id == base.org_id).count()
    assert guardados == 1, "el guardado ya iniciado no se deshace: no hay cancelación dura"


def test_cancelar_despues_de_guardar_conserva_el_guardado_en_el_progreso(base, proveedores, llm_falso, monkeypatch):
    llm_falso(_payload_valido())
    original = servicio.run_person_research_and_persist
    job_id = _encolar(base)

    def guardar_y_cancelar(db, **kwargs):
        resultado = original(db, **kwargs)
        _cancelar(base, job_id)
        return resultado

    monkeypatch.setattr(servicio, "run_person_research_and_persist", guardar_y_cancelar)

    datos = _procesar(base, job_id)

    assert datos["status"] == "cancelled"
    etapas, _ = _etapas(datos)
    assert etapas["person.persist"] == ("completed", None)


def test_cliente_que_conecta_tarde_recibe_el_progreso_aunque_el_bus_se_haya_perdido(base, proveedores, llm_falso):
    from dossier.api.dossier_stream_routes import lector_de_job
    from dossier.services.dossier_progress_stream import stream_job_events

    llm_falso(_payload_valido())
    job_id = _encolar(base)
    _procesar(base, job_id)
    bus.forget(job_id)  # reinicio del proceso: el bus en memoria se perdió

    with Session(base.engine) as db:
        leer = lector_de_job(db, job_id, user_id=base.user_id, org_id=base.org_id)
        frames = list(stream_job_events(job_id, leer, max_seconds=1))

    assert len(frames) == 1 and frames[0].startswith("id: ")
    datos = json.loads(frames[0].split("data: ", 1)[1])
    assert datos["progress"]["scopes"][0]["scope_id"] == "person:0"
    assert all(e["status"] != "running" for e in datos["progress"]["scopes"][0]["stages"])
