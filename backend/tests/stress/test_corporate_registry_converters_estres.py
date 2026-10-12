"""Pruebas de estres - S2.3: adaptadores UK/US al modelo comun.

Responde las tres preguntas de docs/dev/testing-policy.md §4: volumen, datos
incompletos y fallo/degradacion aguas arriba del proveedor.
"""
from __future__ import annotations

import time

from dossier.companies_house.converters import perfil_a_registro_corporativo
from dossier.sec_edgar.converters import submissions_a_registro_corporativo

# --------------------------------------------------------------------------
# Volumen
# --------------------------------------------------------------------------


def test_volumen_filing_history_grande_de_companies_house_no_se_degrada():
    perfil = {"company_name": "Acme Ltd", "company_number": "01234567"}
    filing_history = {
        "items": [
            {"date": f"2020-01-{i % 28 + 1:02d}", "type": "AA", "description": f"item {i}"}
            for i in range(5_000)
        ]
    }

    inicio = time.perf_counter()
    cita = perfil_a_registro_corporativo(perfil, filing_history)
    transcurrido = time.perf_counter() - inicio

    assert len(cita.record.presentaciones) == 5_000
    assert transcurrido < 2.0, f"5000 filings tardaron {transcurrido:.2f}s"


def test_volumen_submissions_grande_de_sec_edgar_no_se_degrada():
    n = 5_000
    submissions = {
        "cik": "320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["10-K"] * n,
                "filingDate": ["2023-11-03"] * n,
                "accessionNumber": [f"0000320193-23-{i:06d}" for i in range(n)],
            }
        },
    }

    inicio = time.perf_counter()
    cita = submissions_a_registro_corporativo(submissions, "0000320193")
    transcurrido = time.perf_counter() - inicio

    assert len(cita.record.presentaciones) == n
    assert transcurrido < 2.0, f"{n} filings tardaron {transcurrido:.2f}s"


# --------------------------------------------------------------------------
# Datos incompletos
# --------------------------------------------------------------------------


def test_datos_incompletos_sin_direccion_ni_fechas_ni_estado_no_rompe():
    """Sin fecha de constitucion, sin domicilio, sin estado (empresas disueltas u opacas)."""
    perfil = {"company_name": "Empresa Opaca", "company_number": "99999999"}
    cita = perfil_a_registro_corporativo(perfil, {"items": []})

    assert cita.record.estado is None
    assert cita.record.fecha_constitucion is None
    assert cita.record.domicilio is None
    assert cita.record.presentaciones == []


def test_datos_incompletos_submissions_sin_bloque_filings_no_rompe():
    cita = submissions_a_registro_corporativo({"cik": "1", "name": "X"}, "1")
    assert cita.record.presentaciones == []


def test_filing_history_con_items_de_forma_inesperada_se_ignoran_sin_romper():
    """Un item corrupto o de forma inesperada del proveedor no debe tumbar la conversion."""
    perfil = {"company_name": "Acme Ltd", "company_number": "01234567"}
    filing_history = {"items": [{"date": "2023-01-01", "type": "AA"}, "item-corrupto", None]}
    cita = perfil_a_registro_corporativo(perfil, filing_history)
    assert len(cita.record.presentaciones) == 1


# --------------------------------------------------------------------------
# Fallo/degradacion aguas arriba del proveedor
# --------------------------------------------------------------------------


def test_error_del_proveedor_perfil_vacio_no_impide_registro_minimo():
    """Un perfil vacio (p. ej. tras un 404 aguas arriba ya manejado) no lanza excepcion."""
    cita = perfil_a_registro_corporativo({}, None)
    assert cita.record.razon_social == ""
    assert cita.record.presentaciones == []


def test_error_del_proveedor_submissions_vacio_no_impide_registro_minimo():
    cita = submissions_a_registro_corporativo({}, "")
    assert cita.record.razon_social == ""
    assert cita.record.presentaciones == []
