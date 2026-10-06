"""Las rutas públicas de oauth-config exponen `configured` por HTTP (sin sesión)."""
from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

import dossier.api.app  # noqa: F401  (registra el módulo en sys.modules)

# ``dossier.api.app`` también es el nombre de la instancia FastAPI: se toma el módulo.
api = sys.modules["dossier.api.app"]


@pytest.fixture
def cliente():
    return TestClient(api.app)


def test_microsoft_sin_configurar_responde_configured_false(cliente, monkeypatch):
    monkeypatch.setattr(api, "CLIENT_ID", None)
    respuesta = cliente.get("/integrations/microsoft/oauth-config")
    assert respuesta.status_code == 200
    assert respuesta.json()["configured"] is False


def test_google_configurado_responde_configured_true(cliente, monkeypatch):
    monkeypatch.setattr(api, "GOOGLE_CLIENT_ID", "id-g.apps.googleusercontent.com")
    monkeypatch.setattr(api, "GOOGLE_CLIENT_SECRET", "secreto-g")
    monkeypatch.setattr(api, "GOOGLE_REDIRECT_URI", "https://x.test/api/callback-google")
    respuesta = cliente.get("/integrations/google/oauth-config")
    assert respuesta.status_code == 200
    assert respuesta.json()["configured"] is True
