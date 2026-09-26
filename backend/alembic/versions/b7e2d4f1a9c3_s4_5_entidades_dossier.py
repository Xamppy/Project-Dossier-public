"""S4.5: extiende alertas, menciones y trayectoria al contrato de S4.1.

Revision ID: b7e2d4f1a9c3
Revises: a3f1c9e2b7d4
Create Date: 2026-09-26

El diseño de S0.10 proponía tres tablas nuevas (``dossier_risk_alerts``,
``dossier_career_positions``, ``dossier_press_mentions``), pero la línea base
ya trae ``dossier_alerts``, ``dossier_career_entries`` y
``dossier_media_mentions`` con el mismo propósito y sin uso en el código. Se
extienden esas en vez de duplicar el concepto (decisión registrada en
docs/architecture/estrategia-migracion-modelo-datos.md §2).

Igual que la línea base con ``_PATCHES``, se reutiliza
``DOSSIER_ENTITIES_PATCHES``: es el mismo DDL idempotente que la app aplica al
arrancar sobre bases sin ``alembic_version``.
"""
from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "b7e2d4f1a9c3"
down_revision = "a3f1c9e2b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from dossier.db.schema_patches import DOSSIER_ENTITIES_PATCHES

    for sql in DOSSIER_ENTITIES_PATCHES:
        op.execute(text(sql))


def downgrade() -> None:
    # Filas con niveles del contrato violarían el CHECK original: se descartan
    # antes de restaurarlo, porque no tienen equivalente en 'critical'/'warning'.
    op.execute(text("DELETE FROM dossier_alerts WHERE level NOT IN ('critical', 'warning')"))
    op.execute(text("ALTER TABLE dossier_alerts DROP CONSTRAINT IF EXISTS dossier_alerts_level_check"))
    op.execute(
        text(
            "ALTER TABLE dossier_alerts ADD CONSTRAINT dossier_alerts_level_check "
            "CHECK (level IN ('critical', 'warning'))"
        )
    )
    op.execute(text("ALTER TABLE dossier_alerts DROP COLUMN IF EXISTS sources"))
    op.execute(text("ALTER TABLE dossier_alerts DROP COLUMN IF EXISTS title"))
    op.execute(text("ALTER TABLE dossier_media_mentions DROP COLUMN IF EXISTS query_context"))
    op.execute(text("ALTER TABLE dossier_media_mentions DROP COLUMN IF EXISTS source_citation"))
    op.execute(text("ALTER TABLE dossier_career_entries DROP COLUMN IF EXISTS source_citation"))
    op.execute(text("ALTER TABLE dossier_career_entries DROP COLUMN IF EXISTS end_date_text"))
    op.execute(text("ALTER TABLE dossier_career_entries DROP COLUMN IF EXISTS start_date_text"))
