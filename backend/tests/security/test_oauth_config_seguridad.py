"""oauth-config es público: nunca debe devolver el secreto del cliente OAuth."""
from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

import dossier.api.app  # noqa: F401  (registra el módulo en sys.modules)

# ``dossier.api.app`` también es el nombre de la instancia FastAPI: se toma el módulo.
api = sys.modules["dossier.api.app"]

SECRETO = "secreto-que-no-debe-salir-0123456789"


@pytest.mark.parametrize(
    ("ruta", "valores"),
    [
        (
            "/integrations/microsoft/oauth-config",
            {"CLIENT_ID": "id-ms", "CLIENT_SECRET": SECRETO, "REDIRECT_URI": "https://x.test/api/callback"},
        ),
        (
            "/integrations/google/oauth-config",
            {
                "GOOGLE_CLIENT_ID": "id-g.apps.googleusercontent.com",
                "GOOGLE_CLIENT_SECRET": SECRETO,
                "GOOGLE_REDIRECT_URI": "https://x.test/api/callback-google",
            },
        ),
    ],
)
def test_oauth_config_no_expone_el_secreto(monkeypatch, ruta, valores):
    for nombre, valor in valores.items():
        monkeypatch.setattr(api, nombre, valor)

    respuesta = TestClient(api.app).get(ruta)

    assert respuesta.status_code == 200
    assert SECRETO not in respuesta.text
