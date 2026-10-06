"""Inicio de sesión con Google contra Postgres: alta, vinculación y vuelta (UX-AUTH-01)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from alembic import command
from dossier.api import google_login_routes as gl
from dossier.api.app import app
from dossier.api.auth_routes import get_db_if_configured
from dossier.db.models import OAuthAccount, Organization, OrgMembership, User
from dossier.security import hash_password
from dossier.security.jwt_tokens import decode_access_token


@pytest.fixture
def sesion(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with Session(pg_vacia) as s:
        yield s


def _perfil(**cambios) -> dict:
    return {"sub": "g-1", "email": "ana@example.test", "email_verified": True, "name": "Ana Prueba", **cambios}


def test_correo_nuevo_crea_cuenta_con_espacio_personal(sesion, monkeypatch):
    monkeypatch.setenv("ORG_SIGNUP_CREDITS", "7")

    user, org, membresia = gl.resolver_usuario_google(sesion, _perfil())

    assert user.email == "ana@example.test"
    assert user.password_hash is None
    assert user.email_verified is True
    assert user.full_name == "Ana Prueba"
    assert user.last_login_at is not None
    assert org.settings == {"workspace_kind": "personal"}
    assert org.credits_balance == 7
    assert (membresia.role, membresia.is_primary_org) == ("admin", True)
    vinculo = sesion.execute(select(OAuthAccount)).scalar_one()
    assert (vinculo.provider, vinculo.provider_user_id, vinculo.user_id) == ("google", "g-1", user.id)


def test_correo_existente_se_vincula_sin_crear_otra_cuenta(sesion):
    org = Organization(name="Acme", slug="acme", settings={"workspace_kind": "work"})
    user = User(email="ana@example.test", password_hash=hash_password("secreta-123"))
    sesion.add_all([org, user])
    sesion.flush()
    sesion.add(OrgMembership(organization_id=org.id, user_id=user.id, role="user", is_primary_org=True))
    sesion.commit()

    vuelto, org_sesion, membresia = gl.resolver_usuario_google(sesion, _perfil(email="Ana@Example.test"))

    assert vuelto.id == user.id
    assert org_sesion.id == org.id
    assert membresia.role == "user"
    assert vuelto.email_verified is True
    assert vuelto.password_hash, "la contraseña existente se conserva"
    assert sesion.scalar(select(func.count()).select_from(User)) == 1
    assert sesion.scalar(select(func.count()).select_from(Organization)) == 1


def test_se_reconoce_por_sub_aunque_cambie_el_correo_en_google(sesion):
    primero, _, _ = gl.resolver_usuario_google(sesion, _perfil())

    segundo, _, _ = gl.resolver_usuario_google(sesion, _perfil(email="ana.nueva@example.test"))

    assert segundo.id == primero.id
    assert sesion.scalar(select(func.count()).select_from(User)) == 1


def test_flujo_http_completo_abre_sesion_en_el_espacio_creado(sesion, pg_vacia, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://front.test")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-g.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secreto-g")
    canjes: list[tuple[str, str]] = []
    monkeypatch.setattr(gl, "_canjear_codigo", lambda code, uri: canjes.append((code, uri)) or {"access_token": "t"})
    monkeypatch.setattr(gl, "_perfil_google", lambda token: _perfil())

    def _db():
        with Session(pg_vacia) as s:
            yield s

    app.dependency_overrides[get_db_if_configured] = _db
    try:
        cliente = TestClient(app, follow_redirects=False)
        inicio = cliente.get("/auth/google/login")
        state = dict(p.split("=", 1) for p in inicio.headers["location"].split("?", 1)[1].split("&"))["state"]
        vuelta = cliente.get("/auth/google/callback", params={"code": "codigo-1", "state": state})
    finally:
        app.dependency_overrides.pop(get_db_if_configured, None)

    assert vuelta.status_code == 302
    assert canjes == [("codigo-1", "http://testserver/auth/google/callback")]
    claims = decode_access_token(vuelta.headers["location"].split("#token=", 1)[1])
    org_id = sesion.execute(text("SELECT organization_id FROM org_memberships")).scalar_one()
    assert claims["email"] == "ana@example.test"
    assert claims["org_id"] == str(org_id)
    assert claims["role"] == "admin"
