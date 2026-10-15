"""S5.10 · BE8–BE11: etapas reales de la investigación de una persona.

Recorre ``run_person_research`` real con un doble del cliente PDL y del LLM.
Las etapas de caché y guardado viven en los wrappers (manual y calendario):
ver tests/integration/test_person_job_progress.py y test_calendar_person_progress.py.
"""
from __future__ import annotations

import json

import pytest
import requests

from dossier.schemas.person_research import PersonResearchRequest, PersonResearchSource
from dossier.services import dossier_progress_model as m
from dossier.services import pdl_research, person_research_service
from dossier.services.pdl_client import PdlApiError

SECRETO = "detalle-interno-91c2"
PERSONA_PDL = {
    "id": "pdl-ana-1",
    "full_name": "Ana Prueba",
    "job_title": "Directora",
    "job_company_name": "Empresa de Prueba SA",
    "linkedin_url": "https://www.linkedin.com/in/ana-prueba",
    "emails": [{"address": "ana@empresa.example"}],
    "mobile_phone": "+56 9 1111 2222",
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
    """Cliente PDL: ``enrich`` y ``search`` deciden la respuesta por llamada."""

    def __init__(self, enrich=None, search=None):
        self._enrich = enrich or (lambda params: None)
        self._search = search or (lambda sql: {"data": [], "total": 0})
        self.enrich_llamadas: list[dict] = []
        self.search_llamadas: list[str] = []

    def person_enrich(self, params):
        self.enrich_llamadas.append(params)
        return self._enrich(params)

    def person_search(self, *, sql=None, query=None, size=5):
        self.search_llamadas.append(sql)
        return self._search(sql)


def _lanza(exc):
    def _f(*_a, **_k):
        raise exc

    return _f


@pytest.fixture
def entorno(monkeypatch):
    """Clave de DeepSeek presente, análisis contextual habilitado y sin ALWAYS."""
    monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "clave-de-prueba")
    monkeypatch.delenv("DEEPSEEK_DISABLE_PERSON_WEB", raising=False)
    monkeypatch.delenv("GEMINI_DISABLE_GOOGLE_SEARCH", raising=False)
    monkeypatch.delenv("DEEPSEEK_PERSON_WEB_ALWAYS", raising=False)
    monkeypatch.delenv("GEMINI_PERSON_WEB_ALWAYS", raising=False)
    contexto: list[dict] = []

    def analisis_contextual(**kwargs):
        contexto.append(kwargs)
        return "## Informe con IA\n\nAna Prueba, según el encargo."

    monkeypatch.setattr(person_research_service, "analyze_person_with_google_search", analisis_contextual)
    respaldo: list[dict] = []

    def markdown(**kwargs):
        respaldo.append(kwargs)
        return "## Informe Markdown de respaldo\n\nAna Prueba dirige la empresa."

    monkeypatch.setattr(person_research_service, "analyze_person_profile_bundle", markdown)

    class Entorno:
        llamadas_contexto = contexto
        llamadas_respaldo = respaldo

        def pdl(self, **kwargs):
            falso = PdlFalso(**kwargs)
            monkeypatch.setattr(pdl_research, "PdlClient", lambda: falso)
            return falso

        def sin_pdl(self):
            def no_construir():
                raise AssertionError("Web pública no debe consultar PDL")

            monkeypatch.setattr(pdl_research, "PdlClient", no_construir)

        def sin_clave_llm(self):
            monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "")

        def contextual(self, fn):
            monkeypatch.setattr(person_research_service, "analyze_person_with_google_search", fn)

        def siempre(self):
            monkeypatch.setenv("DEEPSEEK_PERSON_WEB_ALWAYS", "1")

        def deshabilitar_contexto(self):
            monkeypatch.setenv("DEEPSEEK_DISABLE_PERSON_WEB", "1")

        def sintesis(self, fn):
            monkeypatch.setattr(person_research_service, "analyze_person_profile_bundle_structured", fn)

    return Entorno()


def _encontrado(params):
    return {"data": dict(PERSONA_PDL), "likelihood": 8} if "email" in params else None


def _investigar(progreso, fuente="pdl", **extra):
    job = progreso.job()
    job.declare([m.person_scope("person:0", "Ana Prueba", fuente)])
    req = PersonResearchRequest(
        full_name="Ana Prueba",
        company="Empresa de Prueba SA",
        email="ana@empresa.example",
        research_source=PersonResearchSource(fuente),
        max_profiles=1,
        **extra,
    )
    resultado = person_research_service.run_person_research(req, progress=job.scope("person:0"))
    return job, resultado


