"""La validación no resuelve invitaciones ni toca persistencia con contraseña inválida."""
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dossier.api.auth_routes import get_db_if_configured, router


@pytest.mark.parametrize('password', ['a' * 73, 'é' * 37, '🔐' * 19])
def test_registro_invitado_rechaza_exceso_antes_de_consultar_bd(password):
    db = Mock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db_if_configured] = lambda: db
    response = TestClient(app, raise_server_exceptions=False).post('/auth/register', json={
        'email': 'invitado@example.com', 'full_name': 'Invitado Prueba',
        'password': password, 'invite_token': 'invitacion-ficticia',
    })
    assert response.status_code == 422, response.text
    assert response.json()['detail'][0]['type'] == 'password_too_long_bytes'
    assert db.mock_calls == []
