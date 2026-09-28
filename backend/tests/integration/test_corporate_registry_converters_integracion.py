"""Tests de integracion - S2.3: HTTP simulado hasta RegistroCorporativo.

Cruza capas: el cliente HTTP existente (``companies_house.cli`` / ``sec_edgar.cli``) mas
el adaptador nuevo (``companies_house.converters`` / ``sec_edgar.converters``). La red
esta bloqueada por ``sin_red``; se usa ``respuesta_fija`` para simular al proveedor.
"""
from __future__ import annotations

import dossier.companies_house.cli as ch_cli
import dossier.sec_edgar.cli as sec_cli
from dossier.companies_house.converters import perfil_a_registro_corporativo
from dossier.sec_edgar.converters import submissions_a_registro_corporativo

PERFIL = {
    "company_name": "Acme Ltd",
    "company_number": "01234567",
    "company_status": "active",
    "type": "ltd",
    "date_of_creation": "1999-05-01",
    "registered_office_address": {"locality": "London", "country": "United Kingdom"},
    "sic_codes": ["62012"],
    "links": {"self": "/company/01234567"},
}
FILING_HISTORY = {"items": [{"date": "2023-01-10", "type": "AA", "description": "cuentas"}]}


def test_perfil_y_filing_history_reales_se_convierten_de_extremo_a_extremo(monkeypatch, respuesta_fija):
    respuestas = {
        ch_cli.COMPANY_URL_TEMPLATE.format(number="01234567"): PERFIL,
        ch_cli.FILING_HISTORY_URL_TEMPLATE.format(number="01234567"): FILING_HISTORY,
    }

    def fake_get(url, auth=None, params=None, timeout=None):
        assert url in respuestas
        return respuesta_fija(respuestas[url])

    monkeypatch.setattr(ch_cli.requests, "get", fake_get)

    perfil = ch_cli.get_company_profile("01234567", ("key", ""))
    filing_history = ch_cli.get_filing_history("01234567", ("key", ""))
    cita = perfil_a_registro_corporativo(perfil, filing_history)

    assert cita.record.identificador_registro == "01234567"
    assert cita.record.razon_social == "Acme Ltd"
    assert len(cita.record.presentaciones) == 1


def test_submissions_reales_se_convierten_de_extremo_a_extremo(monkeypatch, respuesta_fija):
    submissions = {
        "cik": "320193",
        "name": "Apple Inc.",
        "sic": "3571",
        "filings": {
            "recent": {
                "form": ["10-K"],
                "filingDate": ["2023-11-03"],
                "accessionNumber": ["0000320193-23-000106"],
            }
        },
    }

    def fake_get(url, headers=None, timeout=None):
        assert "submissions/CIK0000320193.json" in url
        return respuesta_fija(submissions)

    monkeypatch.setattr(sec_cli.requests, "get", fake_get)

    data = sec_cli.fetch_json("https://data.sec.gov/submissions/CIK0000320193.json")
    cita = submissions_a_registro_corporativo(data, "0000320193")

    assert cita.record.razon_social == "Apple Inc."
    assert len(cita.record.presentaciones) == 1


def test_perfil_obtenido_sin_filing_history_previo_se_convierte_igual(monkeypatch, respuesta_fija):
    """Si el historial de filings no llego a pedirse (p. ej. fallo aguas arriba), el perfil
    ya obtenido igual se convierte, con presentaciones vacias."""

    def fake_get(url, auth=None, params=None, timeout=None):
        return respuesta_fija(PERFIL)

    monkeypatch.setattr(ch_cli.requests, "get", fake_get)
    perfil_obtenido = ch_cli.get_company_profile("01234567", ("key", ""))
    cita = perfil_a_registro_corporativo(perfil_obtenido, None)

    assert cita.record.razon_social == "Acme Ltd"
    assert cita.record.presentaciones == []
