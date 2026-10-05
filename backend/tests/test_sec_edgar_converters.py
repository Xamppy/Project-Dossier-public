"""Tests - S2.3: adaptador de SEC EDGAR al modelo comun (RegistroCorporativo).

Convierte lo que ya entrega ``submissions/CIK{n}.json`` a ``RegistroCorporativo`` +
``CorporateRecordCitation`` (S1.9). Son funciones puras sobre el JSON ya obtenido por
el agente existente: no llaman a la red.
"""
from __future__ import annotations

from datetime import UTC, datetime

from dossier.schemas.corporate_registry import JurisdiccionRegistro
from dossier.schemas.dossier_executive_payload import SourceType
from dossier.sec_edgar.converters import submissions_a_registro_corporativo

SUBMISSIONS = {
    "cik": "320193",
    "name": "Apple Inc.",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "tickers": ["AAPL"],
    "filings": {
        "recent": {
            "form": ["10-K", "10-Q"],
            "filingDate": ["2023-11-03", "2023-08-04"],
            "accessionNumber": ["0000320193-23-000106", "0000320193-23-000077"],
        }
    },
}


def test_submissions_completo_produce_registro_con_campos_disponibles():
    momento = datetime(2024, 1, 1, tzinfo=UTC)
    cita = submissions_a_registro_corporativo(SUBMISSIONS, "0000320193", consultado_en=momento)

    registro = cita.record
    assert registro.jurisdiccion == JurisdiccionRegistro.us
    assert registro.fuente == "sec_edgar"
    assert registro.identificador_registro == "0000320193"
    assert registro.razon_social == "Apple Inc."
    assert registro.codigos_actividad == ["3571"]
    assert len(registro.presentaciones) == 2
    assert registro.presentaciones[0].tipo == "10-K"
    assert registro.presentaciones[0].fecha == "2023-11-03"
    assert registro.presentaciones[0].url is not None
    assert registro.consultado_en == momento

    assert cita.source.source_type == SourceType.sec_edgar
    assert cita.source.record_id == "0000320193"


def test_campos_sin_equivalente_directo_quedan_en_none():
    """Ver tabla de mapeo de S1.9: SEC no entrega estado/forma_juridica/fecha/domicilio."""
    cita = submissions_a_registro_corporativo(SUBMISSIONS, "320193")
    registro = cita.record
    assert registro.estado is None
    assert registro.forma_juridica is None
    assert registro.fecha_constitucion is None
    assert registro.domicilio is None
    assert registro.directivos == []


def test_submissions_sin_filings_no_rompe():
    cita = submissions_a_registro_corporativo({"cik": "1", "name": "Shell Inc"}, "1")
    assert cita.record.presentaciones == []
    assert cita.record.codigos_actividad == []


def test_submissions_vacio_no_lanza_excepcion():
    cita = submissions_a_registro_corporativo({}, "")
    assert cita.record.razon_social == ""
    assert cita.record.identificador_registro == ""
    assert cita.record.url_fuente is None


def test_cik_se_normaliza_a_diez_digitos():
    cita = submissions_a_registro_corporativo({"name": "X"}, "320193")
    assert cita.record.identificador_registro == "0000320193"


def test_serializa_a_dict_sin_errores():
    cita = submissions_a_registro_corporativo(SUBMISSIONS, "0000320193")
    dump = cita.model_dump()
    assert dump["record"]["fuente"] == "sec_edgar"
