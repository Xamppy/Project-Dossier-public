"""Tests unitarios — User-Agent de la SEC configurable por entorno.

La SEC exige un User-Agent con nombre y correo de contacto. Antes estaba fijo en el
código con el correo de una persona real, repetido en tres módulos. Ahora sale de
``SEC_USER_AGENT`` y, sin la variable, usa un valor ficticio válido.
"""
from __future__ import annotations

import re

import pytest

from dossier.sec_edgar import cli as sec_cli
from dossier.sec_edgar.user_agent import (
    SEC_USER_AGENT_DEFAULT,
    sec_request_headers,
    sec_user_agent,
)
from dossier.services import corporate_company_search, corporate_registry_context

CORREO = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def test_valor_por_defecto_es_ficticio_y_tiene_nombre_y_correo(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    ua = sec_user_agent()
    assert ua == SEC_USER_AGENT_DEFAULT
    correo = CORREO.search(ua)
    assert correo is not None, "la política de la SEC pide un correo de contacto"
    assert correo.group(0).endswith("@example.com")
    # Antes del correo debe ir un nombre identificable.
    assert ua[: correo.start()].strip()


def test_valor_por_defecto_no_contiene_el_correo_real_anterior(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert "utem" not in sec_user_agent().lower()
    assert "carlosapp" not in sec_user_agent().lower()


def test_user_agent_sale_de_la_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Equipo Prueba pruebas@example.com")
    assert sec_user_agent() == "Equipo Prueba pruebas@example.com"
    assert sec_request_headers()["User-Agent"] == "Equipo Prueba pruebas@example.com"


@pytest.mark.parametrize("vacio", ["", "   "])
def test_variable_vacia_usa_el_valor_por_defecto(monkeypatch, vacio):
    monkeypatch.setenv("SEC_USER_AGENT", vacio)
    assert sec_user_agent() == SEC_USER_AGENT_DEFAULT


class _RespuestaFalsa:
    content = b"{}"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {}


@pytest.mark.parametrize(
    ("modulo", "llamar"),
    [
        (sec_cli, lambda: sec_cli.fetch_json("https://www.sec.gov/x.json")),
        (sec_cli, lambda: sec_cli.fetch_bytes("https://www.sec.gov/x.htm")),
        (
            corporate_company_search,
            lambda: corporate_company_search._load_sec_company_rows.__wrapped__(),
        ),
        (
            corporate_registry_context,
            lambda: corporate_registry_context._sec_get_json("https://data.sec.gov/x.json"),
        ),
        (
            corporate_registry_context,
            lambda: corporate_registry_context._sec_fetch_bytes("https://www.sec.gov/x.htm"),
        ),
    ],
)
def test_los_tres_modulos_envian_el_user_agent_configurado(monkeypatch, modulo, llamar):
    """CLI, búsqueda de empresas y contexto corporativo usan la misma fuente."""
    monkeypatch.setenv("SEC_USER_AGENT", "Equipo Prueba pruebas@example.com")
    enviados: list[dict] = []

    def get_falso(url, headers=None, timeout=None):
        enviados.append(headers or {})
        return _RespuestaFalsa()

    monkeypatch.setattr(modulo.requests, "get", get_falso)
    monkeypatch.setattr(modulo.time, "sleep", lambda _s: None)
    llamar()
    assert enviados and enviados[0]["User-Agent"] == "Equipo Prueba pruebas@example.com"
