"""Contrato de registro: bcrypt recibe como máximo 72 bytes UTF-8."""
import pytest
from pydantic import ValidationError

from dossier.schemas.auth import RegisterRequest


@pytest.mark.parametrize('password', ['a' * 8, 'a' * 72, 'é' * 36, '🔐' * 18])
def test_password_valida_se_conserva_exactamente(password):
    body = RegisterRequest(email='prueba@example.com', full_name='Persona Prueba', password=password)
    assert body.password == password


@pytest.mark.parametrize('password', ['a' * 73, 'a' * 128, 'a' * 129, 'é' * 37, '🔐' * 19])
def test_password_mayor_a_72_bytes_se_rechaza_con_mensaje(password):
    with pytest.raises(ValidationError) as error:
        RegisterRequest(email='prueba@example.com', full_name='Persona Prueba', password=password)
    detalle = error.value.errors()[0]
    assert detalle['loc'] == ('password',)
    assert detalle['type'] == 'password_too_long_bytes'
    assert detalle['ctx'] == {'max_bytes': 72}
    assert '72 bytes' in detalle['msg']


def test_minimo_de_ocho_caracteres_se_conserva():
    with pytest.raises(ValidationError) as error:
        RegisterRequest(email='prueba@example.com', full_name='Persona Prueba', password='é' * 7)
    assert error.value.errors()[0]['type'] == 'string_too_short'
