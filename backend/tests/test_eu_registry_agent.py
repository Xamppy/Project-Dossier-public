"""Unitarias - S2.1: agente de registros corporativos europeos.

Monkeypatch sobre el cliente (reexportado por ``eu_registry.agent``), sin red
real (fixture ``sin_red`` de conftest.py es autouse).
"""
from __future__ import annotations

from dossier.eu_registry import agent
from dossier.eu_registry.client import RegistroEuropeoError
from dossier.schemas.corporate_registry import JurisdiccionRegistro
from dossier.schemas.dossier_executive_payload import SourceType


def test_consulta_ambas_jurisdicciones_por_defecto(monkeypatch):
    monkeypatch.setattr(
        agent, "search_france_companies", lambda q, *, limite=5: [{"siren": "1", "nom_complet": "Acme FR"}]
    )
    monkeypatch.setattr(
        agent, "search_germany_companies", lambda q, *, limite=5: [{"company_number": "HRB 1", "name": "Acme DE"}]
    )

    resultado = agent.run_eu_registry_agent("Acme")

    jurisdicciones = {c.record.jurisdiccion for c in resultado.citas}
    assert jurisdicciones == {JurisdiccionRegistro.fr, JurisdiccionRegistro.de}
    assert resultado.errores == {}


def test_nombre_vacio_no_llama_a_ninguna_fuente(monkeypatch):
    def falla(*args, **kwargs):
        raise AssertionError("no deberia consultar con nombre vacio")

    monkeypatch.setattr(agent, "search_france_companies", falla)
    monkeypatch.setattr(agent, "search_germany_companies", falla)

    resultado = agent.run_eu_registry_agent("   ")

    assert resultado.citas == []
    assert resultado.errores == {}


def test_filtra_por_jurisdiccion_pedida(monkeypatch):
    monkeypatch.setattr(
        agent, "search_france_companies", lambda q, *, limite=5: [{"siren": "1", "nom_complet": "Acme FR"}]
    )

    def falla_alemania(*args, **kwargs):
        raise AssertionError("no deberia consultar Alemania si no se pidio")

    monkeypatch.setattr(agent, "search_germany_companies", falla_alemania)

    resultado = agent.run_eu_registry_agent("Acme", jurisdicciones=["fr"])

    assert {c.record.jurisdiccion for c in resultado.citas} == {JurisdiccionRegistro.fr}


def test_jurisdiccion_no_soportada_lanza_value_error():
    import pytest

    with pytest.raises(ValueError):
        agent.run_eu_registry_agent("Acme", jurisdicciones=["uk"])


def test_error_de_un_pais_no_impide_el_otro(monkeypatch):
    def rompe(*args, **kwargs):
        raise RegistroEuropeoError("Francia caida")

    monkeypatch.setattr(agent, "search_france_companies", rompe)
    monkeypatch.setattr(
        agent, "search_germany_companies", lambda q, *, limite=5: [{"company_number": "HRB 1", "name": "Acme DE"}]
    )

    resultado = agent.run_eu_registry_agent("Acme")

    assert resultado.errores == {"fr": "Francia caida"}
    assert len(resultado.citas) == 1
    assert resultado.citas[0].record.jurisdiccion == JurisdiccionRegistro.de


def test_cita_trae_source_citation_con_source_type_eu_registry(monkeypatch):
    monkeypatch.setattr(
        agent, "search_france_companies", lambda q, *, limite=5: [{"siren": "552100554", "nom_complet": "L'Oreal"}]
    )
    monkeypatch.setattr(agent, "search_germany_companies", lambda q, *, limite=5: [])

    resultado = agent.run_eu_registry_agent("L'Oreal")

    cita = resultado.citas[0]
    assert cita.source.source_type == SourceType.eu_registry
    assert cita.source.record_id == "552100554"
    assert cita.source.retrieved_at is not None
