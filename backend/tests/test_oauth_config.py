"""`configured` en /integrations/{google,microsoft}/oauth-config.

El dashboard oculta la conexión de un calendario cuyo OAuth no está configurado. Debe
exigir lo mismo que exige /start (ID, secreto y URI de redirección): `client_id_configured`
solo miraba el ID, y con él un proveedor a medio configurar se mostraba y fallaba al usarlo.
"""
from __future__ import annotations

import sys

import pytest

import dossier.api.app  # noqa: F401  (registra el módulo en sys.modules)

# ``dossier.api.app`` también es el nombre de la instancia FastAPI: se toma el módulo.
api = sys.modules["dossier.api.app"]

COMPLETO_MS = {"CLIENT_ID": "id-ms", "CLIENT_SECRET": "secreto-ms", "REDIRECT_URI": "https://x.test/api/callback"}
COMPLETO_G = {
    "GOOGLE_CLIENT_ID": "id-g.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "secreto-g",
    "GOOGLE_REDIRECT_URI": "https://x.test/api/callback-google",
}


def _fijar(monkeypatch, valores: dict) -> None:
    for nombre, valor in valores.items():
        monkeypatch.setattr(api, nombre, valor)


def test_microsoft_completo_esta_configurado(monkeypatch):
    _fijar(monkeypatch, COMPLETO_MS)
    assert api.integrations_microsoft_oauth_config()["configured"] is True


def test_google_completo_esta_configurado(monkeypatch):
    _fijar(monkeypatch, COMPLETO_G)
    assert api.integrations_google_oauth_config()["configured"] is True


@pytest.mark.parametrize("falta", list(COMPLETO_MS))
def test_microsoft_a_medias_no_esta_configurado(monkeypatch, falta):
    _fijar(monkeypatch, {**COMPLETO_MS, falta: None})
    assert api.integrations_microsoft_oauth_config()["configured"] is False


@pytest.mark.parametrize("falta", list(COMPLETO_G))
def test_google_a_medias_no_esta_configurado(monkeypatch, falta):
    _fijar(monkeypatch, {**COMPLETO_G, falta: None})
    assert api.integrations_google_oauth_config()["configured"] is False