def _etapas(progreso):
    """{stage_id: [(status, reason_code), ...]} en orden de publicación."""
    salida: dict[str, list] = {}
    for d in progreso.de("stage_progress"):
        salida.setdefault(d["stage_id"], []).append((d["status"], d["reason_code"]))
    return salida


def _ultimo(progreso, etapa):
    eventos = [d for d in progreso.de("stage_progress") if d["stage_id"] == etapa]
    return eventos[-1] if eventos else None


def _parcial(progreso, seccion):
    return next((d for d in progreso.de("partial_result") if d["section"] == seccion), None)


def _revision(progreso, etapa, estado):
    return next(
        d["revision"] for d in progreso.de("stage_progress") if d["stage_id"] == etapa and d["status"] == estado
    )


# --- PDL ---------------------------------------------------------------------


def test_enrich_suficiente_omite_search_y_publica_perfiles_antes_de_sintetizar(progreso, entorno, llm_falso):
    pdl = entorno.pdl(enrich=_encontrado)
    llm_falso(_payload_valido())

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.pdl_enrich"] == [("running", None), ("completed", None)]
    assert etapas["person.pdl_search"] == [("skipped", "sufficient_profiles")]
    assert etapas["person.profile_normalization"] == [("running", None), ("completed", None)]
    assert etapas["person.context_analysis"] == [("skipped", "mode_not_applicable")]
    assert etapas["person.profile_synthesis"] == [("running", None), ("completed", None)]
    assert etapas["person.markdown_fallback"] == [("skipped", "not_required")]
    assert etapas["person.report_finalize"][-1] == ("completed", None)
    assert "person.persist" not in etapas, "guardar es cosa del wrapper"
    assert _ultimo(progreso, "person.pdl_enrich")["attempts"] == {"total": len(pdl.enrich_llamadas), "failed": 0}
    perfiles = _parcial(progreso, "person_profiles")
    assert perfiles["revision"] < _revision(progreso, "person.profile_synthesis", "running")
    assert perfiles["data"]["profiles"][0]["full_name"] == "Ana Prueba"
    informe = _parcial(progreso, "person_report")
    assert informe["provenance"] == {"basis": "provider_records", "sources": ["pdl"], "live_web_search": False}


def test_enrich_sin_coincidencias_pasa_a_search(progreso, entorno, llm_falso):
    pdl = entorno.pdl(search=lambda sql: {"data": [dict(PERSONA_PDL)], "total": 1})
    llm_falso(_payload_valido())

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.pdl_enrich"][-1] == ("completed", "no_matches")
    assert etapas["person.pdl_search"] == [("running", None), ("completed", None)]
    assert _ultimo(progreso, "person.pdl_search")["attempts"]["total"] == len(pdl.search_llamadas) >= 1
    assert _parcial(progreso, "person_profiles") is not None


def test_ninguna_coincidencia_no_es_un_fallo(progreso, entorno):
    entorno.pdl()
    entorno.deshabilitar_contexto()

    _, resultado = _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.pdl_enrich"][-1] == ("completed", "no_matches")
    assert etapas["person.pdl_search"][-1] == ("completed", "no_matches")
    assert etapas["person.profile_normalization"] == [("skipped", "no_profiles")]
    assert etapas["person.context_analysis"] == [("skipped", "feature_disabled")]
    assert etapas["person.profile_synthesis"] == [("skipped", "no_profiles")]
    assert etapas["person.report_finalize"] == [("skipped", "no_content")]
    assert progreso.de("partial_result") == []
    assert resultado["llm_analysis_markdown"] is None


def test_401_en_enrich_corta_y_search_queda_omitido(progreso, entorno):
    pdl = entorno.pdl(enrich=_lanza(PdlApiError(401, SECRETO)))
    entorno.deshabilitar_contexto()

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.pdl_enrich"][-1] == ("failed", "upstream_auth_failed")
    assert etapas["person.pdl_search"] == [("skipped", "upstream_auth_failed")]
    assert pdl.search_llamadas == []
    assert _ultimo(progreso, "person.pdl_enrich")["attempts"] == {"total": 1, "failed": 1}


