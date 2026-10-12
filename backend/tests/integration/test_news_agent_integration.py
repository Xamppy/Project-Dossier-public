"""Tests de integracion - S3.2: agente de noticias sobre el cliente HTTP real (mockeado).

A diferencia de test_news_agent.py (unitario, monkeypatchea las funciones del
cliente), aqui se monkeypatchea `requests.get` para cruzar la capa del cliente
HTTP (S3.1) y la del agente (S3.2) juntas, como en produccion.
"""
from __future__ import annotations

import dossier.news.client as client
from dossier.news.agent import collect_press_mentions
from dossier.schemas.dossier_executive_payload import SourceType


def test_agente_sobre_cliente_http_real_con_ambos_proveedores(monkeypatch, respuesta_fija):
    monkeypatch.setenv("NEWS_API_KEY", "clave-de-prueba")

    def fake_get(url, params=None, headers=None, timeout=None):
        if url == client.GDELT_SEARCH_URL:
            return respuesta_fija(
                {"articles": [{"url": "https://gdelt.ejemplo.com/nota", "title": "Nota GDELT",
                               "domain": "gdelt.ejemplo.com", "seendate": "20260910"}]}
            )
        assert url == client.NEWSAPI_SEARCH_URL
        return respuesta_fija(
            {"articles": [{"url": "https://newsapi.ejemplo.com/nota", "title": "Nota NewsAPI",
                            "source": {"name": "NewsAPI Medio"}, "description": "desc",
                            "publishedAt": "2026-09-10T10:00:00Z"}]}
        )

    monkeypatch.setattr(client.requests, "get", fake_get)

    resultado = collect_press_mentions('"Ana Perez" AND "Acme"')

    assert not resultado.failed_providers
    assert len(resultado.mentions) == 2
    assert {m.source.source_type for m in resultado.mentions} == {SourceType.gdelt_news, SourceType.news_api}


def test_agente_reporta_fallo_http_de_un_proveedor_y_entrega_el_otro(monkeypatch, respuesta_fija):
    monkeypatch.setenv("NEWS_API_KEY", "clave-de-prueba")

    def fake_get(url, params=None, headers=None, timeout=None):
        if url == client.GDELT_SEARCH_URL:
            return respuesta_fija({"error": "boom"}, status=500)
        return respuesta_fija(
            {"articles": [{"url": "https://newsapi.ejemplo.com/nota", "title": "Nota NewsAPI",
                            "source": {"name": "NewsAPI Medio"}, "description": "desc"}]}
        )

    monkeypatch.setattr(client.requests, "get", fake_get)

    resultado = collect_press_mentions("Ana Perez")

    assert len(resultado.mentions) == 1
    assert len(resultado.failed_providers) == 1
    assert resultado.failed_providers[0].provider == "gdelt_news"


def test_agente_sin_news_api_key_reporta_ese_proveedor_como_fallido(monkeypatch, respuesta_fija):
    monkeypatch.delenv("NEWS_API_KEY", raising=False)

    def fake_get(url, params=None, timeout=None, headers=None):
        assert url == client.GDELT_SEARCH_URL
        return respuesta_fija(
            {"articles": [{"url": "https://gdelt.ejemplo.com/nota", "title": "Nota GDELT",
                            "domain": "gdelt.ejemplo.com"}]}
        )

    monkeypatch.setattr(client.requests, "get", fake_get)

    resultado = collect_press_mentions("Ana Perez")

    assert len(resultado.mentions) == 1
    assert [f.provider for f in resultado.failed_providers] == ["news_api"]
