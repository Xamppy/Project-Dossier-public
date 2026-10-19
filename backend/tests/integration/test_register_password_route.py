"""Registro manual contra PostgreSQL: límite bcrypt, login y ausencia de altas parciales."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alembic import command
from dossier.api.app import app
from dossier.api.auth_routes import get_db_if_configured
from dossier.db.models import Organization, OrgMembership, User
from dossier.security import verify_password


@pytest.fixture
def registro(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, 'head')

    def db():
        with Session(pg_vacia) as session:
            yield session

    app.dependency_overrides[get_db_if_configured] = db
    try:
        yield TestClient(app, raise_server_exceptions=False), pg_vacia
    finally:
        app.dependency_overrides.pop(get_db_if_configured, None)


def payload(password, workspace_kind):
    return {
        'email': 'persona@example.com', 'full_name': 'Persona Prueba',
        'password': password, 'workspace_kind': workspace_kind,
        'company_name': 'Empresa Prueba' if workspace_kind == 'work' else None,
    }


@pytest.mark.parametrize('workspace_kind', ['personal', 'work'])
@pytest.mark.parametrize('password', ['a' * 8, 'a' * 72, 'é' * 36, '🔐' * 18])
def test_registro_hasta_72_bytes_permite_login_y_guarda_bcrypt(registro, password, workspace_kind):
    client, engine = registro
    body = payload(password, workspace_kind)
    response = client.post('/auth/register', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['user']['workspace_kind'] == workspace_kind
    with Session(engine) as session:
        user = session.scalar(select(User))
        assert user.password_hash.startswith('$2b$')
        assert verify_password(password, user.password_hash)
        assert not verify_password('incorrecta', user.password_hash)
        for model in (User, Organization, OrgMembership):
            assert session.scalar(select(func.count()).select_from(model)) == 1
    assert client.post('/auth/login', json={'email': body['email'], 'password': password}).status_code == 200
    assert client.post('/auth/register', json=body).status_code == 409


@pytest.mark.parametrize('workspace_kind', ['personal', 'work'])
@pytest.mark.parametrize('password', ['a' * 73, 'a' * 128, 'a' * 129, 'é' * 37, '🔐' * 19])
def test_exceso_de_bytes_devuelve_422_sin_crear_filas(registro, password, workspace_kind):
    client, engine = registro
    response = client.post('/auth/register', json=payload(password, workspace_kind))
    assert response.status_code == 422, response.text
    detail = response.json()['detail'][0]
    assert detail['loc'] == ['body', 'password']
    assert detail['type'] == 'password_too_long_bytes'
    assert detail['ctx']['max_bytes'] == 72
    assert '72 bytes' in detail['msg']
    with Session(engine) as session:
        for model in (User, Organization, OrgMembership):
            assert session.scalar(select(func.count()).select_from(model)) == 0
