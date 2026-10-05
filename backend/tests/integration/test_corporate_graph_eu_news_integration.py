"""S2.2, integración: el grafo corporativo completo con los agentes europeo y de noticias.

Recorre LangGraph real; solo los proveedores (UK, USA, Europa, noticias) y el LLM son dobles.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dossier.eu_registry.agent import ResultadoAgenteEuropeo
from dossier.graphs.corporate_dossier_graph import run_corporate_dossier_langgraph_detailed
from dossier.news.agent import ResultadoRecoleccionPrensa
from dossier.schemas.corporate_registry import JurisdiccionRegistro, RegistroCorporativo
from dossier.schemas.dossier_executive_payload import (
    CorporateRecordCitation,
    PressMention,
    SourceCitation,
    SourceType,
)

AHORA = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _cita_eu() -> CorporateRecordCitation:
    return CorporateRecordCitation(
        record=RegistroCorporativo(
            jurisdiccion=JurisdiccionRegistro.de,
            fuente="offeneregister",
            identificador_registro="HRB 999",
            razon_social="Acme GmbH",
        ),
        source=SourceCitation(
            source_type=SourceType.eu_registry, source_name="offeneregister", retrieved_at=AHORA
        ),
    )


@pytest.fixture
def proveedores(monkeypatch):
    """Los cuatro agentes y el LLM, sustituidos; devuelve los prompts enviados al LLM."""
    prompts: list[str] = []

    monkeypatch.setattr(
        "dossier.services.corporate_registry_context.build_uk_corporate_context_markdown",
        lambda participantes: "## Reino Unido\n\nACME UK LTD",
    )
    monkeypatch.setattr(
        "dossier.services.corporate_registry_context.build_us_corporate_context_markdown",
        lambda participantes: "## Estados Unidos\n\nACME CORP",
    )
    monkeypatch.setattr(
        "dossier.eu_registry.agent.run_eu_registry_agent",
        lambda nombre, **_: ResultadoAgenteEuropeo(citas=[_cita_eu()]),
    )
    monkeypatch.setattr(
        "dossier.news.agent.collect_press_mentions",
        lambda consulta, **_: ResultadoRecoleccionPrensa(
            mentions=[
                PressMention(
                    headline="Acme cierra una ronda de financiamiento",
                    publisher="Diario de Prueba",
                    summary="Resumen.",
                    url="https://example.test/acme",
                    source=SourceCitation(
                        source_type=SourceType.news_api, source_name="news_api", retrieved_at=AHORA
                    ),
                )
            ]
        ),
    )

    def llm(prompt, **_):
        prompts.append(prompt)
        return "# Dossier corporativo"

    monkeypatch.setattr("dossier.llm.text_generate.generate_text_with_llm", llm)
    return prompts


def _correr(alcance, empresa="Acme"):
    return run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión",
        participantes="Acme",
        jurisdiction_scope=alcance,
        empresa_objetivo=empresa,
    )


def test_alcance_dual_corre_los_cuatro_agentes_y_la_sintesis_recibe_todo(proveedores):
    resultado = _correr("dual")

    assert set(resultado.agents_succeeded) >= {
        "agent_corporate_uk",
        "agent_corporate_usa",
        "agent_corporate_eu",
        "agent_news",
        "synthesize_llm",
    }
    assert resultado.agents_failed == []
    prompt = proveedores[0]
    for fragmento in ("ACME UK LTD", "ACME CORP", "Acme GmbH", "Acme cierra una ronda"):
        assert fragmento in prompt, fragmento


def test_alcance_uk_only_omite_europa_y_usa_pero_mantiene_prensa(proveedores):
    resultado = _correr("uk_only")

    assert set(resultado.agents_skipped) >= {"agent_corporate_eu", "agent_corporate_usa"}
    assert "agent_news" in resultado.agents_succeeded
    assert "Acme GmbH" not in proveedores[0]
    assert "Acme cierra una ronda" in proveedores[0]


def test_alcance_eu_only_omite_uk_y_usa(proveedores):
    resultado = _correr("eu_only")

    assert set(resultado.agents_skipped) == {"agent_corporate_uk", "agent_corporate_usa"}
    assert {"agent_corporate_eu", "agent_news"} <= set(resultado.agents_succeeded)
    assert "Acme GmbH" in proveedores[0]


def test_sin_empresa_objetivo_el_grafo_se_comporta_como_antes(proveedores):
    resultado = _correr("dual", empresa=None)

    assert set(resultado.agents_skipped) == {"agent_corporate_eu", "agent_news"}
    assert "Acme GmbH" not in proveedores[0]


def test_fallo_del_agente_europeo_no_impide_la_sintesis(proveedores, monkeypatch):
    """CA2 de S0.12 aplicado al nodo nuevo."""

    def caido(nombre, **_):
        raise TimeoutError("registro europeo no respondió")

    monkeypatch.setattr("dossier.eu_registry.agent.run_eu_registry_agent", caido)

    resultado = _correr("dual")

    assert resultado.agents_failed == ["agent_corporate_eu"]
    assert "synthesize_llm" in resultado.agents_succeeded
    assert resultado.markdown == "# Dossier corporativo"


def test_el_calendario_pasa_la_empresa_al_grafo(monkeypatch):
    from dossier.graphs.corporate_dossier_graph import CorporateDossierResult
    from dossier.services import calendar_event_dossiers as cal

    capturado: dict = {}

    def detallado(**kwargs):
        capturado.update(kwargs)
        return CorporateDossierResult(markdown="# ok", agents_failed=[], agents_succeeded=[])

    monkeypatch.setattr(cal, "run_corporate_dossier_langgraph_detailed", detallado)
    monkeypatch.setattr(cal, "redis_corporate_cache_available", lambda: False)
    monkeypatch.setattr(cal, "get_corporate_cached_markdown", lambda key: None)
    monkeypatch.setattr(cal, "run_with_corporate_cache_lock", lambda key, fn: fn())

    cal._corporate_md_from_cache_or_langgraph(
        participantes_brief="Acme — brief",
        tema="Reunión",
        participantes="Acme — brief",
        scope="dual",
        depth="standard",
        empresa_objetivo="Acme",
    )

    assert capturado["empresa_objetivo"] == "Acme"


@pytest.mark.parametrize(
    ("resolucion", "esperado"),
    [
        (None, "Acme SpA"),
        ({"source": "companies_house", "title": "ACME UK LTD", "company_number": "123"}, "ACME UK LTD"),
    ],
)
def test_la_api_toma_la_empresa_de_la_resolucion_o_de_la_consulta(resolucion, esperado):
    from dossier.api.dossier_routes import empresa_objetivo_de_solicitud
    from dossier.schemas.dossier_generation import CreateCorporateDossierRequest

    body = CreateCorporateDossierRequest(subject_query="Acme SpA", resolution=resolucion)

    assert empresa_objetivo_de_solicitud(body) == esperado
