"""Callback del inicio de sesión con Google: qué se rechaza antes de abrir sesión (UX-AUTH-01)."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient

from dossier.api import google_login_routes as gl
from dossier.api.app import app
from dossier.api.auth_routes import get_db_if_configured
from dossier.security.jwt_tokens import create_google_oauth_state, decode_access_token

ERROR = "https://front.test/login?error=google"
NONCE = "nonce-del-navegador"


class Llamadas:
    def __init__(self):
        self.canje = 0
        self.resolver = 0


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://front.test")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-g.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secreto-g")
    llamadas = Llamadas()
    perfil = {"sub": "g-123", "email": "ana@example.test", "email_verified": True, "name": "Ana"}

    def _canjear(code, redirect_uri):
        llamadas.canje += 1
        return {"access_token": "tok-google"}

    def _resolver(db, datos):
        llamadas.resolver += 1
        return (
            SimpleNamespace(id=uuid.uuid4(), email=datos["email"]),
            SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(role="admin"),
        )

    monkeypatch.setattr(gl, "_canjear_codigo", _canjear)
    monkeypatch.setattr(gl, "_perfil_google", lambda token: perfil)
    monkeypatch.setattr(gl, "resolver_usuario_google", _resolver)
    app.dependency_overrides[get_db_if_configured] = lambda: iter([object()])
    yield SimpleNamespace(llamadas=llamadas, perfil=perfil)
    app.dependency_overrides.pop(get_db_if_configured, None)


def _cliente(nonce: str | None = NONCE) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    if nonce is not None:
        c.cookies.set(gl.COOKIE_NONCE, nonce)
    return c


def _state(**cambios) -> str:
    payload = {
        "purpose": "google_login",
        "nonce": NONCE,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        **cambios,
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


def test_flujo_valido_entrega_el_token_en_el_fragmento(entorno):
    r = _cliente().get("/auth/google/callback", params={"code": "c", "state": _state()})

    assert r.status_code == 302
    destino = r.headers["location"]
    assert destino.startswith("https://front.test/auth/google#token=")
    assert "?" not in destino, "el token no debe viajar en la query"
    token = destino.split("#token=", 1)[1]
    assert decode_access_token(token)["email"] == "ana@example.test"


def test_sin_cookie_del_navegador_no_canjea_el_codigo(entorno):
    r = _cliente(nonce=None).get("/auth/google/callback", params={"code": "c", "state": _state()})

    assert r.headers["location"] == ERROR
    assert entorno.llamadas.canje == 0


def test_cookie_de_otro_navegador_no_sirve(entorno):
    r = _cliente(nonce="otro").get("/auth/google/callback", params={"code": "c", "state": _state()})

    assert r.headers["location"] == ERROR
    assert entorno.llamadas.canje == 0


def test_state_firmado_con_otra_clave_se_rechaza(entorno):
    falso = jwt.encode(
        {"purpose": "google_login", "nonce": NONCE, "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "otra-clave-distinta-de-al-menos-32-caracteres",
        algorithm="HS256",
    )
    r = _cliente().get("/auth/google/callback", params={"code": "c", "state": falso})

    assert r.headers["location"] == ERROR
    assert entorno.llamadas.canje == 0


def test_state_caducado_se_rechaza(entorno):
    r = _cliente().get(
        "/auth/google/callback",
        params={"code": "c", "state": _state(exp=datetime.now(UTC) - timedelta(seconds=1))},
    )
    assert r.headers["location"] == ERROR


def test_state_del_calendario_no_abre_sesion(entorno):
    """El ``state`` del flujo de calendario está firmado con la misma clave, pero es otro propósito."""
    calendario = create_google_oauth_state(user_id=str(uuid.uuid4()), organization_id=str(uuid.uuid4()))
    r = _cliente().get("/auth/google/callback", params={"code": "c", "state": calendario})

    assert r.headers["location"] == ERROR
    assert entorno.llamadas.canje == 0


def test_correo_no_verificado_por_google_no_abre_sesion(entorno):
    entorno.perfil["email_verified"] = False
    r = _cliente().get("/auth/google/callback", params={"code": "c", "state": _state()})

    assert r.headers["location"] == ERROR
    assert entorno.llamadas.resolver == 0


def test_error_devuelto_por_google_vuelve_al_login(entorno):
    r = _cliente().get(
        "/auth/google/callback", params={"error": "access_denied", "state": _state()}
    )
    assert r.headers["location"] == ERROR
    assert entorno.llamadas.canje == 0


def test_la_cookie_se_borra_tras_el_callback(entorno):
    r = _cliente().get("/auth/google/callback", params={"code": "c", "state": _state()})
    cabecera = r.headers.get("set-cookie", "")
    assert gl.COOKIE_NONCE in cabecera
    assert "max-age=0" in cabecera.lower() or "expires=thu, 01 jan 1970" in cabecera.lower()
