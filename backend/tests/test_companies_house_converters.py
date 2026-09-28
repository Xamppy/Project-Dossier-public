"""Tests - S2.3: adaptador de Companies House al modelo comun (RegistroCorporativo).

Convierte lo que ya devuelven ``get_company_profile``/``get_filing_history`` (perfil +
filing history) a ``RegistroCorporativo`` + ``CorporateRecordCitation`` (S1.9). Son
funciones puras sobre el JSON ya obtenido por el agente existente: no llaman a la red.
"""
from __future__ import annotations

from datetime import UTC, datetime

from dossier.companies_house.converters import perfil_a_registro_corporativo
from dossier.schemas.corporate_registry import JurisdiccionRegistro
from dossier.schemas.dossier_executive_payload import SourceType

PERFIL_COMPLETO = {
    "company_name": "Acme Ltd",
    "company_number": "01234567",
    "company_status": "active",
    "type": "ltd",
    "date_of_creation": "1999-05-01",
    "registered_office_address": {
        "premises": "1",
        "address_line_1": "Baker Street",
        "locality": "London",
        "region": "Greater London",
        "postal_code": "NW1 6XE",
        "country": "United Kingdom",
    },
    "sic_codes": ["62012", "62020"],
    "links": {"self": "/company/01234567"},
}

FILING_HISTORY = {
    "items": [
        {"date": "2023-01-10", "type": "AA", "description": "cuentas anuales"},
        {"date": "2022-01-10", "type": "CS01", "description": "declaracion de confirmacion"},
    ]
}


def test_perfil_completo_produce_registro_con_todos_los_campos():
    momento = datetime(2024, 1, 1, tzinfo=UTC)
    cita = perfil_a_registro_corporativo(PERFIL_COMPLETO, FILING_HISTORY, consultado_en=momento)

    registro = cita.record
    assert registro.jurisdiccion == JurisdiccionRegistro.uk
    assert registro.fuente == "companies_house"
    assert registro.identificador_registro == "01234567"
    assert registro.razon_social == "Acme Ltd"
    assert registro.estado == "active"
    assert registro.forma_juridica == "ltd"
    assert registro.fecha_constitucion == "1999-05-01"
    assert registro.domicilio.localidad == "London"
    assert registro.domicilio.codigo_postal == "NW1 6XE"
    assert registro.codigos_actividad == ["62012", "62020"]
    assert len(registro.presentaciones) == 2
    assert registro.presentaciones[0].tipo == "AA"
    assert registro.consultado_en == momento
    assert registro.url_fuente == (
        "https://find-and-update.company-information.service.gov.uk/company/01234567"
    )

    assert cita.source.source_type == SourceType.companies_house
    assert cita.source.record_id == "01234567"
    assert cita.source.retrieved_at == momento
    assert cita.source.url == registro.url_fuente


def test_directivos_vacio_porque_ch_no_consulta_officers_hoy():
    """Ver tabla de mapeo de S1.9: el endpoint /officers no se consulta hoy."""
    cita = perfil_a_registro_corporativo(PERFIL_COMPLETO, FILING_HISTORY)
    assert cita.record.directivos == []


def test_perfil_incompleto_sin_direccion_ni_filing_history_no_rompe():
    perfil_minimo = {"company_name": "Shell Co", "company_number": "00000001"}
    cita = perfil_a_registro_corporativo(perfil_minimo, None)

    assert cita.record.razon_social == "Shell Co"
    assert cita.record.domicilio is None
    assert cita.record.presentaciones == []
    assert cita.record.estado is None
    assert cita.record.fecha_constitucion is None


def test_perfil_vacio_no_lanza_excepcion():
    cita = perfil_a_registro_corporativo({}, {})
    assert cita.record.identificador_registro == ""
    assert cita.record.razon_social == ""
    assert cita.record.url_fuente is None


def test_serializa_a_dict_sin_errores():
    cita = perfil_a_registro_corporativo(PERFIL_COMPLETO, FILING_HISTORY)
    dump = cita.model_dump()
    assert dump["record"]["identificador_registro"] == "01234567"
    assert dump["source"]["source_type"] == "companies_house"
