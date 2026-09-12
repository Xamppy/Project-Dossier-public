"""Tests - S1.8: cliente HTTP de la fuente europea (Francia, Alemania).

Solo el cliente HTTP (fetch + parseo del JSON crudo). La normalizacion a
RegistroCorporativo (S1.9) es responsabilidad de S2.1/S2.3.
"""
from __future__ import annotations

import pytest

import dossier.eu_registry.client as client
from dossier.eu_registry.client import (
    RegistroEuropeoError,
    search_france_companies,
    search_germany_companies,
)


def test_busca_empresas_francesas_devuelve_results(monkeypatch, respuesta_fija):
    payload = {
        "results": [{"siren": "552100554", "nom_complet": "L'Oreal SA"}],
        "total_results": 1,
    }

    def fake_get(url, params=None, timeout=None):
        assert url == client.FRANCE_SEARCH_URL
        assert params["q"] == "loreal"
        return respuesta_fija(payload)

    monkeypatch.setattr(client.requests, "get", fake_get)
    assert search_france_companies("loreal") == payload["results"]


def test_busca_empresas_francesas_query_vacia_no_llama_a_la_red(monkeypatch):
    def fake_get(*args, **kwargs):
        raise AssertionError("no deberia llamar a la red con query vacia")

    monkeypatch.setattr(client.requests, "get", fake_get)
    assert search_france_companies("   ") == []


def test_busca_empresas_francesas_error_http_se_traduce(monkeypatch, respuesta_fija):
    def fake_get(*args, **kwargs):
        return respuesta_fija({"error": "boom"}, status=500)

    monkeypatch.setattr(client.requests, "get", fake_get)
    with pytest.raises(RegistroEuropeoError):
        search_france_companies("loreal")


def test_busca_empresas_francesas_respuesta_no_json_se_traduce(monkeypatch, respuesta_fija):
    r = respuesta_fija({})

    def rota():
        raise ValueError("no es JSON")

    r.json = rota

    def fake_get(*args, **kwargs):
        return r

    monkeypatch.setattr(client.requests, "get", fake_get)
    with pytest.raises(RegistroEuropeoError):
        search_france_companies("loreal")


def test_busca_empresas_alemanas_devuelve_filas(monkeypatch, respuesta_fija):
    payload = [{"name": "Beispiel GmbH", "company_number": "HRB 12345"}]

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/company.json")
        assert params["name__contains"] == "beispiel"
        return respuesta_fija(payload)

    monkeypatch.setattr(client.requests, "get", fake_get)
    assert search_germany_companies("beispiel") == payload


def test_busca_empresas_alemanas_forma_inesperada_es_error(monkeypatch, respuesta_fija):
    def fake_get(*args, **kwargs):
        return respuesta_fija({"not": "a list"})

    monkeypatch.setattr(client.requests, "get", fake_get)
    with pytest.raises(RegistroEuropeoError):
        search_germany_companies("beispiel")


def test_busca_empresas_alemanas_query_vacia_no_llama_a_la_red(monkeypatch):
    def fake_get(*args, **kwargs):
        raise AssertionError("no deberia llamar a la red con query vacia")

    monkeypatch.setattr(client.requests, "get", fake_get)
    assert search_germany_companies("") == []
