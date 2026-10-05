"""S2.2: nodos europeo y de noticias en el grafo corporativo, con selección de jurisdicción.

Spec S0.12: CA1 (los agentes corren en paralelo), CA3 (los nodos fuera de alcance quedan
en ``agents_skipped`` sin llamar a la red).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dossier.eu_registry.agent import ResultadoAgenteEuropeo
from dossier.graphs import corporate_dossier_graph as grafo
from dossier.news.agent import FalloProveedor, ResultadoRecoleccionPrensa
from dossier.schemas.corporate_registry import JurisdiccionRegistro, RegistroCorporativo
from dossier.schemas.dossier_executive_payload import (
    CorporateRecordCitation,
    PressMention,
    SourceCitation,
    SourceType,
)

AHORA = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _cita_eu(razon: str = "Acme France SAS", ident: str = "123456789") -> CorporateRecordCitation:
    return CorporateRecordCitation(
        record=RegistroCorporativo(
            jurisdiccion=JurisdiccionRegistro.fr,
            fuente="recherche-entreprises",
            identificador_registro=ident,
            razon_social=razon,
            estado="active",
        ),
        source=SourceCitation(
            source_type=SourceType.eu_registry,
            source_name="recherche-entreprises",
            retrieved_at=AHORA,
            record_id=ident,
        ),
    )


def _mencion(titular: str = "Acme anuncia expansión") -> PressMention:
    return PressMention(
        headline=titular,
        publisher="Diario de Prueba",
        published_date="2026-10-01",
        summary="Resumen breve.",
        url="https://example.test/nota",
        source=SourceCitation(
            source_type=SourceType.gdelt_news, source_name="gdelt_news", retrieved_at=AHORA
        ),
    )


@pytest.fixture
def llamadas(monkeypatch):
    """Sustituye los agentes europeo y de noticias y registra con qué se llamaron."""
    registro: dict[str, list] = {"eu": [], "news": []}

    def eu(nombre, **_):
        registro["eu"].append(nombre)
        return ResultadoAgenteEuropeo(citas=[_cita_eu()])

    def news(consulta, **_):
        registro["news"].append(consulta)
        return ResultadoRecoleccionPrensa(mentions=[_mencion()])

    monkeypatch.setattr("dossier.eu_registry.agent.run_eu_registry_agent", eu)
    monkeypatch.setattr("dossier.news.agent.collect_press_mentions", news)
    return registro


# --- Nodo europeo ------------------------------------------------------------


def test_nodo_europeo_con_alcance_dual_consulta_y_resume_registros(llamadas):
    salida = grafo._node_agent_corporate_eu(
        {"jurisdiction_scope": "dual", "empresa_objetivo": "Acme"}
    )

    assert llamadas["eu"] == ["Acme"]
    assert "Acme France SAS" in salida["eu_corporate_context"]
    assert "123456789" in salida["eu_corporate_context"]
    assert salida["agents_succeeded"] == ["agent_corporate_eu"]


@pytest.mark.parametrize("alcance", ["uk_only", "us_only"])
def test_nodo_europeo_se_omite_si_el_usuario_eligio_registro_uk_o_us(llamadas, alcance):
    salida = grafo._node_agent_corporate_eu(
        {"jurisdiction_scope": alcance, "empresa_objetivo": "Acme"}
    )

    assert llamadas["eu"] == []
    assert salida["agents_skipped"] == ["agent_corporate_eu"]
    assert "agents_failed" not in salida and "agents_succeeded" not in salida


def test_nodo_europeo_sin_empresa_objetivo_se_omite(llamadas):
    salida = grafo._node_agent_corporate_eu({"jurisdiction_scope": "dual"})

    assert llamadas["eu"] == []
    assert salida["agents_skipped"] == ["agent_corporate_eu"]


def test_nodo_europeo_falla_si_todos_los_paises_fallan_sin_resultados(monkeypatch):
    monkeypatch.setattr(
        "dossier.eu_registry.agent.run_eu_registry_agent",
        lambda nombre, **_: ResultadoAgenteEuropeo(errores={"fr": "caído", "de": "caído"}),
    )

    salida = grafo._node_agent_corporate_eu(
        {"jurisdiction_scope": "dual", "empresa_objetivo": "Acme"}
    )

    assert salida["agents_failed"] == ["agent_corporate_eu"]


def test_nodo_europeo_con_fallo_parcial_sigue_y_lo_indica(monkeypatch):
    monkeypatch.setattr(
        "dossier.eu_registry.agent.run_eu_registry_agent",
        lambda nombre, **_: ResultadoAgenteEuropeo(citas=[_cita_eu()], errores={"de": "caído"}),
    )

    salida = grafo._node_agent_corporate_eu(
        {"jurisdiction_scope": "dual", "empresa_objetivo": "Acme"}
    )

    assert salida["agents_succeeded"] == ["agent_corporate_eu"]
    assert "Acme France SAS" in salida["eu_corporate_context"]


def test_nodo_europeo_excepcion_inesperada_se_registra_como_fallo(monkeypatch):
    def explota(nombre, **_):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr("dossier.eu_registry.agent.run_eu_registry_agent", explota)

    salida = grafo._node_agent_corporate_eu(
        {"jurisdiction_scope": "dual", "empresa_objetivo": "Acme"}
    )

    assert salida["agents_failed"] == ["agent_corporate_eu"]


def test_nodo_europeo_descarta_homonimos_que_no_contienen_el_nombre_buscado(monkeypatch):
    """Probado contra el registro francés real (2026-10-05): buscar «Danone» devolvía
    empresarios individuales como «OLIVIA DANON», personas sin relación con la empresa."""
    monkeypatch.setattr(
        "dossier.eu_registry.agent.run_eu_registry_agent",
        lambda nombre, **_: ResultadoAgenteEuropeo(
            citas=[
                _cita_eu("DANONE", "552032534"),
                _cita_eu("DANONE PRODUITS FRAIS FRANCE", "672039971"),
                _cita_eu("OLIVIA DANON", "531722742"),
                _cita_eu("Société Générale", "552120222"),
            ]
        ),
    )

    salida = grafo._node_agent_corporate_eu(
        {"jurisdiction_scope": "dual", "empresa_objetivo": "Danone"}
    )

    contexto = salida["eu_corporate_context"]
    assert "552032534" in contexto and "672039971" in contexto
    assert "OLIVIA DANON" not in contexto
    assert "Société Générale" not in contexto


def test_filtro_de_coincidencia_ignora_mayusculas_y_tildes(monkeypatch):
    monkeypatch.setattr(
        "dossier.eu_registry.agent.run_eu_registry_agent",
        lambda nombre, **_: ResultadoAgenteEuropeo(citas=[_cita_eu("SOCIETE GENERALE", "552120222")]),
    )

    salida = grafo._node_agent_corporate_eu(
        {"jurisdiction_scope": "dual", "empresa_objetivo": "Société Générale"}
    )

    assert "552120222" in salida["eu_corporate_context"]


# --- Nodo de noticias --------------------------------------------------------


@pytest.mark.parametrize("alcance", ["dual", "uk_only", "us_only", "eu_only"])
def test_nodo_noticias_corre_en_cualquier_alcance_con_empresa(llamadas, alcance):
    salida = grafo._node_agent_news({"jurisdiction_scope": alcance, "empresa_objetivo": "Acme"})

    assert llamadas["news"] == ["Acme"]
    assert "Acme anuncia expansión" in salida["news_context"]
    assert "https://example.test/nota" in salida["news_context"]
    assert salida["agents_succeeded"] == ["agent_news"]


def test_nodo_noticias_sin_empresa_objetivo_se_omite(llamadas):
    salida = grafo._node_agent_news({"jurisdiction_scope": "dual"})

    assert llamadas["news"] == []
    assert salida["agents_skipped"] == ["agent_news"]


def test_nodo_noticias_falla_si_ambos_proveedores_fallan(monkeypatch):
    monkeypatch.setattr(
        "dossier.news.agent.collect_press_mentions",
        lambda consulta, **_: ResultadoRecoleccionPrensa(
            mentions=[],
            failed_providers=[
                FalloProveedor(provider="gdelt_news", error="caído"),
                FalloProveedor(provider="news_api", error="caído"),
            ],
        ),
    )

    salida = grafo._node_agent_news({"jurisdiction_scope": "dual", "empresa_objetivo": "Acme"})

    assert salida["agents_failed"] == ["agent_news"]


def test_nodo_noticias_sin_menciones_no_es_un_fallo(monkeypatch):
    monkeypatch.setattr(
        "dossier.news.agent.collect_press_mentions",
        lambda consulta, **_: ResultadoRecoleccionPrensa(mentions=[]),
    )

    salida = grafo._node_agent_news({"jurisdiction_scope": "dual", "empresa_objetivo": "Acme"})

    assert salida["agents_succeeded"] == ["agent_news"]


# --- Alcance eu_only en UK y USA ---------------------------------------------


@pytest.mark.parametrize(
    ("nodo", "nombre", "builder"),
    [
        ("_node_agent_corporate_uk", "agent_corporate_uk", "build_uk_corporate_context_markdown"),
        ("_node_agent_corporate_usa", "agent_corporate_usa", "build_us_corporate_context_markdown"),
    ],
)
def test_con_alcance_eu_only_uk_y_usa_se_omiten_sin_consultar(monkeypatch, nodo, nombre, builder):
    def no_debe_llamarse(*_a, **_k):
        raise AssertionError("no debe consultarse fuera de alcance")

    monkeypatch.setattr(f"dossier.services.corporate_registry_context.{builder}", no_debe_llamarse)

    salida = getattr(grafo, nodo)({"jurisdiction_scope": "eu_only", "participantes": "Acme"})

    assert salida["agents_skipped"] == [nombre]
