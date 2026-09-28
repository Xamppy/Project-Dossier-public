"""Estres - S2.1: agente europeo. Ver docs/dev/testing-policy.md §4.

Volumen (muchos resultados y duplicados), concurrencia (paises en paralelo)
y degradacion (un pais lento o caido no bloquea ni tumba a los demas).
"""
from __future__ import annotations

import time

from dossier.eu_registry import agent
from dossier.eu_registry.client import RegistroEuropeoError

# --------------------------------------------------------------------------
# Volumen
# --------------------------------------------------------------------------


def test_volumen_muchos_resultados_y_duplicados_no_se_degrada(monkeypatch):
    """500 filas francesas con solo 20 SIREN distintos deben deduplicarse rapido."""
    filas = [{"siren": str(i % 20), "nom_complet": f"Empresa {i % 20}"} for i in range(500)]
    monkeypatch.setattr(agent, "search_france_companies", lambda q, *, limite=5: filas)
    monkeypatch.setattr(agent, "search_germany_companies", lambda q, *, limite=5: [])

    inicio = time.perf_counter()
    resultado = agent.run_eu_registry_agent("Empresa", jurisdicciones=["fr"])
    transcurrido = time.perf_counter() - inicio

    assert len(resultado.citas) == 20
    assert transcurrido < 1.0, f"Deduplicar 500 filas tardo {transcurrido:.2f}s"


# --------------------------------------------------------------------------
# Concurrencia
# --------------------------------------------------------------------------


def test_concurrencia_paises_se_consultan_en_paralelo_no_en_serie(monkeypatch):
    """Francia y Alemania tardando 0.3s cada una deben resolverse en ~0.3s, no ~0.6s."""

    def lenta_francia(q, *, limite=5):
        time.sleep(0.3)
        return [{"siren": "1", "nom_complet": "FR"}]

    def lenta_alemania(q, *, limite=5):
        time.sleep(0.3)
        return [{"company_number": "HRB 1", "name": "DE"}]

    monkeypatch.setattr(agent, "search_france_companies", lenta_francia)
    monkeypatch.setattr(agent, "search_germany_companies", lenta_alemania)

    inicio = time.perf_counter()
    resultado = agent.run_eu_registry_agent("Acme")
    transcurrido = time.perf_counter() - inicio

    assert len(resultado.citas) == 2
    assert transcurrido < 0.55, (
        f"Tardo {transcurrido:.2f}s; se esperaba paralelismo (~0.3s), no la suma (~0.6s)"
    )


def test_concurrencia_diez_consultas_simultaneas_sin_excepciones(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(
        agent, "search_france_companies", lambda q, *, limite=5: [{"siren": "1", "nom_complet": "FR"}]
    )
    monkeypatch.setattr(
        agent, "search_germany_companies", lambda q, *, limite=5: [{"company_number": "HRB 1", "name": "DE"}]
    )

    errores: list[BaseException] = []

    def trabajo(_):
        try:
            resultado = agent.run_eu_registry_agent("Acme")
            assert len(resultado.citas) == 2
        except BaseException as exc:
            errores.append(exc)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(trabajo, range(10)))

    assert not errores, f"{len(errores)} llamada(s) fallaron: {errores[:3]}"


# --------------------------------------------------------------------------
# Degradacion
# --------------------------------------------------------------------------


def test_degradacion_un_pais_lento_no_bloquea_al_resultado_del_otro(monkeypatch):
    """Alemania cae de inmediato; Francia tarda: el resultado de Francia igual llega."""

    def rota_alemania(q, *, limite=5):
        raise RegistroEuropeoError("Handelsregister caido")

    def lenta_francia(q, *, limite=5):
        time.sleep(0.2)
        return [{"siren": "1", "nom_complet": "FR"}]

    monkeypatch.setattr(agent, "search_france_companies", lenta_francia)
    monkeypatch.setattr(agent, "search_germany_companies", rota_alemania)

    resultado = agent.run_eu_registry_agent("Acme")

    assert resultado.errores == {"de": "Handelsregister caido"}
    assert len(resultado.citas) == 1
    assert resultado.citas[0].record.jurisdiccion.value == "fr"


def test_degradacion_ambos_paises_caidos_devuelve_solo_errores(monkeypatch):
    def rota(*args, **kwargs):
        raise RegistroEuropeoError("caido")

    monkeypatch.setattr(agent, "search_france_companies", rota)
    monkeypatch.setattr(agent, "search_germany_companies", rota)

    resultado = agent.run_eu_registry_agent("Acme")

    assert resultado.citas == []
    assert set(resultado.errores) == {"fr", "de"}
