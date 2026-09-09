"""Plantilla viva de pruebas de seguridad.

Cubren los cuatro controles del objetivo específico 8: control de acceso,
limitación de tasa, registro de auditoría y retención de 24 horas.

Hoy solo existe el primero. Las pruebas de los otros tres están escritas como
esqueleto con `skip` y su tarea asociada: cuando la tarea se implemente, se quita
el `skip` y la prueba ya dice qué debe cumplir. Eso es TDD a escala de sprint.

Ver docs/dev/testing-policy.md §1 y docs/security/README.md.
"""
from __future__ import annotations

import os

import pytest

from dossier.security.jwt_tokens import (
    create_access_token,
    decode_access_token,
)


# --------------------------------------------------------------------------
# Control de acceso — implementado
# --------------------------------------------------------------------------

def test_token_valido_se_decodifica_con_sus_datos():
    """Caso normal: lo que se firma es lo que se lee."""
    token = create_access_token(
        user_id="u-1",
        email="persona@ejemplo.cl",
        organization_id="org-1",
        role="user",
    )
    datos = decode_access_token(token)

    assert datos["sub"] == "u-1"
    assert datos["email"] == "persona@ejemplo.cl"
    # La clave del payload es `org_id`, no `organization_id`: el parámetro y el
    # campo firmado tienen nombres distintos (jwt_tokens.py:48).
    assert datos["org_id"] == "org-1"
    assert datos["role"] == "user"


def test_token_manipulado_es_rechazado():
    """Caso de error: alterar el token invalida la firma."""
    token = create_access_token(user_id="u-1", email="persona@ejemplo.cl")
    manipulado = token[:-6] + "AAAAAA"

    with pytest.raises(Exception):
        decode_access_token(manipulado)


def test_token_con_otra_clave_es_rechazado():
    """Caso de error: un token firmado con otra clave no vale.

    Es la prueba que demuestra que `JWT_SECRET` cumple su función.
    """
    token = create_access_token(user_id="u-1", email="persona@ejemplo.cl")

    previo = os.environ["JWT_SECRET"]
    os.environ["JWT_SECRET"] = "una-clave-distinta-de-la-original-xyz"
    try:
        with pytest.raises(Exception):
            decode_access_token(token)
    finally:
        os.environ["JWT_SECRET"] = previo


def test_vigencia_del_token_de_acceso_es_corta():
    """La vigencia por omisión es de 7 días (10080 minutos) y debe bajar.

    Esta prueba documenta el hallazgo de seguridad y **falla a propósito**
    cuando S3.9 no está hecha. Se quita el `skip` al implementar S3.9: ese es el
    momento en que pasa a verde y se queda para siempre como red de seguridad.

    Ver docs/security/README.md, "Token de acceso de 7 días en localStorage".
    """
    pytest.skip("Se habilita con S3.9 — reducir vigencia del token e introducir renovación")


# --------------------------------------------------------------------------
# Aislamiento entre organizaciones — S6.7
# --------------------------------------------------------------------------
#
# Prueba NEGATIVA: no verifica que algo funcione, sino que algo NO sea posible.
# Es la más valiosa de este proyecto, porque una fuga entre organizaciones es el
# fallo más caro que puede tener un sistema multiempresa.
#
# Patrón:
#   1. Crea dos organizaciones con un recurso cada una
#   2. Autentica como la organización A
#   3. Pide el recurso de la organización B
#   4. Verifica que la respuesta es 404 o 403, NUNCA el recurso

@pytest.mark.skip(reason="Se habilita con S6.7 — pruebas negativas de aislamiento")
def test_una_organizacion_no_accede_a_dossiers_de_otra():
    raise NotImplementedError


@pytest.mark.skip(reason="Se habilita con S6.7, tras S4.5")
def test_una_organizacion_no_accede_a_alertas_ni_prensa_de_otra():
    raise NotImplementedError


@pytest.mark.skip(reason="Se habilita con S6.7, tras S4.10")
def test_una_organizacion_no_lee_la_auditoria_de_otra():
    raise NotImplementedError


# --------------------------------------------------------------------------
# Limitación de tasa — S5.8
# --------------------------------------------------------------------------

@pytest.mark.skip(reason="Se habilita con S5.8 — limitación de tasa")
def test_superado_el_umbral_la_api_responde_429():
    raise NotImplementedError


@pytest.mark.skip(reason="Se habilita con S5.8")
def test_pasada_la_ventana_la_api_vuelve_a_aceptar():
    raise NotImplementedError


# --------------------------------------------------------------------------
# Auditoría — S4.10 y S6.6
# --------------------------------------------------------------------------

@pytest.mark.skip(reason="Se habilita con S4.10 — registro de auditoría")
def test_leer_un_dossier_deja_registro_de_auditoria():
    """Con actor, organización, recurso e instante."""
    raise NotImplementedError


@pytest.mark.skip(reason="Se habilita con S6.6")
def test_enviar_y_borrar_dejan_registro_de_auditoria():
    raise NotImplementedError


# --------------------------------------------------------------------------
# Retención de 24 horas — S6.5
# --------------------------------------------------------------------------

@pytest.mark.skip(reason="Se habilita con S6.5 — retención de 24 h")
def test_pasadas_24_horas_el_dossier_no_es_recuperable():
    """Borrado EFECTIVO, no solo marca de borrado.

    Hoy `ALLOWED_DOSSIER_RETENTION_DAYS = {7, 14, 30, 90}` y admite conservar
    indefinidamente. La especificación exige 24 horas con borrado verificado.
    """
    raise NotImplementedError


@pytest.mark.skip(reason="Se habilita con S6.5, tras S4.5")
def test_el_borrado_arrastra_alertas_trayectoria_y_prensa():
    """Sin entidades huérfanas: el borrado debe ser completo."""
    raise NotImplementedError
