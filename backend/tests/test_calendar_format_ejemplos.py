"""Tests unitarios — ejemplos de formato de reunión que ve el usuario.

Los ejemplos (mensaje de ayuda cuando no se pudo generar ningún dossier) deben
seguir el mismo formato que el parser entiende y usar solo datos ficticios.
"""
from __future__ import annotations

import re

from dossier.services.calendar_event_dossiers import (
    MENSAJE_FORMATO_SIN_DOSSIER,
    extract_company_from_description,
    extract_numbered_persons_from_description,
)


def _descripcion_del_mensaje() -> str:
    return MENSAJE_FORMATO_SIN_DOSSIER.split("**Descripción:**\n", 1)[1]


def test_el_ejemplo_del_mensaje_lo_entiende_el_parser():
    descripcion = _descripcion_del_mensaje()
    assert extract_company_from_description(descripcion) == "Empresa Ejemplo SpA"
    personas = extract_numbered_persons_from_description(descripcion)
    assert [p["full_name"] for p in personas] == ["Valeria Ruiz Prueba", "Andrea Soto Ejemplo"]


def test_el_mensaje_solo_usa_correos_ficticios():
    correos = re.findall(r"[\w.+-]+@[\w.-]+", MENSAJE_FORMATO_SIN_DOSSIER)
    assert all(c.endswith("@example.com") for c in correos)
