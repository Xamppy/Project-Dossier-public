"""BUG-2026-10-05-01: la cola de trabajos (`dossier_generation_jobs`) entra a Alembic.

Revision ID: c4d8a2f6b1e9
Revises: b7e2d4f1a9c3
Create Date: 2026-10-05

La tabla no estaba en Migracion.md, ni en la línea base, ni en los parches: solo la
creaba ``create_all`` del ORM al arrancar la app. Una base hecha con
``alembic upgrade head`` y ``DATABASE_AUTO_CREATE_TABLES=0`` no tenía la cola, y la
generación asíncrona fallaba.

El DDL es idempotente (``IF NOT EXISTS``) porque las bases reales ya tienen la tabla,
creada por la app. Igual que S4.5, se reutiliza la tupla de ``schema_patches``, que la
app también aplica al arrancar.
"""
from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "c4d8a2f6b1e9"
down_revision = "b7e2d4f1a9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from dossier.db.schema_patches import JOB_QUEUE_PATCHES

    for sql in JOB_QUEUE_PATCHES:
        op.execute(text(sql))


def downgrade() -> None:
    # Borra también los trabajos que hubiera: es la tabla que esta revisión aporta.
    op.execute(text("DROP TABLE IF EXISTS dossier_generation_jobs"))
