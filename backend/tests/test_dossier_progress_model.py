"""S5.10 · Modelo puro del progreso por scopes (ADR 0009).

Sin base de datos ni bus: reglas de estado, revisiones, cierre al terminar el job,
límites de las vistas previas y la proyección pública de perfiles PDL.
"""
from __future__ import annotations

import json

import pytest

from dossier.services import dossier_progress_model as m

AHORA = "2026-10-15T12:00:00+00:00"


def _progreso_con(*scopes):
    p = m.new_progress()
    for s in scopes:
        assert m.add_scope(p, s) is True
    return p


def _entidad(p, scope_id, entity_id):
    scope = m.find_scope(p, scope_id)
    clave = "agents" if scope["kind"] == "corporate" else "stages"
    campo = "agent_name" if scope["kind"] == "corporate" else "stage_id"
    return next(e for e in scope[clave] if e[campo] == entity_id)


# --- catálogos -------------------------------------------------------------


def test_scope_corporativo_declara_los_cinco_agentes_en_orden_y_pendientes():
    s = m.corporate_scope("corporate:0", "Acme Corp")

    assert s["kind"] == "corporate"
    assert [a["agent_name"] for a in s["agents"]] == [
        "agent_corporate_uk",
        "agent_corporate_usa",
        "agent_corporate_eu",
        "agent_news",
        "synthesize_llm",
    ]
    assert {a["status"] for a in s["agents"]} == {"pending"}
    assert s["partial_results"] == [] and s["dossier"] is None


def test_scope_pdl_y_gemini_web_tienen_catalogos_distintos_y_sin_busqueda_en_vivo():
    pdl = m.person_scope("person:0", "Ana Prueba", "pdl")
    web = m.person_scope("person:1", "Ana Prueba", "gemini_web")

    assert [e["stage_id"] for e in pdl["stages"]] == [
        "person.cache_lookup",
        "person.pdl_enrich",
        "person.pdl_search",
        "person.profile_normalization",
        "person.context_analysis",
        "person.profile_synthesis",
        "person.markdown_fallback",
        "person.report_finalize",
        "person.persist",
    ]
    assert [e["stage_id"] for e in web["stages"]] == [
        "person.cache_lookup",
        "person.context_analysis",
        "person.report_finalize",
        "person.persist",
    ]
    assert pdl["live_web_search"] is False and web["live_web_search"] is False
    assert web["research_source"] == "gemini_web"


def test_scope_persona_rechaza_una_modalidad_desconocida():
    with pytest.raises(ValueError):
        m.person_scope("person:0", "Ana", "google_search")


def test_no_se_declara_dos_veces_el_mismo_scope():
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))

    assert m.add_scope(p, m.corporate_scope("corporate:0", "Acme")) is False
    assert len(p["scopes"]) == 1


# --- transiciones ----------------------------------------------------------


def test_cada_cambio_sube_la_revision_del_job_y_la_guarda_en_la_entidad():
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))

    a = m.update_entity(p, "corporate:0", "agent_corporate_uk", "running", now=AHORA)
    b = m.update_entity(p, "corporate:0", "agent_corporate_usa", "running", now=AHORA)

    assert (a["revision"], b["revision"]) == (1, 2)
    assert p["revision"] == 2
    assert _entidad(p, "corporate:0", "agent_corporate_uk")["timestamp"] == AHORA


def test_un_terminal_no_vuelve_a_running_ni_cambia_a_otro_terminal():
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))
    m.update_entity(p, "corporate:0", "agent_news", "failed", reason_code="provider_error", now=AHORA)

    assert m.update_entity(p, "corporate:0", "agent_news", "running", now=AHORA) is None
    assert m.update_entity(p, "corporate:0", "agent_news", "completed", now=AHORA) is None
    assert _entidad(p, "corporate:0", "agent_news")["status"] == "failed"
    assert p["revision"] == 1


def test_un_terminal_puede_ganar_metadatos_sin_cambiar_de_estado():
    p = _progreso_con(m.person_scope("person:0", "Ana", "pdl"))
    m.update_entity(p, "person:0", "person.context_analysis", "completed", now=AHORA)

    cambio = m.update_entity(
        p, "person:0", "person.context_analysis", "completed", meta={"used_in_final": False}, now=AHORA
    )

    assert cambio is not None and cambio["used_in_final"] is False
    assert cambio["status"] == "completed"


def test_repetir_el_mismo_estado_sin_metadatos_nuevos_no_genera_revision():
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))
    m.update_entity(p, "corporate:0", "agent_corporate_uk", "running", now=AHORA)

    assert m.update_entity(p, "corporate:0", "agent_corporate_uk", "running", now=AHORA) is None
    assert p["revision"] == 1


