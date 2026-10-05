"""BUG-2026-10-05-01, seguridad: la cola guarda datos de reuniones (participantes, empresas).

Borrar una organización no puede dejar trabajos huérfanos con esos datos, ni tocar los de
otra organización. Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia``).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import DossierGenerationJob


def test_borrar_una_organizacion_borra_sus_trabajos_y_no_los_de_otra(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        orgs = [
            conn.execute(
                text("INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id"),
                {"n": n, "s": n},
            ).scalar_one()
            for n in ("org-borrada", "org-ajena")
        ]
        user_id = conn.execute(
            text("INSERT INTO users (email) VALUES ('cola@example.test') RETURNING id")
        ).scalar_one()

    with Session(pg_vacia) as db:
        for org_id in orgs:
            db.add(
                DossierGenerationJob(
                    organization_id=org_id,
                    requested_by_user_id=user_id,
                    reunion_snapshot={"participantes": "Ana Prueba <ana@example.test>"},
                )
            )
        db.commit()

    with pg_vacia.begin() as conn:
        conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": orgs[0]})

    with pg_vacia.connect() as conn:
        por_org = dict(
            conn.execute(
                text("SELECT organization_id, count(*) FROM dossier_generation_jobs GROUP BY 1")
            ).all()
        )
    assert orgs[0] not in por_org
    assert por_org[orgs[1]] == 1
