"""BUG-2026-10-05-01: la cola de trabajos (`dossier_generation_jobs`) entra al esquema versionado.

Antes solo la creaba ``create_all`` del ORM al arrancar: una base hecha con
``alembic upgrade head`` y ``DATABASE_AUTO_CREATE_TABLES=0`` no la tenía.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from dossier.db import schema_patches

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION_S45 = "b7e2d4f1a9c3"


def _scripts() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_la_migracion_de_la_cola_es_la_cabeza_y_sigue_a_s45():
    scripts = _scripts()
    cabezas = scripts.get_heads()

    assert len(cabezas) == 1
    assert scripts.get_revision(cabezas[0]).down_revision == REVISION_S45


def test_el_ddl_de_la_cola_es_idempotente():
    """Las bases existentes ya tienen la tabla (create_all): crearla de nuevo no debe fallar."""
    assert schema_patches.JOB_QUEUE_PATCHES
    for sql in schema_patches.JOB_QUEUE_PATCHES:
        normalizado = " ".join(sql.upper().split())
        assert "IF NOT EXISTS" in normalizado, sql


def test_el_arranque_aplica_tambien_la_cola():
    ejecutadas: list[str] = []

    class _Conn:
        def execute(self, stmt):
            ejecutadas.append(str(stmt))

    class _Engine:
        @contextmanager
        def begin(self):
            yield _Conn()

    schema_patches.apply_schema_patches(_Engine())

    for sql in schema_patches.JOB_QUEUE_PATCHES:
        assert sql in ejecutadas


def test_la_linea_base_y_s45_no_absorben_la_cola():
    """Las migraciones anteriores leen sus tuplas en vivo: deben seguir siendo fijas."""
    cola = set(schema_patches.JOB_QUEUE_PATCHES)
    assert not cola & set(schema_patches._PATCHES)
    assert not cola & set(schema_patches.DOSSIER_ENTITIES_PATCHES)