@pytest.mark.parametrize(
    ("scope", "entidad"),
    [
        ("corporate:0", "person.pdl_enrich"),  # etapa personal en un scope corporativo
        ("person:0", "agent_corporate_uk"),  # agente corporativo en un scope personal
        ("person:0", "person.pdl_search"),  # etapa PDL en Web pública
        ("person:9", "person.persist"),  # scope inexistente
    ],
)
def test_no_se_aplican_entidades_fuera_del_catalogo_del_scope(scope, entidad):
    p = _progreso_con(
        m.corporate_scope("corporate:0", "Acme"), m.person_scope("person:0", "Ana", "gemini_web")
    )

    with pytest.raises(ValueError):
        m.update_entity(p, scope, entidad, "running", now=AHORA)
    assert p["revision"] == 0


def test_motivo_y_estado_deben_ser_del_contrato():
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))

    with pytest.raises(ValueError):
        m.update_entity(p, "corporate:0", "agent_news", "exploded", now=AHORA)
    with pytest.raises(ValueError):
        m.update_entity(p, "corporate:0", "agent_news", "failed", reason_code="Traceback ...", now=AHORA)
    with pytest.raises(ValueError):
        # cache_hit no es un motivo de fallo
        m.update_entity(p, "corporate:0", "agent_news", "failed", reason_code="cache_hit", now=AHORA)


def test_metadatos_fuera_de_la_lista_permitida_se_rechazan():
    p = _progreso_con(m.person_scope("person:0", "Ana", "pdl"))

    with pytest.raises(ValueError):
        m.update_entity(
            p, "person:0", "person.pdl_enrich", "failed", meta={"error": "PDL HTTP 500 ..."}, now=AHORA
        )


# --- parciales y campos del scope -----------------------------------------


def test_un_parcial_reemplaza_al_de_la_misma_seccion_y_conserva_los_demas():
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))
    m.put_partial(p, "corporate:0", m.corporate_partial("agent_news", "news", "- uno"))
    m.put_partial(p, "corporate:0", m.corporate_partial("agent_corporate_eu", "corporate_eu", "- reg"))
    m.put_partial(p, "corporate:0", m.corporate_partial("agent_news", "news", "- dos"))

    parciales = m.find_scope(p, "corporate:0")["partial_results"]
    assert [x["section"] for x in parciales] == ["corporate_eu", "news"]
    assert next(x for x in parciales if x["section"] == "news")["content"] == "- dos"
    assert p["revision"] == 3


def test_parcial_corporativo_rechaza_secciones_sin_vista_previa_publica():
    with pytest.raises(ValueError):
        m.corporate_partial("agent_corporate_uk", "corporate_uk", "## UK")


@pytest.mark.parametrize("texto", [None, "", "   ", "# Error en síntesis\n\nDeepSeek caído"])
def test_parcial_sin_contenido_valido_no_existe(texto):
    assert m.corporate_partial("synthesize_llm", "synthesis", texto) is None
    assert (
        m.person_partial_markdown(
            "person.report_finalize", "person_report", texto, basis="model_only", sources=[], origin="generated"
        )
        is None
    )


def test_campos_del_scope_suben_revision_solo_si_cambian():
    p = _progreso_con(m.person_scope("person:0", "Ana", "pdl"))

    assert m.set_scope_fields(p, "person:0", {"origin": "redis_cache", "profiles_count": 2}) is True
    assert m.set_scope_fields(p, "person:0", {"origin": "redis_cache"}) is False
    assert p["revision"] == 1
    with pytest.raises(ValueError):
        m.set_scope_fields(p, "person:0", {"label": "otra persona"})


# --- cierre ----------------------------------------------------------------


def test_al_terminar_pendientes_quedan_omitidas_y_en_curso_interrumpidas():
    p = _progreso_con(m.person_scope("person:0", "Ana", "pdl"))
    m.update_entity(p, "person:0", "person.cache_lookup", "completed", reason_code="cache_miss", now=AHORA)
    m.update_entity(p, "person:0", "person.pdl_enrich", "running", now=AHORA)

    cerrado = m.finalize_progress(p, "failed", now=AHORA)

    estados = {e["stage_id"]: (e["status"], e["reason_code"]) for e in cerrado["scopes"][0]["stages"]}
    assert estados["person.cache_lookup"] == ("completed", "cache_miss")
    assert estados["person.pdl_enrich"] == ("failed", "interrupted")
    assert estados["person.persist"] == ("skipped", "not_reached")
    assert cerrado["revision"] == p["revision"] + 1
    assert _entidad(p, "person:0", "person.pdl_enrich")["status"] == "running", "no muta el original"


def test_al_cancelar_lo_que_estaba_en_curso_queda_cancelado():
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))
    m.update_entity(p, "corporate:0", "agent_news", "running", now=AHORA)

    cerrado = m.finalize_progress(p, "cancelled", now=AHORA)

    noticias = next(a for a in cerrado["scopes"][0]["agents"] if a["agent_name"] == "agent_news")
    assert noticias["status"] == "cancelled"


