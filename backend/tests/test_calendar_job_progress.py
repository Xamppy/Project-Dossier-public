"""S5.10 · BE1/BE12/BE13 en Calendario: scopes por asistente, caché y guardado.

Sin base de datos: el grafo y la investigación de personas son dobles que
reciben el scope que les toca; aquí se prueba el cableado del calendario.
El recorrido completo con Postgres está en tests/integration/test_calendar_job_progress.py.
"""
from __future__ import annotations

import uuid

import pytest

from dossier.db.models import Dossier
from dossier.graphs.corporate_dossier_graph import CorporateDossierResult
from dossier.services import calendar_event_dossiers as cal
from dossier.services import dossier_progress_model as m

REUNION = {
    "tema": "Kick-off con Acme Corp",
    "descripcion": (
        "Empresa: Acme Corp\n"
        "Contacto 1: Ana Prueba\nCargo 1: Directora\n"
        "Contacto 2: Beto Prueba\nCargo 2: Gerente"
    ),
    "participantes": "",
    "inicio": "2026-10-20T10:00:00Z",
}


def _resultado_persona(nombre, *, md="## Informe\n\nTexto.", perfiles=1):
    return {
        "filters_applied": {"research_source": "pdl", "profiles_count": perfiles},
        "profiles": [{"provider": "pdl", "linkedin_urls": [], "data": {"full_name": nombre}}] * perfiles,
        "profile_urls": [],
        "warnings": [],
        "llm_analysis_markdown": md,
        "executive_payload": None,
    }


@pytest.fixture
def calendario(monkeypatch):
    """Grafo y personas como dobles que dejan rastro en el scope recibido; sin Redis."""
    llamadas: dict[str, list] = {"grafo": [], "persona": []}

    def grafo(**kwargs):
        progress = kwargs["progress"]
        llamadas["grafo"].append(progress.scope_id)
        progress.agent("agent_corporate_uk", "running")
        progress.agent("agent_corporate_uk", "failed", "provider_error")
        return CorporateDossierResult(
            markdown="# Dossier corporativo\n\nResumen.", agents_failed=["agent_corporate_uk"], agents_succeeded=[]
        )

    def persona(req, **kwargs):
        progress = kwargs["progress"]
        llamadas["persona"].append((req.full_name, progress.scope_id))
        if req.research_source.value == "gemini_web":
            progress.stage("person.context_analysis", "running")
            progress.stage("person.context_analysis", "completed")
            return _resultado_persona(req.full_name)
        progress.stage("person.pdl_enrich", "running")
        if req.full_name.startswith("Beto"):
            progress.stage("person.pdl_enrich", "completed", "no_matches")
            return _resultado_persona(req.full_name, md=None, perfiles=0)
        progress.stage("person.pdl_enrich", "completed")
        return _resultado_persona(req.full_name)

    monkeypatch.setattr(cal, "run_corporate_dossier_langgraph_detailed", grafo)
    monkeypatch.setattr(cal, "run_person_research", persona)
    monkeypatch.setattr(cal, "resolve_corporate_brief", lambda q: (q, "dual"))
    monkeypatch.setenv("PERSON_RESEARCH_PROVIDER", "pdl")
    return llamadas


def _generar(progreso, **extra):
    job = progreso.job()
    item = cal.generate_dossiers_from_calendar_event(
        REUNION, organization_id=uuid.uuid4(), organization_plan=extra.pop("plan", "pro"), progress=job, **extra
    )
    return job, item


def _scope(job, scope_id):
    return m.find_scope(job.snapshot(), scope_id)


def test_declara_un_scope_corporativo_y_uno_por_asistente_antes_de_ejecutar(progreso, calendario):
    _, item = _generar(progreso)

    primer = progreso.eventos[0]
    assert primer[0] == "job_status"
    scopes = primer[1]["progress"]["scopes"]
    assert [(s["scope_id"], s["kind"], s["label"]) for s in scopes] == [
        ("corporate:0", "corporate", "Acme Corp"),
        ("person:0", "person", "Ana Prueba"),
        ("person:1", "person", "Beto Prueba"),
    ]
    assert {s.get("research_source") for s in scopes[1:]} == {"pdl"}
    assert calendario["grafo"] == ["corporate:0"]
    assert calendario["persona"] == [("Ana Prueba", "person:0"), ("Beto Prueba", "person:1")]
    assert [p["scope_id"] for p in item["dossier_personas"]] == ["person:0", "person:1"]


