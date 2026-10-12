"""S4.6, unitarias: mapeo puro de ``DossierExecutivePayload`` a filas de tabla.

Sin Postgres: solo prueba que ``_filas_de_alertas`` y ``_filas_de_ice_breakers``
transforman el payload en las columnas reales de ``dossier_alerts`` y
``dossier_ice_breakers``, sin tocar la base.
"""
from __future__ import annotations

import pytest

from dossier.services.dossier_entities_writer import (
    _filas_de_alertas,
    _filas_de_ice_breakers,
)


def _alerta(**overrides) -> dict:
    base = {
        "title": "Litigio abierto",
        "severity": "high",
        "description": "Demanda vigente contra la empresa.",
        "sources": [{"source_type": "companies_house", "source_name": "CH"}],
    }
    base.update(overrides)
    return base


def _starter(**overrides) -> dict:
    base = {
        "topic": "Expansión regional",
        "rationale": "Mencionó planes de abrir oficina en Chile.",
        "suggested_opener": "¿Cómo va la apertura de la oficina en Chile?",
    }
    base.update(overrides)
    return base


# Caso normal: cada alerta se mapea a level/title/message/sources.
def test_filas_de_alertas_mapea_severity_y_description():
    payload = {"risk_alerts": [_alerta()]}

    filas = _filas_de_alertas(payload)

    assert filas == [
        {
            "level": "high",
            "title": "Litigio abierto",
            "message": "Demanda vigente contra la empresa.",
            "sources": [{"source_type": "companies_house", "source_name": "CH"}],
        }
    ]


# Borde: sin risk_alerts (o lista vacía) no hay filas.
@pytest.mark.parametrize("payload", [{}, {"risk_alerts": []}])
def test_filas_de_alertas_vacio_sin_riesgos(payload):
    assert _filas_de_alertas(payload) == []


# Borde: sources ausente cae a lista vacía, nunca a NULL (columna NOT NULL).
def test_filas_de_alertas_sin_sources_usa_lista_vacia():
    payload = {"risk_alerts": [_alerta(sources=None)]}

    assert _filas_de_alertas(payload)[0]["sources"] == []


# Error: falta un campo obligatorio del contrato (severity) -> falla, no se inventa un valor.
def test_filas_de_alertas_sin_severity_lanza_key_error():
    payload = {"risk_alerts": [{"title": "x", "description": "y"}]}

    with pytest.raises(KeyError):
        _filas_de_alertas(payload)


# Caso normal: cada starter se mapea a content, con sort_order por posición.
def test_filas_de_ice_breakers_mapea_suggested_opener_y_orden():
    payload = {"conversation_starters": [_starter(), _starter(suggested_opener="¿Y el equipo?")]}

    filas = _filas_de_ice_breakers(payload)

    assert filas == [
        {"content": "¿Cómo va la apertura de la oficina en Chile?", "sort_order": 0},
        {"content": "¿Y el equipo?", "sort_order": 1},
    ]


# Borde: sin conversation_starters (o lista vacía) no hay filas.
@pytest.mark.parametrize("payload", [{}, {"conversation_starters": []}])
def test_filas_de_ice_breakers_vacio_sin_ideas(payload):
    assert _filas_de_ice_breakers(payload) == []


# Error: falta el campo obligatorio suggested_opener -> falla, no se inventa un valor.
def test_filas_de_ice_breakers_sin_suggested_opener_lanza_key_error():
    payload = {"conversation_starters": [{"topic": "x", "rationale": "y"}]}

    with pytest.raises(KeyError):
        _filas_de_ice_breakers(payload)
