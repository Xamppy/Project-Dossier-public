"""BUG-2026-10-05-01 contra Postgres real: la cola de trabajos en Alembic y en el arranque.

Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

from sqlalchemy import inspect

from alembic import command
from dossier.db.models import DossierGenerationJob
from dossier.db.schema_patches import apply_schema_patches

TABLA = "dossier_generation_jobs"
REVISION_S45 = "b7e2d4f1a9c3"


def _tablas(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_head_crea_la_cola_igual_que_el_orm(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")

    insp = inspect(pg_vacia)
    assert TABLA in insp.get_table_names()
    columnas = {c["name"] for c in insp.get_columns(TABLA)}
    assert columnas == set(DossierGenerationJob.__table__.columns.keys())
    indices = {i["name"] for i in insp.get_indexes(TABLA)}
    assert indices >= {ix.name for ix in DossierGenerationJob.__table__.indexes}
    fk_org = next(fk for fk in insp.get_foreign_keys(TABLA) if fk["referred_table"] == "organizations")
    assert fk_org["options"].get("ondelete") == "CASCADE"


def test_downgrade_quita_la_cola(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, REVISION_S45)

    assert TABLA not in _tablas(pg_vacia)


def test_upgrade_no_falla_si_create_all_ya_la_habia_creado(pg_vacia, alembic_cfg):
    """Así están hoy las bases reales: la tabla existe porque la creó la app al arrancar."""
    command.upgrade(alembic_cfg, REVISION_S45)
    DossierGenerationJob.__table__.create(pg_vacia)

    command.upgrade(alembic_cfg, "head")

    assert TABLA in _tablas(pg_vacia)


def test_el_arranque_crea_la_cola_en_una_base_sin_ella_y_es_idempotente(pg_vacia, alembic_cfg):
    """Base creada antes de esta migración y sin create_all (DATABASE_AUTO_CREATE_TABLES=0)."""
    command.upgrade(alembic_cfg, REVISION_S45)
    assert TABLA not in _tablas(pg_vacia)

    apply_schema_patches(pg_vacia)
    apply_schema_patches(pg_vacia)

    assert TABLA in _tablas(pg_vacia)
