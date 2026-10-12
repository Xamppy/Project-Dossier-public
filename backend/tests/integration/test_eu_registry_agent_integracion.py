"""Integracion - S2.1: agente europeo con ambas fuentes simuladas a la vez.

Cubre deduplicacion cruzada, mezcla de exito+error por pais y que la salida
cumple el contrato de citas del dossier ejecutivo
(``CorporateRecordCitation`` / ``SourceCitation``, S4.1).
"""
from __future__ import annotations

from dossier.eu_registry import agent, client
from dossier.schemas.corporate_registry import JurisdiccionRegistro
from dossier.schemas.dossier_executive_payload import CorporateRecordCitation


def test_flujo_completo_con_cliente_http_simulado(monkeypatch, respuesta_fija):
    """Pasa por el cliente HTTP real (S1.8), no solo por la funcion del agente."""

    def fake_get_francia(url, params=None, timeout=None):
        assert url == client.FRANCE_SEARCH_URL
        return respuesta_fija(
            {
                "results": [
                    {"siren": "552100554", "nom_complet": "L'Oreal SA"},
                    {"siren": "552100554", "nom_complet": "L'Oreal SA (repetida)"},
                ]
            }
        )

    def fake_get_alemania(url, params=None, timeout=None):
        assert url.endswith("/company.json")
        return respuesta_fija([{"company_number": "HRB 12345", "name": "Beispiel GmbH"}])

    def fake_get(url, params=None, timeout=None):
        if "gouv.fr" in url:
            return fake_get_francia(url, params=params, timeout=timeout)
        return fake_get_alemania(url, params=params, timeout=timeout)

    monkeypatch.setattr(client.requests, "get", fake_get)

    resultado = agent.run_eu_registry_agent("Oreal Beispiel")

    # Deduplicado: dos filas francesas con el mismo SIREN -> una sola cita.
    citas_fr = [c for c in resultado.citas if c.record.jurisdiccion == JurisdiccionRegistro.fr]
    assert len(citas_fr) == 1
    assert citas_fr[0].record.razon_social == "L'Oreal SA"

    citas_de = [c for c in resultado.citas if c.record.jurisdiccion == JurisdiccionRegistro.de]
    assert len(citas_de) == 1
    assert citas_de[0].record.identificador_registro == "HRB 12345"

    assert resultado.errores == {}

    # Contrato de cita obligatorio del dossier ejecutivo (S4.1): cada elemento
    # debe poder reconstruirse como CorporateRecordCitation sin perder datos.
    for cita in resultado.citas:
        reconstruida = CorporateRecordCitation.model_validate(cita.model_dump())
        assert reconstruida == cita


def test_un_pais_caido_y_el_otro_con_datos_conviven(monkeypatch, respuesta_fija):
    def fake_get(url, params=None, timeout=None):
        if "gouv.fr" in url:
            return respuesta_fija({"error": "boom"}, status=500)
        return respuesta_fija([{"company_number": "HRB 1", "name": "Solo Alemania GmbH"}])

    monkeypatch.setattr(client.requests, "get", fake_get)

    resultado = agent.run_eu_registry_agent("Solo Alemania")

    assert "fr" in resultado.errores
    assert len(resultado.citas) == 1
    assert resultado.citas[0].record.jurisdiccion == JurisdiccionRegistro.de


def test_serializa_a_dict_para_embeber_en_dossier_data(monkeypatch, respuesta_fija):
    monkeypatch.setattr(
        client.requests,
        "get",
        lambda url, params=None, timeout=None: respuesta_fija(
            {"results": [{"siren": "1", "nom_complet": "Acme"}]}
        )
        if "gouv.fr" in url
        else respuesta_fija([]),
    )

    resultado = agent.run_eu_registry_agent("Acme")

    volcado = [c.model_dump(mode="json") for c in resultado.citas]
    assert volcado[0]["record"]["jurisdiccion"] == "fr"
    assert volcado[0]["source"]["source_type"] == "eu_registry"