def test_los_eventos_de_cada_asistente_quedan_en_su_scope(progreso, calendario):
    _generar(progreso)

    por_scope = {
        (d["scope_id"], d["stage_id"]): d["reason_code"]
        for d in progreso.de("stage_progress")
        if d["status"] == "completed"
    }
    assert por_scope == {("person:0", "person.pdl_enrich"): None, ("person:1", "person.pdl_enrich"): "no_matches"}
    assert [d["scope_id"] for d in progreso.de("agent_progress")] == ["corporate:0", "corporate:0"]


def test_modalidad_del_calendario_viene_del_servidor(progreso, calendario, monkeypatch):
    monkeypatch.setenv("PERSON_RESEARCH_PROVIDER", "gemini_web")

    job, _ = _generar(progreso)

    assert _scope(job, "person:0")["research_source"] == "gemini_web"


def test_plan_free_declara_el_corporativo_omitido_sin_ejecutarlo(progreso, calendario):
    job, item = _generar(progreso, plan="free")

    assert calendario["grafo"] == []
    agentes = _scope(job, "corporate:0")["agents"]
    assert {(a["status"], a["reason_code"]) for a in agentes} == {("skipped", "plan_not_included")}
    assert item["corporate_skipped_plan_free"] is True


def test_corporativo_desde_cache_no_inventa_ejecuciones(progreso, calendario, monkeypatch):
    monkeypatch.setattr(cal, "redis_corporate_cache_available", lambda: True)
    monkeypatch.setattr(cal, "get_corporate_cached_markdown", lambda key: "# Dossier en caché\n\nResumen.")

    job, _ = _generar(progreso)

    assert calendario["grafo"] == []
    scope = _scope(job, "corporate:0")
    assert {(a["status"], a["reason_code"]) for a in scope["agents"]} == {("skipped", "cache_hit")}
    assert scope["origin"] == "redis_cache"
    sintesis = next(p for p in scope["partial_results"] if p["section"] == "synthesis")
    assert sintesis["origin"] == "redis_cache"


def test_corporativo_generado_declara_su_origen(progreso, calendario):
    job, _ = _generar(progreso)

    assert _scope(job, "corporate:0")["origin"] == "generated"


# --- caché de personas del calendario -------------------------------------


@pytest.fixture
def cache_persona(monkeypatch):
    estado = {"disponible": True, "respuestas": [], "guardados": []}

    def obtener(fp):
        return estado["respuestas"].pop(0) if estado["respuestas"] else None

    monkeypatch.setattr(cal, "redis_person_cache_available", lambda: estado["disponible"])
    monkeypatch.setattr(cal, "get_person_cached_payload", obtener)
    monkeypatch.setattr(cal, "set_person_cached_payload", lambda fp, payload: estado["guardados"].append(payload))
    monkeypatch.setattr(cal, "run_with_person_cache_lock", lambda fp, fn: fn())
    return estado


CACHE_ANTIGUA = {
    "markdown": "## Informe en caché\n\nAna Prueba.",
    "profiles_count": 2,
    "profile_urls": ["https://www.linkedin.com/in/ana"],
    "warnings": [],
}


def _etapas_de(progreso, scope_id):
    return [
        (d["stage_id"], d["status"], d["reason_code"])
        for d in progreso.de("stage_progress")
        if d["scope_id"] == scope_id
    ]


def test_persona_sin_redis_omite_la_consulta_a_cache(progreso, calendario, cache_persona):
    cache_persona["disponible"] = False

    _generar(progreso)

    assert _etapas_de(progreso, "person:0")[0] == ("person.cache_lookup", "skipped", "cache_unavailable")


def test_persona_sin_acierto_de_cache_investiga(progreso, calendario, cache_persona):
    _generar(progreso)

    etapas = _etapas_de(progreso, "person:0")
    assert etapas[:2] == [
        ("person.cache_lookup", "running", None),
        ("person.cache_lookup", "completed", "cache_miss"),
    ]
    assert ("person.pdl_enrich", "running", None) in etapas


def test_acierto_de_cache_antigua_no_inventa_etapas_ni_perfiles(progreso, calendario, cache_persona):
    cache_persona["respuestas"] = [dict(CACHE_ANTIGUA)] * 2

    job, _ = _generar(progreso)

    etapas = _etapas_de(progreso, "person:0")
    assert etapas[0:2] == [
        ("person.cache_lookup", "running", None),
        ("person.cache_lookup", "completed", "cache_hit"),
    ]
    omitidas = {e for e, s, r in etapas if (s, r) == ("skipped", "cache_hit")}
    assert omitidas == set(m.PERSON_STAGES["pdl"]) - {
        "person.cache_lookup",
        "person.report_finalize",
        "person.persist",
    }
    assert ("person.report_finalize", "completed", None) in etapas
    scope = _scope(job, "person:0")
    assert (scope["origin"], scope["profiles_count"]) == ("redis_cache", 2)
    secciones = {p["section"]: p for p in scope["partial_results"]}
    assert "person_profiles" not in secciones, "la caché no trae perfiles: no se inventan"
    assert secciones["person_report"]["origin"] == "redis_cache"
    assert secciones["person_report"]["provenance"]["basis"] == "unknown"