def test_cerrar_sin_progreso_o_ya_cerrado_no_inventa_nada():
    assert m.finalize_progress(None, "completed", now=AHORA) is None
    p = _progreso_con(m.corporate_scope("corporate:0", "Acme"))
    for a in m.CORPORATE_AGENTS:
        m.update_entity(p, "corporate:0", a, "completed", now=AHORA)

    assert m.finalize_progress(p, "completed", now=AHORA)["revision"] == p["revision"]


# --- vistas previas --------------------------------------------------------


def test_vista_previa_corta_entre_bloques_completos_y_lo_marca():
    bloques = [f"- **Registro {i}** {'x' * 900}" for i in range(60)]  # ~54 KiB
    texto = "## Registros\n\n" + "\n".join(bloques)

    contenido, truncado = m.markdown_preview(texto)

    assert truncado is True
    assert len(contenido.encode("utf-8")) <= m.PREVIEW_MAX_BYTES
    assert contenido.splitlines()[-1].startswith("- **Registro"), "no corta un bloque a la mitad"
    assert contenido.splitlines()[-1].endswith("x")


def test_vista_previa_respeta_caracteres_multibyte_en_el_limite():
    texto = "ñ" * 40_000  # un solo bloque de 80 KB en UTF-8

    contenido, truncado = m.markdown_preview(texto)

    assert truncado is True
    contenido.encode("utf-8").decode("utf-8")  # no deja un carácter partido
    assert len(contenido.encode("utf-8")) <= m.PREVIEW_MAX_BYTES


def test_vista_previa_corta_no_se_marca_truncada():
    assert m.markdown_preview("## Breve\n\nTexto.") == ("## Breve\n\nTexto.", False)


# --- proyección de perfiles PDL -------------------------------------------


PERFIL_PDL = {
    "provider": "pdl",
    "provider_id": "pdl-123",
    "pdl_id": "pdl-123",
    "linkedin_urls": [
        "https://www.linkedin.com/in/ana",
        "http://inseguro.example/ana",
        "javascript:alert(1)",
        "https://usuario:clave@example.com/x",
        "https://example.com/dos",
        "https://example.com/tres",
    ],
    "data": {
        "full_name": "Ana Prueba",
        "job_title": "Directora",
        "job_company_name": "Empresa de prueba",
        "emails": [{"address": "ana@empresa.example"}],
        "phone_numbers": ["+56 9 1234 5678"],
        "mobile_phone": "+56 9 1234 5678",
    },
}


def test_dto_de_perfiles_solo_lleva_campos_permitidos_y_urls_seguras():
    dto = m.person_profiles_data([PERFIL_PDL])

    assert dto["profiles_count"] == 1
    perfil = dto["profiles"][0]
    assert set(perfil) == {"record_key", "full_name", "job_title", "company", "profile_urls"}
    assert perfil == {
        "record_key": "profile:0",
        "full_name": "Ana Prueba",
        "job_title": "Directora",
        "company": "Empresa de prueba",
        "profile_urls": [
            "https://www.linkedin.com/in/ana",
            "https://example.com/dos",
            "https://example.com/tres",
        ],
    }
    serializado = json.dumps(dto)
    for prohibido in ("pdl-123", "ana@empresa", "1234 5678", "javascript", "clave@"):
        assert prohibido not in serializado


def test_dto_tolera_perfiles_sin_campos_de_negocio():
    dto = m.person_profiles_data([{"linkedin_urls": [], "data": {}}, {"data": None}])

    assert dto["profiles_count"] == 2
    assert dto["profiles"][0] == {
        "record_key": "profile:0",
        "full_name": None,
        "job_title": None,
        "company": None,
        "profile_urls": [],
    }


def test_parcial_de_perfiles_declara_procedencia_de_registros_sin_busqueda_en_vivo():
    parcial = m.person_partial_profiles("person.profile_normalization", [PERFIL_PDL], origin="generated")

    assert parcial["section"] == "person_profiles"
    assert parcial["format"] == "person_profiles"
    assert parcial["provenance"] == {"basis": "provider_records", "sources": ["pdl"], "live_web_search": False}
    assert parcial["provisional"] is True and parcial["truncated"] is False
    assert m.person_partial_profiles("person.profile_normalization", [], origin="generated") is None


def test_parcial_markdown_de_persona_valida_procedencia():
    parcial = m.person_partial_markdown(
        "person.context_analysis",
        "person_context_report",
        "## Informe\n\nTexto del modelo.",
        basis="model_only",
        sources=[],
        origin="generated",
    )

    assert parcial["provenance"] == {"basis": "model_only", "sources": [], "live_web_search": False}
    with pytest.raises(ValueError):
        m.person_partial_markdown(
            "person.context_analysis", "person_context_report", "x", basis="web_search", sources=[], origin="generated"
        )
