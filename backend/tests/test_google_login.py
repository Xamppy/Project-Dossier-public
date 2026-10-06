"""Inicio de sesión con Google: la redirección inicial (UX-AUTH-01)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi.testclient import TestClient

from dossier.api import google_login_routes as gl
from dossier.api.app import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://front.test")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-g.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secreto-g")
    monkeypatch.delenv("GOOGLE_LOGIN_REDIRECT_URI", raising=False)
    return TestClient(app, follow_redirects=False)


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_inicio_redirige_a_google_con_alcances_de_identidad(cliente):
    r = cliente.get("/auth/google/login")

    assert r.status_code == 302
    destino = r.headers["location"]
    assert destino.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    q = _query(destino)
    assert q["client_id"] == "id-g.apps.googleusercontent.com"
    assert q["scope"] == "openid email profile"
    assert q["response_type"] == "code"
    assert q["prompt"] == "select_account"


def test_inicio_ata_el_state_al_navegador_con_una_cookie(cliente):
    r = cliente.get("/auth/google/login")

    state = _query(r.headers["location"])["state"]
    nonce = jwt.decode(state, options={"verify_signature": False})["nonce"]
    assert r.cookies.get(gl.COOKIE_NONCE) == nonce
    cabecera = r.headers["set-cookie"].lower()
    assert "httponly" in cabecera
    assert "samesite=lax" in cabecera


def test_redirect_uri_por_defecto_es_la_propia_ruta_de_callback(cliente):
    r = cliente.get("/auth/google/login")
    assert _query(r.headers["location"])["redirect_uri"] == "http://testserver/auth/google/callback"


def test_redirect_uri_se_puede_fijar_por_entorno(cliente, monkeypatch):
    monkeypatch.setenv("GOOGLE_LOGIN_REDIRECT_URI", "https://dominio.test/api/auth/google/callback")
    r = cliente.get("/auth/google/login")
    assert _query(r.headers["location"])["redirect_uri"] == "https://dominio.test/api/auth/google/callback"


def test_sin_oauth_configurado_vuelve_al_login_con_error(cliente, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    r = cliente.get("/auth/google/login")

    assert r.status_code == 302
    assert r.headers["location"] == "https://front.test/login?error=google"
