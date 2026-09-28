"""Pruebas de estrés — S4.9: telemetría de agentes fallidos bajo carga.

Ver docs/dev/testing-policy.md §4. La pregunta central de esta tarea: con muchos
grafos corriendo en paralelo (cada uno con una mezcla distinta de agentes que
fallan), ¿el ``agents_failed`` de una invocación termina mezclado con el de otra?
El reducer ``operator.add`` de LangGraph vive en el canal de estado de *cada*
invocación de ``app.invoke()``: si algo quedara compartido a nivel de módulo
(una lista mutable por defecto, un ``StateGraph`` cacheado con estado), esto lo
mostraría como una carrera intermitente en vez de un fallo determinista.
"""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor

from dossier.graphs.corporate_dossier_graph import run_corporate_dossier_langgraph_detailed


def _instalar_agentes_deterministas(monkeypatch, *, uk_falla: bool, usa_falla: bool):
    """Cada llamada usa su propio ``monkeypatch`` de pytest-forked... salvo que aquí no
    hay fixture por hilo, así que se parchea una sola vez con funciones que deciden
    por los kwargs recibidos (no hay estado compartido entre hilos)."""
    import dossier.llm.text_generate as llm
    import dossier.services.corporate_registry_context as ctx

    def _uk(participantes: str) -> str:
        if "UK_FALLA" in participantes:
            raise RuntimeError("Companies House caído")
        return "## UK\n\nok\n"

    def _usa(participantes: str) -> str:
        if "USA_FALLA" in participantes:
            raise TimeoutError("SEC EDGAR no respondió")
        return "## USA\n\nok\n"

    monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", _uk)
    monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", _usa)
    monkeypatch.setattr(
        llm, "generate_text_with_llm", lambda user, system_instruction=None: "# Dossier\n\nOK"
    )


# --------------------------------------------------------------------------
# Concurrencia: muchos grafos a la vez, cada uno con su propia mezcla de fallos.
# --------------------------------------------------------------------------

def test_concurrencia_muchos_grafos_no_mezclan_agents_failed_entre_si(monkeypatch):
    _instalar_agentes_deterministas(monkeypatch, uk_falla=False, usa_falla=False)

    combinaciones = [
        (uk, usa)
        for uk in (True, False)
        for usa in (True, False)
    ] * 10  # 40 invocaciones, 10 de cada combinación
    random.shuffle(combinaciones)

    def _invocar(combo):
        uk_falla, usa_falla = combo
        participantes = " ".join(
            filter(None, ["Acme Corp", "UK_FALLA" if uk_falla else "", "USA_FALLA" if usa_falla else ""])
        )
        resultado = run_corporate_dossier_langgraph_detailed(
            tema_reunion="Reunión", participantes=participantes, jurisdiction_scope="dual"
        )
        esperado_failed = set()
        if uk_falla:
            esperado_failed.add("agent_corporate_uk")
        if usa_falla:
            esperado_failed.add("agent_corporate_usa")
        return set(resultado.agents_failed) == esperado_failed

    with ThreadPoolExecutor(max_workers=10) as pool:
        resultados = list(pool.map(_invocar, combinaciones))

    assert all(resultados), "algún grafo devolvió agents_failed distinto del esperado para su combinación"


def test_concurrencia_sin_excepciones_en_paralelo(monkeypatch):
    """Ningún hilo debe morir con excepción no capturada (CA2 de S0.12)."""
    _instalar_agentes_deterministas(monkeypatch, uk_falla=False, usa_falla=False)
    errores: list[BaseException] = []

    def _trabajo(i):
        try:
            participantes = "Acme Corp UK_FALLA" if i % 2 == 0 else "Acme Corp USA_FALLA"
            run_corporate_dossier_langgraph_detailed(
                tema_reunion="Reunión", participantes=participantes, jurisdiction_scope="dual"
            )
        except BaseException as exc:
            errores.append(exc)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(_trabajo, range(60)))

    assert not errores, f"{len(errores)} hilo(s) fallaron: {errores[:3]}"


# --------------------------------------------------------------------------
# Volumen: muchas invocaciones secuenciales no deben degradarse.
# --------------------------------------------------------------------------

def test_volumen_cien_invocaciones_secuenciales_con_un_agente_caido(monkeypatch):
    _instalar_agentes_deterministas(monkeypatch, uk_falla=False, usa_falla=False)

    inicio = time.perf_counter()
    for _ in range(100):
        resultado = run_corporate_dossier_langgraph_detailed(
            tema_reunion="Reunión", participantes="Acme Corp UK_FALLA", jurisdiction_scope="dual"
        )
        assert resultado.agents_failed == ["agent_corporate_uk"]
    transcurrido = time.perf_counter() - inicio

    assert transcurrido < 10.0, f"100 invocaciones tardaron {transcurrido:.2f}s"
