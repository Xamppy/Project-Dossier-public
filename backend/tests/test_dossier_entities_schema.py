"""S4.5: las tablas de alertas, trayectoria y menciones cubren el contrato de S4.1.

Las tres tablas ya existían en la línea base (``dossier_alerts``,
``dossier_career_entries``, ``dossier_media_mentions``) sin que nada las usara;
S4.5 las extiende en vez de crear tablas paralelas. Ver
docs/architecture/estrategia-migracion-modelo-datos.md §2.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from dossier.db import models, schema_patches
from dossier.schemas.dossier_executive_payload import RiskSeverity

BACKEND_ROOT = Path(__file__).resolve().parents[1]
LINEA_BASE = "a3f1c9e2b7d4"


# Caso normal: toda severidad del contrato cabe en la columna.
def test_niveles_de_alerta_aceptan_toda_severidad_del_contrato():
    assert {s.value for s in RiskSeverity} <= set(models.ALERT_LEVELS)


# Borde: ampliar el CHECK no puede dejar inválidas las filas heredadas.
def test_niveles_heredados_se_conservan():
    assert {"critical", "warning"} <= set(models.ALERT_LEVELS)


@pytest.mark.parametrize(
    ("modelo", "columnas"),
    [
        ("DossierAlert", {"dossier_id", "title", "level", "message", "sources"}),
        (
            "DossierMediaMention",
            {
                "dossier_id",
                "title",
                "source_name",
                "published_at",
                "summary",
                "url",
                "source_citation",
                "query_context",
            },
        ),
        (
            "DossierCareerEntry",
            {
                "dossier_id",
                "job_title",
                "company_name",
                "start_date_text",
                "end_date_text",
                "is_current",
                "source_citation",
            },
        ),
    ],
)
def test_modelo_cubre_los_campos_del_contrato(modelo, columnas):
    tabla = getattr(models, modelo).__table__
    assert columnas <= set(tabla.columns.keys())


@pytest.mark.parametrize("modelo", ["DossierAlert", "DossierMediaMention", "DossierCareerEntry"])
def test_filas_se_borran_con_su_dossier(modelo):
    """La retención (S6.5) depende de que borrar el dossier arrastre sus filas."""
    fk = next(iter(getattr(models, modelo).__table__.c.dossier_id.foreign_keys))
    assert fk.column.table.name == "dossiers"
    assert fk.ondelete == "CASCADE"


def test_arranque_aplica_tambien_los_parches_de_entidades():
    ejecutadas: list[str] = []

    class _Conn:
        def execute(self, stmt):
            ejecutadas.append(str(stmt))

    class _Engine:
        @contextmanager
        def begin(self):
            yield _Conn()

    schema_patches.apply_schema_patches(_Engine())

    assert schema_patches.DOSSIER_ENTITIES_PATCHES
    for sql in schema_patches.DOSSIER_ENTITIES_PATCHES:
        assert sql in ejecutadas


def test_linea_base_no_absorbe_los_parches_de_entidades():
    """La línea base itera ``_PATCHES`` en vivo: si S4.5 cayera ahí, dejaría de ser fija."""
    assert not set(schema_patches.DOSSIER_ENTITIES_PATCHES) & set(schema_patches._PATCHES)


# Error típico: un ADD COLUMN sin IF NOT EXISTS rompe el arranque la segunda vez.
def test_parches_de_entidades_son_idempotentes_en_texto():
    for sql in schema_patches.DOSSIER_ENTITIES_PATCHES:
        if "ADD COLUMN" in sql.upper():
            assert "IF NOT EXISTS" in sql.upper(), sql


def test_migracion_s45_es_la_unica_cabeza_y_sigue_a_la_linea_base():
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(cfg)

    cabezas = scripts.get_heads()
    assert len(cabezas) == 1
    assert scripts.get_revision(cabezas[0]).down_revision == LINEA_BASE