def test_acierto_bajo_el_candado_tambien_cuenta_como_cache(progreso, calendario, cache_persona):
    cache_persona["respuestas"] = [None, dict(CACHE_ANTIGUA)]

    _generar(progreso)

    etapas = _etapas_de(progreso, "person:0")
    assert ("person.cache_lookup", "completed", "cache_hit") in etapas
    assert not any(e == "person.pdl_enrich" and s == "running" for e, s, _ in etapas)


def test_la_cache_no_guarda_ids_ni_progreso_del_job(progreso, calendario, cache_persona):
    _generar(progreso)

    assert cache_persona["guardados"], "el informe válido se cachea como siempre"
    for payload in cache_persona["guardados"]:
        texto = repr(payload)
        assert "_progress" not in texto and "scope_id" not in texto and "person:0" not in texto


# --- guardado -----------------------------------------------------------------


class _Sesion:
    def __init__(self, falla=False):
        self.added: list[object] = []
        self._falla = falla

    def get(self, model, pk):
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        if self._falla:
            raise RuntimeError("base caída")


def _persistir(job, item, db):
    return cal.persist_calendar_dossiers(
        db,
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        result=item,
        calendar_provider="google",
        generation_duration_ms=10,
        progress=job,
    )


def test_guardar_cierra_persist_por_asistente_y_enlaza_cada_dossier(progreso, calendario):
    job, item = _generar(progreso)
    db = _Sesion()

    item = _persistir(job, item, db)

    personas = {d.subject_name: d for d in db.added if isinstance(d, Dossier) and not d.module_corporate}
    ana, beto = personas["Ana Prueba"], personas["Beto Prueba"]
    assert _etapas_de(progreso, "person:0")[-1] == ("person.persist", "completed", None)
    assert _etapas_de(progreso, "person:1")[-1] == ("person.persist", "failed", "no_valid_report")
    ultimo = [d for d in progreso.de("stage_progress") if d["scope_id"] == "person:1"][-1]
    assert (ultimo["dossier_id"], ultimo["dossier_status"]) == (str(beto.id), "failed")
    assert _scope(job, "person:0")["dossier"] == {"id": str(ana.id), "status": "complete"}
    corporativo = next(d for d in db.added if isinstance(d, Dossier) and d.module_corporate)
    assert _scope(job, "corporate:0")["dossier"] == {"id": str(corporativo.id), "status": "complete"}
    assert corporativo.agents_failed == ["agent_corporate_uk"], "S4.9 se conserva"


def test_cada_dossier_guarda_una_copia_de_su_scope(progreso, calendario):
    job, item = _generar(progreso)
    db = _Sesion()

    _persistir(job, item, db)

    for d in db.added:
        copia = d.dossier_data["_progress"]
        assert copia["job_id"] == str(job.job_id)
        esperado = "corporate:0" if d.module_corporate else {"Ana Prueba": "person:0", "Beto Prueba": "person:1"}[
            d.subject_name
        ]
        assert copia["scope"]["scope_id"] == esperado


def test_si_el_commit_falla_persist_queda_fallido_y_se_propaga(progreso, calendario):
    job, item = _generar(progreso)

    with pytest.raises(RuntimeError):
        _persistir(job, item, _Sesion(falla=True))

    assert _etapas_de(progreso, "person:0")[-1] == ("person.persist", "failed", "persistence_error")


def test_sin_job_el_calendario_hace_lo_de_siempre(calendario, monkeypatch):
    monkeypatch.setattr(
        cal,
        "run_corporate_dossier_langgraph_detailed",
        lambda **kwargs: CorporateDossierResult(markdown="# ok", agents_failed=[], agents_succeeded=[]),
    )
    monkeypatch.setattr(cal, "run_person_research", lambda req, **kwargs: _resultado_persona(req.full_name))

    item = cal.generate_dossiers_from_calendar_event(REUNION, organization_id=uuid.uuid4(), organization_plan="pro")
    db = _Sesion()
    cal.persist_calendar_dossiers(
        db, user_id=uuid.uuid4(), org_id=uuid.uuid4(), result=item, calendar_provider="google", generation_duration_ms=1
    )

    assert item["dossier_corporativo"] == "# ok"
    assert all("_progress" not in d.dossier_data for d in db.added)
