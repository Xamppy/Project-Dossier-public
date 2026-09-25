"""Tests - S1.9: modelo comun de registro corporativo (UK / US / EU).

Cubre unicamente el contrato (specs/proposals/S1.9-modelo-comun-registro-corporativo.md).
No hay adaptadores de fuente real todavia: eso es S2.1 / S2.3.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from dossier.schemas.corporate_registry import (
    Directivo,
    DomicilioRegistrado,
    JurisdiccionRegistro,
    Presentacion,
    RegistroCorporativo,
)


def test_campos_minimos_requeridos():
    registro = RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.uk,
        fuente="companies_house",
        identificador_registro="01234567",
        razon_social="Acme Ltd",
    )
    assert registro.estado is None
    assert registro.forma_juridica is None
    assert registro.fecha_constitucion is None
    assert registro.domicilio is None
    assert registro.codigos_actividad == []
    assert registro.directivos == []
    assert registro.presentaciones == []
    assert registro.url_fuente is None
    assert registro.consultado_en is None
    assert registro.datos_brutos is None


@pytest.mark.parametrize("jurisdiccion", ["uk", "us", "fr", "de"])
def test_las_cuatro_jurisdicciones_del_alcance_firme_son_validas(jurisdiccion):
    registro = RegistroCorporativo(
        jurisdiccion=jurisdiccion,
        fuente="fuente-de-prueba",
        identificador_registro="X",
        razon_social="Empresa de prueba",
    )
    assert registro.jurisdiccion == jurisdiccion


def test_jurisdiccion_invalida_rechazada():
    with pytest.raises(ValidationError):
        RegistroCorporativo(
            jurisdiccion="es",
            fuente="fuente-de-prueba",
            identificador_registro="X",
            razon_social="Empresa de prueba",
        )


def test_domicilio_y_directivos_estructurados_estilo_frances():
    # Forma de "dirigeants" de la API Recherche d'entreprises (ADR 0003).
    registro = RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.fr,
        fuente="recherche_entreprises",
        identificador_registro="552100554",
        razon_social="L'Oreal SA",
        forma_juridica="Société anonyme",
        domicilio=DomicilioRegistrado(
            calle="14 Rue Royale",
            localidad="Paris",
            codigo_postal="75008",
            pais="France",
        ),
        directivos=[
            Directivo(nombre="Jean Dupont", cargo="Président", fecha_nombramiento="2020-06-01"),
        ],
    )
    assert registro.domicilio.localidad == "Paris"
    assert registro.directivos[0].cargo == "Président"


def test_presentaciones_estilo_companies_house():
    registro = RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.uk,
        fuente="companies_house",
        identificador_registro="01234567",
        razon_social="Acme Ltd",
        presentaciones=[
            Presentacion(fecha="2026-03-01", tipo="AA", descripcion="Annual accounts made up to..."),
        ],
    )
    assert registro.presentaciones[0].tipo == "AA"


def test_serializa_a_dict_json_compatible():
    registro = RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.us,
        fuente="sec_edgar",
        identificador_registro="0000320193",
        razon_social="Apple Inc.",
        url_fuente="https://www.sec.gov/cgi-bin/browse-edgar?CIK=0000320193",
        consultado_en=datetime(2026, 9, 12, tzinfo=timezone.utc),
        datos_brutos={"cik": "0000320193"},
    )
    dump = registro.model_dump(mode="json")
    assert dump["identificador_registro"] == "0000320193"
    assert dump["jurisdiccion"] == "us"
