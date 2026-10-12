"""Pruebas de estrés - S2.2: cuatro agentes en paralelo en el grafo corporativo.

Ver docs/dev/testing-policy.md §4: volumen, concurrencia, degradación.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from dossier.eu_registry.agent import ResultadoAgenteEuropeo
from dossier.graphs.corporate_dossier_graph import run_corporate_dossier_langgraph_detailed
from dossier.news.agent import ResultadoRecoleccionPrensa
from dossier.schemas.dossier_executive_payload import PressMention, SourceCitation, SourceType

DEMORA = 0.3


def _mencion(i: int, empresa: str) -> PressMention:
    return PressMention(
        headline=f"{empresa} titular {i}",
        publisher="Diario",
        summary="Resumen.",
        url=f"https://example.test/{empresa}/{i}",
        source=SourceCitation(
            source_type=SourceType.gdelt_news,
            source_name="gdelt_news",
            retrieved_at=datetime(2026, 10, 5, tzinfo=UTC),
        ),
    )


@pytest.fixture
def agentes_lentos(monkeypatch):
    """Cada agente tarda DEMORA; las noticias devuelven contenido propio de cada empresa."""
    prompts: dict[str, str] = {}

    def lento(texto):
        def _f(*_a, **_k):
            time.sleep(DEMORA)
            return texto

        return _f

    monkeypatch.setattr(
        "dossier.services.corporate_registry_context.build_uk_corporate_context_markdown",
        lento("UK"),
    )
    monkeypatch.setattr(
        "dossier.services.corporate_registry_context.build_us_corporate_context_markdown",
        lento("US"),
    )

    def eu(nombre, **_):
        time.sleep(DEMORA)
        return ResultadoAgenteEuropeo()

    def news(consulta, **_):
        time.sleep(DEMORA)
        return ResultadoRecoleccionPrensa(mentions=[_mencion(i, consulta) for i in range(200)])

    monkeypatch.setattr("dossier.eu_registry.agent.run_eu_registry_agent", eu)
    monkeypatch.setattr("dossier.news.agent.collect_press_mentions", news)

    def llm(prompt, **_):
        empresa = next(p for p in prompt.split() if p.startswith("Empresa-"))
        prompts[empresa] = prompt
        return f"# {empresa}"

    monkeypatch.setattr("dossier.llm.text_generate.generate_text_with_llm", llm)
    return prompts


def test_degradacion_los_cuatro_agentes_lentos_corren_en_paralelo(agentes_lentos):
    inicio = time.perf_counter()
    run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión Empresa-unica",
        participantes="Empresa-unica",
        jurisdiction_scope="dual",
        empresa_objetivo="Empresa-unica",
    )
    transcurrido = time.perf_counter() - inicio

    assert transcurrido < DEMORA * 3, f"cuatro agentes de {DEMORA}s tardaron {transcurrido:.2f}s"


def test_volumen_doscientas_menciones_no_inflan_el_prompt_sin_limite(agentes_lentos):
    run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión Empresa-volumen",
        participantes="Empresa-volumen",
        jurisdiction_scope="dual",
        empresa_objetivo="Empresa-volumen",
    )

    prompt = agentes_lentos["Empresa-volumen"]
    assert "Empresa-volumen titular 0" in prompt
    assert "Empresa-volumen titular 199" not in prompt
    assert len(prompt) < 30_000


def test_concurrencia_grafos_paralelos_no_mezclan_empresas(agentes_lentos):
    empresas = [f"Empresa-{i}" for i in range(12)]

    def correr(empresa):
        return run_corporate_dossier_langgraph_detailed(
            tema_reunion=f"Reunión {empresa}",
            participantes=empresa,
            jurisdiction_scope="dual",
            empresa_objetivo=empresa,
        ).markdown

    with ThreadPoolExecutor(max_workers=6) as pool:
        salidas = list(pool.map(correr, empresas))

    assert salidas == [f"# {e}" for e in empresas]
    for empresa in empresas:
        otras = [e for e in empresas if e != empresa]
        prompt = agentes_lentos[empresa]
        assert f"{empresa} titular 0" in prompt
        assert not any(f"{o} titular" in prompt for o in otras)
