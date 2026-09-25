"""Tests - S1.6: retiro de la linea no canonica y las rutas legadas (ADR 0001)."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_TOKENS = (
    "gemini_analysis_markdown",
    "synthesize_gemini",
    "DOSSIER_LEGACY_OPENAI",
    "DOSSIER_ENABLE_LEGACY_OPEN_ROUTES",
    "dossier.gemini",
    "openai_dossier",
    "legacy_routes",
)

SCAN_DIRS = (
    REPO_ROOT / "backend" / "src",
    REPO_ROOT / "frontend" / "src",
)

SCAN_EXTS = (".py", ".ts", ".tsx")


def _archivos_a_revisar():
    for carpeta in SCAN_DIRS:
        for ext in SCAN_EXTS:
            yield from carpeta.rglob(f"*{ext}")


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_no_quedan_referencias_a_la_linea_no_canonica(token):
    coincidencias = [
        str(archivo.relative_to(REPO_ROOT))
        for archivo in _archivos_a_revisar()
        if token in archivo.read_text(encoding="utf-8")
    ]
    assert coincidencias == [], (
        f"'{token}' todavia aparece en: {coincidencias} (ver ADR 0001, tarea S1.6)"
    )


def test_gemini_dir_no_existe():
    assert not (REPO_ROOT / "backend" / "src" / "dossier" / "gemini").exists()


def test_openai_dossier_no_existe():
    ruta = REPO_ROOT / "backend" / "src" / "dossier" / "services" / "openai_dossier.py"
    assert not ruta.exists()


def test_legacy_routes_modulo_no_existe():
    ruta = REPO_ROOT / "backend" / "src" / "dossier" / "security" / "legacy_routes.py"
    assert not ruta.exists()


def test_google_calendar_ruta_legada_no_existe():
    ruta = REPO_ROOT / "backend" / "src" / "dossier" / "api" / "google_calendar.py"
    assert not ruta.exists()


def test_app_no_registra_rutas_legadas():
    from dossier.api.app import app

    rutas = {getattr(r, "path", None) for r in app.routes}
    assert "/generar-dossier" not in rutas
    assert "/calendario/generar-dossier-google" not in rutas


def test_grafo_usa_nodo_sintesis_llm():
    from dossier.graphs import corporate_dossier_graph as g

    assert hasattr(g, "_node_synthesize_llm")
    assert not hasattr(g, "_node_synthesize_gemini")
