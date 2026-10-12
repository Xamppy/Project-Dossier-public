"""Unitarias - S2.1: mapeo de filas crudas europeas a ``RegistroCorporativo``.

Ver specs/proposals/S1.9-modelo-comun-registro-corporativo.md (tabla de mapeo).
"""
from __future__ import annotations

from dossier.eu_registry.mapper import mapear_registro_aleman, mapear_registro_frances
from dossier.schemas.corporate_registry import JurisdiccionRegistro

# --- Francia --------------------------------------------------------------

def test_mapea_registro_frances_completo():
    fila = {
        "siren": "552100554",
        "nom_complet": "L'Oreal SA",
        "etat_administratif": "A",
        "nature_juridique": "SA",
        "date_creation": "1919-07-30",
        "activite_principale": "20.42Z",
        "siege": {
            "adresse": "14 Rue Royale",
            "libelle_commune": "Paris",
            "region": "Ile-de-France",
            "code_postal": "75008",
            "pays": "France",
        },
        "dirigeants": [
            {"nom": "Hieronimus", "qualite": "Directeur general"},
            {"nom": "", "qualite": "Sin nombre - se descarta"},
        ],
    }

    registro = mapear_registro_frances(fila)

    assert registro.jurisdiccion == JurisdiccionRegistro.fr
    assert registro.fuente == "recherche_entreprises"
    assert registro.identificador_registro == "552100554"
    assert registro.razon_social == "L'Oreal SA"
    assert registro.estado == "A"
    assert registro.forma_juridica == "SA"
    assert registro.fecha_constitucion == "1919-07-30"
    assert registro.codigos_actividad == ["20.42Z"]
    assert registro.domicilio is not None
    assert registro.domicilio.localidad == "Paris"
    assert registro.domicilio.codigo_postal == "75008"
    assert len(registro.directivos) == 1
    assert registro.directivos[0].nombre == "Hieronimus"
    assert registro.directivos[0].cargo == "Directeur general"
    assert registro.datos_brutos == fila


def test_mapea_registro_frances_campos_minimos():
    """Solo lo que trae el fixture de S1.8 (test_eu_registry_client.py)."""
    fila = {"siren": "552100554", "nom_complet": "L'Oreal SA"}

    registro = mapear_registro_frances(fila)

    assert registro.identificador_registro == "552100554"
    assert registro.razon_social == "L'Oreal SA"
    assert registro.domicilio is None
    assert registro.directivos == []
    assert registro.presentaciones == []


def test_mapea_registro_frances_fila_vacia_no_lanza():
    registro = mapear_registro_frances({})

    assert registro.identificador_registro == ""
    assert registro.razon_social == ""
    assert registro.jurisdiccion == JurisdiccionRegistro.fr


def test_mapea_registro_frances_usa_siret_si_falta_siren():
    registro = mapear_registro_frances({"siret": "55210055400010", "nom_complet": "X"})
    assert registro.identificador_registro == "55210055400010"


# --- Alemania --------------------------------------------------------------

def test_mapea_registro_aleman_campos_del_fixture_s18():
    fila = {"name": "Beispiel GmbH", "company_number": "HRB 12345"}

    registro = mapear_registro_aleman(fila)

    assert registro.jurisdiccion == JurisdiccionRegistro.de
    assert registro.fuente == "handelsregister"
    assert registro.identificador_registro == "HRB 12345"
    assert registro.razon_social == "Beispiel GmbH"
    assert registro.datos_brutos == fila


def test_mapea_registro_aleman_campos_extendidos():
    fila = {
        "name": "Beispiel GmbH",
        "company_number": "HRB 12345",
        "current_status": "Active",
        "company_type": "GmbH",
        "incorporation_date": "2001-05-02",
        "registered_address_in_full": "Musterstrasse 1, 10115 Berlin",
        "opencorporates_url": "https://opencorporates.com/companies/de/HRB12345",
    }

    registro = mapear_registro_aleman(fila)

    assert registro.estado == "Active"
    assert registro.forma_juridica == "GmbH"
    assert registro.fecha_constitucion == "2001-05-02"
    assert registro.domicilio is not None
    assert registro.domicilio.calle == "Musterstrasse 1, 10115 Berlin"
    assert registro.url_fuente == "https://opencorporates.com/companies/de/HRB12345"


def test_mapea_registro_aleman_fila_vacia_no_lanza():
    registro = mapear_registro_aleman({})

    assert registro.identificador_registro == ""
    assert registro.razon_social == ""
    assert registro.jurisdiccion == JurisdiccionRegistro.de
    assert registro.domicilio is None