def test_402_en_enrich_sigue_con_search(progreso, entorno, llm_falso):
    entorno.pdl(
        enrich=_lanza(PdlApiError(402, SECRETO)),
        search=lambda sql: {"data": [dict(PERSONA_PDL)], "total": 1},
    )
    llm_falso(_payload_valido())

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.pdl_enrich"][-1] == ("failed", "provider_quota")
    assert etapas["person.pdl_search"][-1] == ("completed", None)
    assert _parcial(progreso, "person_profiles") is not None


def test_429_se_distingue_de_sin_coincidencias(progreso, entorno):
    entorno.pdl(enrich=_lanza(PdlApiError(429, SECRETO)), search=_lanza(PdlApiError(429, SECRETO)))
    entorno.deshabilitar_contexto()

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.pdl_enrich"][-1] == ("failed", "provider_rate_limit")
    assert etapas["person.pdl_search"][-1] == ("failed", "provider_rate_limit")


def test_timeout_de_pdl_marca_la_etapa_y_se_propaga_como_hoy(progreso, entorno):
    entorno.pdl(enrich=_lanza(requests.Timeout(SECRETO)))

    with pytest.raises(requests.Timeout):
        _investigar(progreso)

    assert _etapas(progreso)["person.pdl_enrich"][-1] == ("failed", "provider_timeout")


def test_404_en_search_es_sin_coincidencias(progreso, entorno):
    entorno.pdl(search=_lanza(PdlApiError(404, "not found")))
    entorno.deshabilitar_contexto()

    _investigar(progreso)

    assert _etapas(progreso)["person.pdl_search"][-1] == ("completed", "no_matches")


def test_sin_clave_pdl_las_fases_pdl_se_omiten(progreso, entorno, monkeypatch):
    def sin_clave():
        raise ValueError("Falta PDL_API_KEY en el entorno (.env).")

    monkeypatch.setattr(pdl_research, "PdlClient", sin_clave)
    entorno.deshabilitar_contexto()

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.pdl_enrich"] == [("skipped", "configuration_missing")]
    assert etapas["person.pdl_search"] == [("skipped", "configuration_missing")]


def test_perfiles_sin_clave_llm_conservan_el_parcial_de_perfiles(progreso, entorno):
    entorno.pdl(enrich=_encontrado)
    entorno.sin_clave_llm()

    _, resultado = _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.profile_synthesis"] == [("skipped", "configuration_missing")]
    assert etapas["person.report_finalize"] == [("skipped", "no_content")]
    assert _parcial(progreso, "person_profiles")["data"]["profiles_count"] == 1
    assert resultado["llm_analysis_markdown"] is None


def test_json_invalido_con_respaldo_valido_se_ve_como_recuperacion(progreso, entorno, llm_falso):
    entorno.pdl(enrich=_encontrado)
    llm_falso("no es JSON", "tampoco")

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.profile_synthesis"][1] == ("failed", "structured_output_invalid")
    assert etapas["person.markdown_fallback"] == [("running", None), ("completed", None)]
    sintesis = _ultimo(progreso, "person.profile_synthesis")
    assert sintesis["status"] == "failed" and sintesis["recovered_by"] == "person.markdown_fallback"
    assert etapas["person.report_finalize"][-1] == ("completed", None)
    assert len(entorno.llamadas_respaldo) == 1


def test_proveedor_llm_caido_no_inventa_un_respaldo(progreso, entorno):
    entorno.pdl(enrich=_encontrado)
    entorno.sintesis(_lanza(RuntimeError(f"DeepSeek HTTP 503 {SECRETO}")))

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.profile_synthesis"][-1] == ("failed", "provider_error")
    assert etapas["person.markdown_fallback"] == [("skipped", "not_required")]
    assert entorno.llamadas_respaldo == []
    assert _parcial(progreso, "person_profiles") is not None, "los perfiles sobreviven al fallo"


def test_respaldo_que_tambien_falla_queda_registrado(progreso, entorno, llm_falso, monkeypatch):
    entorno.pdl(enrich=_encontrado)
    llm_falso("no es JSON", "tampoco")
    monkeypatch.setattr(
        person_research_service, "analyze_person_profile_bundle", _lanza(RuntimeError(SECRETO))
    )

    _investigar(progreso)

    assert _etapas(progreso)["person.markdown_fallback"][-1] == ("failed", "provider_error")
    assert "recovered_by" not in _ultimo(progreso, "person.profile_synthesis")


