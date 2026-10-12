"""Tests - S3.2: agente de noticias (recoleccion + deduplicacion).

Consulta GDELT y NewsAPI (client de S3.1, ya probado en test_news_client.py) y
devuelve `PressMention` deduplicados. El filtro de homonimos es S3.3; la
procedencia en base de datos, S3.4: ninguno de los dos es responsabilidad de
este modulo.
"""
from __future__ import annotations

from datetime import UTC

import dossier.news.agent as agent
from dossier.news.agent import collect_press_mentions
from dossier.news.client import ProveedorNoticiasError
from dossier.schemas.dossier_executive_payload import SourceType


def _gdelt(url="https://ejemplo.com/nota", title="Ana Perez asume cargo", domain="ejemplo.com", seendate="20260910T120000Z"):
    return {"url": url, "title": title, "domain": domain, "seendate": seendate}


def _newsapi(url="https://otromedio.com/nota", title="Ana Perez asume cargo", nombre_medio="Otro Medio",
             descripcion="Resumen de la nota", published="2026-09-10T12:00:00Z"):
    return {
        "url": url,
        "title": title,
        "source": {"id": None, "name": nombre_medio},
        "description": descripcion,
        "publishedAt": published,
    }


# --------------------------------------------------------------------------
# Caso normal
# --------------------------------------------------------------------------

def test_flujo_normal_devuelve_press_mentions_con_source_correcto(monkeypatch):
    monkeypatch.setattr(agent, "search_gdelt_articles", lambda q, *, limite=10: [_gdelt()])
    monkeypatch.setattr(agent, "search_newsapi_articles", lambda q, *, limite=10: [_newsapi(title="Otra nota distinta")])

    resultado = collect_press_mentions('"Ana Perez" AND "Acme"')

    assert not resultado.failed_providers
    assert len(resultado.mentions) == 2
    tipos = {m.source.source_type for m in resultado.mentions}
    assert tipos == {SourceType.gdelt_news, SourceType.news_api}
    for m in resultado.mentions:
        assert m.summary
        assert m.headline
        assert m.url
        assert m.source.retrieved_at.tzinfo is not None
        assert m.source.retrieved_at.astimezone(UTC) == m.source.retrieved_at


# --------------------------------------------------------------------------
# Borde: articulo malformado, sin url o sin titulo
# --------------------------------------------------------------------------

def test_articulo_sin_url_o_sin_titulo_se_descarta_sin_romper(monkeypatch):
    monkeypatch.setattr(
        agent, "search_gdelt_articles",
        lambda q, *, limite=10: [_gdelt(), {"title": "Sin url"}, {"url": "https://x.com"}],
    )
    monkeypatch.setattr(agent, "search_newsapi_articles", lambda q, *, limite=10: [])

    resultado = collect_press_mentions("Ana Perez")

    assert len(resultado.mentions) == 1


# --------------------------------------------------------------------------
# Deduplicacion
# --------------------------------------------------------------------------

def test_dedup_misma_url_normalizada_entre_variantes(monkeypatch):
    variantes = [
        "https://www.ejemplo.com/nota?utm_source=twitter&utm_campaign=x",
        "http://ejemplo.com/nota/",
        "https://ejemplo.com/nota#seccion",
    ]
    monkeypatch.setattr(
        agent, "search_gdelt_articles",
        lambda q, *, limite=10: [_gdelt(url=variantes[0]), _gdelt(url=variantes[1], title="Titular distinto")],
    )
    monkeypatch.setattr(agent, "search_newsapi_articles", lambda q, *, limite=10: [_newsapi(url=variantes[2])])

    resultado = collect_press_mentions("Ana Perez")

    assert len(resultado.mentions) == 1


def test_dedup_mismo_titular_normalizado_y_mismo_medio_url_distinta(monkeypatch):
    monkeypatch.setattr(
        agent, "search_gdelt_articles",
        lambda q, *, limite=10: [_gdelt(url="https://ejemplo.com/a", title="  Ana   Perez asume CARGO ")],
    )
    monkeypatch.setattr(
        agent, "search_newsapi_articles",
        lambda q, *, limite=10: [_newsapi(url="https://ejemplo.com/b-completamente-distinta",
                                           nombre_medio="ejemplo.com", title="ana perez asume cargo")],
    )

    resultado = collect_press_mentions("Ana Perez")

    assert len(resultado.mentions) == 1


def test_no_deduplica_mismo_titular_en_medios_distintos(monkeypatch):
    monkeypatch.setattr(
        agent, "search_gdelt_articles",
        lambda q, *, limite=10: [_gdelt(url="https://medio-uno.com/a", domain="medio-uno.com")],
    )
    monkeypatch.setattr(
        agent, "search_newsapi_articles",
        lambda q, *, limite=10: [_newsapi(url="https://medio-dos.com/b", nombre_medio="medio-dos.com")],
    )

    resultado = collect_press_mentions("Ana Perez")

    assert len(resultado.mentions) == 2


# --------------------------------------------------------------------------
# Tolerancia a fallos: uno falla, el otro responde
# --------------------------------------------------------------------------

def test_un_proveedor_falla_el_otro_responde_no_propaga_excepcion(monkeypatch):
    def gdelt_falla(q, *, limite=10):
        raise ProveedorNoticiasError("boom")

    monkeypatch.setattr(agent, "search_gdelt_articles", gdelt_falla)
    monkeypatch.setattr(agent, "search_newsapi_articles", lambda q, *, limite=10: [_newsapi()])

    resultado = collect_press_mentions("Ana Perez")

    assert len(resultado.mentions) == 1
    assert len(resultado.failed_providers) == 1
    assert resultado.failed_providers[0].provider == "gdelt_news"


def test_ambos_proveedores_fallan_devuelve_vacio_sin_propagar(monkeypatch):
    def falla(q, *, limite=10):
        raise ProveedorNoticiasError("boom")

    monkeypatch.setattr(agent, "search_gdelt_articles", falla)
    monkeypatch.setattr(agent, "search_newsapi_articles", falla)

    resultado = collect_press_mentions("Ana Perez")

    assert resultado.mentions == []
    assert len(resultado.failed_providers) == 2


def test_query_context_incluye_la_consulta_original(monkeypatch):
    monkeypatch.setattr(agent, "search_gdelt_articles", lambda q, *, limite=10: [])
    monkeypatch.setattr(agent, "search_newsapi_articles", lambda q, *, limite=10: [])

    resultado = collect_press_mentions('"Ana Perez" AND "Acme"')

    assert resultado.query_context["subject_query"] == '"Ana Perez" AND "Acme"'
