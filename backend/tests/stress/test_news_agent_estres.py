"""Pruebas de estres - S3.2: agente de noticias.

Ver docs/dev/testing-policy.md §4: volumen, concurrencia, degradacion.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import dossier.news.agent as agent
from dossier.news.agent import collect_press_mentions
from dossier.news.client import ProveedorNoticiasError


def _articulos_gdelt(cantidad: int, duplicados_por: int) -> list[dict]:
    """`cantidad` articulos, repartidos en grupos de `duplicados_por` con la misma URL."""
    articulos = []
    for i in range(cantidad):
        grupo = i // duplicados_por
        articulos.append(
            {
                "url": f"https://medio.ejemplo.com/nota-{grupo}",
                "title": f"Nota numero {grupo}",
                "domain": "medio.ejemplo.com",
                "seendate": "20260910",
            }
        )
    return articulos


# --------------------------------------------------------------------------
# Volumen: cientos de articulos con muchos duplicados
# --------------------------------------------------------------------------

def test_volumen_cientos_de_articulos_con_duplicados_se_procesan_rapido(monkeypatch):
    monkeypatch.setattr(agent, "search_gdelt_articles", lambda q, *, limite=10: _articulos_gdelt(600, 6))
    monkeypatch.setattr(agent, "search_newsapi_articles", lambda q, *, limite=10: [])

    inicio = time.perf_counter()
    resultado = collect_press_mentions("Ana Perez")
    transcurrido = time.perf_counter() - inicio

    assert len(resultado.mentions) == 100, "600 articulos en grupos de 6 duplicados deben colapsar a 100"
    assert transcurrido < 2.0, f"tardo {transcurrido:.2f}s procesando 600 articulos"


# --------------------------------------------------------------------------
# Concurrencia: muchas consultas del agente a la vez
# --------------------------------------------------------------------------

def test_concurrencia_muchas_consultas_simultaneas_sin_excepciones(monkeypatch):
    monkeypatch.setattr(agent, "search_gdelt_articles", lambda q, *, limite=10: _articulos_gdelt(10, 2))
    monkeypatch.setattr(agent, "search_newsapi_articles", lambda q, *, limite=10: [])

    errores: list[BaseException] = []
    resultados = []

    def trabajo(i):
        try:
            resultados.append(collect_press_mentions(f"Sujeto {i}"))
        except BaseException as exc:
            errores.append(exc)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(trabajo, range(50)))

    assert not errores, f"{len(errores)} consulta(s) fallaron: {errores[:3]}"
    assert len(resultados) == 50
    assert all(len(r.mentions) == 5 for r in resultados)


# --------------------------------------------------------------------------
# Degradacion: un proveedor lento o caido
# --------------------------------------------------------------------------

def test_degradacion_proveedor_lento_no_bloquea_mas_alla_del_timeout(monkeypatch):
    def newsapi_lenta(q, *, limite=10):
        time.sleep(2.0)
        return []

    monkeypatch.setattr(agent, "search_gdelt_articles", lambda q, *, limite=10: [
        {"url": "https://medio.ejemplo.com/nota", "title": "Nota rapida", "domain": "medio.ejemplo.com"}
    ])
    monkeypatch.setattr(agent, "search_newsapi_articles", newsapi_lenta)

    inicio = time.perf_counter()
    resultado = collect_press_mentions("Ana Perez", timeout_seg=0.1)
    transcurrido = time.perf_counter() - inicio

    assert transcurrido < 1.0, f"el proveedor lento bloqueo la respuesta ({transcurrido:.2f}s)"
    assert len(resultado.mentions) == 1
    assert [f.provider for f in resultado.failed_providers] == ["news_api"]


def test_degradacion_ambos_proveedores_caidos_no_rompe_el_agente(monkeypatch):
    def caido(q, *, limite=10):
        raise ProveedorNoticiasError("proveedor caido")

    monkeypatch.setattr(agent, "search_gdelt_articles", caido)
    monkeypatch.setattr(agent, "search_newsapi_articles", caido)

    resultado = collect_press_mentions("Ana Perez")

    assert resultado.mentions == []
    assert len(resultado.failed_providers) == 2