def test_pdl_sin_perfiles_usa_el_analisis_contextual(progreso, entorno):
    entorno.pdl()

    _investigar(progreso)

    etapas = _etapas(progreso)
    assert etapas["person.context_analysis"][:2] == [("running", None), ("completed", None)]
    assert _ultimo(progreso, "person.context_analysis")["used_in_final"] is True
    contexto = _parcial(progreso, "person_context_report")
    assert contexto["provenance"] == {"basis": "model_only", "sources": [], "live_web_search": False}
    assert _parcial(progreso, "person_report")["provenance"]["basis"] == "model_only"


def test_pdl_con_always_analiza_antes_de_sintetizar_y_no_usa_ese_texto(progreso, entorno, llm_falso):
    entorno.pdl(enrich=_encontrado)
    entorno.siempre()
    llm_falso(_payload_valido())

    _investigar(progreso)

    assert _revision(progreso, "person.context_analysis", "completed") < _revision(
        progreso, "person.profile_synthesis", "running"
    )
    contexto = _ultimo(progreso, "person.context_analysis")
    assert (contexto["status"], contexto["used_in_final"]) == ("completed", False)
    assert _parcial(progreso, "person_report")["provenance"]["basis"] == "provider_records"


# --- Web pública -------------------------------------------------------------


def test_web_publica_no_consulta_pdl_y_solo_publica_texto_al_volver(progreso, entorno):
    entorno.sin_pdl()

    _investigar(progreso, fuente="gemini_web")

    etapas = _etapas(progreso)
    assert set(etapas) == {"person.context_analysis", "person.report_finalize"}
    assert etapas["person.context_analysis"][:2] == [("running", None), ("completed", None)]
    assert all(d["research_source"] == "gemini_web" for d in progreso.de("stage_progress"))
    contexto = _parcial(progreso, "person_context_report")
    assert contexto["revision"] > _revision(progreso, "person.context_analysis", "running")
    assert contexto["provenance"]["live_web_search"] is False


@pytest.mark.parametrize(
    ("preparar", "motivo"),
    [("deshabilitar_contexto", "feature_disabled"), ("sin_clave_llm", "configuration_missing")],
)
def test_web_publica_sin_poder_llamar_al_modelo_se_omite(progreso, entorno, preparar, motivo):
    entorno.sin_pdl()
    getattr(entorno, preparar)()

    _investigar(progreso, fuente="gemini_web")

    assert _etapas(progreso)["person.context_analysis"] == [("skipped", motivo)]
    assert _etapas(progreso)["person.report_finalize"] == [("skipped", "no_content")]
    assert progreso.de("partial_result") == []


@pytest.mark.parametrize(
    ("respuesta", "motivo"),
    [
        (_lanza(RuntimeError(f"DeepSeek caído {SECRETO}")), "provider_error"),
        (_lanza(TimeoutError(SECRETO)), "provider_timeout"),
        (lambda **_: "", "no_valid_report"),
        (lambda **_: f"# Error\n\n{SECRETO}", "no_valid_report"),
    ],
)
def test_web_publica_con_fallo_del_modelo_no_inventa_parciales(progreso, entorno, respuesta, motivo):
    entorno.sin_pdl()
    entorno.contextual(respuesta)

    _investigar(progreso, fuente="gemini_web")

    assert _etapas(progreso)["person.context_analysis"][-1] == ("failed", motivo)
    assert progreso.de("partial_result") == []
    assert SECRETO not in json.dumps(progreso.eventos)


def test_sin_observador_el_resultado_no_cambia(entorno, llm_falso):
    entorno.pdl(enrich=_encontrado)
    llm_falso(_payload_valido())

    resultado = person_research_service.run_person_research(
        PersonResearchRequest(full_name="Ana Prueba", email="ana@empresa.example", max_profiles=1)
    )

    assert "Ana Prueba dirige Empresa de Prueba SA." in resultado["llm_analysis_markdown"]
    assert resultado["filters_applied"]["profiles_count"] == 1


def test_ningun_evento_expone_datos_crudos_de_pdl(progreso, entorno, llm_falso):
    entorno.pdl(enrich=_encontrado)
    llm_falso(_payload_valido())

    _investigar(progreso)

    texto = json.dumps(progreso.eventos)
    for prohibido in ("pdl-ana-1", "ana@empresa", "1111 2222", "min_likelihood", "SELECT"):
        assert prohibido not in texto
