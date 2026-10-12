"""S4.6, seguridad: aislamiento entre dossiers/organizaciones y borrado sin residuos.

``dossier_alerts`` y ``dossier_ice_breakers`` guardan datos derivados de personas
investigadas. Sustituir un dossier no puede tocar filas de otro, y borrar un
dossier no puede dejar sus alertas o ideas de conversación huérfanas.

Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.services.dossier_entities_writer import escribir_entidades_ejecutivas

PAYLOAD = {
    "risk_alerts": [
        {"title": "Alerta", "severity": "high", "description": "Detalle.", "sources": []}
    ],
    "conversation_starters": [
        {"topic": "t", "rationale": "r", "suggested_opener": "Idea"}
    ],
}


def _filas(conn, tabla: str, dossier_id) -> int:
    return conn.execute(
        text(f"SELECT count(*) FROM {tabla} WHERE dossier_id = :d"), {"d": dossier_id}
    ).scalar_one()


def test_reemplazar_un_dossier_no_toca_las_filas_de_otro(pg_vacia, alembic_cfg, sembrar_dossier):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        propio = sembrar_dossier(conn)
        ajeno = sembrar_dossier(conn)

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=propio, payload=PAYLOAD, reemplazo=False)
        escribir_entidades_ejecutivas(db, dossier_id=ajeno, payload=PAYLOAD, reemplazo=False)
        db.commit()

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=propio, payload=None, reemplazo=True)
        db.commit()

    with pg_vacia.connect() as conn:
        assert _filas(conn, "dossier_alerts", propio) == 0
        assert _filas(conn, "dossier_ice_breakers", propio) == 0
        assert _filas(conn, "dossier_alerts", ajeno) == 1
        assert _filas(conn, "dossier_ice_breakers", ajeno) == 1


def test_borrar_un_dossier_no_deja_ice_breakers_residuales_ni_toca_otra_organizacion(
    pg_vacia, alembic_cfg, sembrar_dossier
):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        borrado = sembrar_dossier(conn)
        ajeno = sembrar_dossier(conn)

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=borrado, payload=PAYLOAD, reemplazo=False)
        escribir_entidades_ejecutivas(db, dossier_id=ajeno, payload=PAYLOAD, reemplazo=False)
        db.commit()

    with pg_vacia.begin() as conn:
        conn.execute(text("DELETE FROM dossiers WHERE id = :d"), {"d": borrado})

    with pg_vacia.connect() as conn:
        assert _filas(conn, "dossier_alerts", borrado) == 0
        assert _filas(conn, "dossier_ice_breakers", borrado) == 0
        assert _filas(conn, "dossier_alerts", ajeno) == 1
        assert _filas(conn, "dossier_ice_breakers", ajeno) == 1


def test_ice_breakers_tiene_borrado_en_cascada_con_su_dossier(pg_vacia, alembic_cfg):
    """El DDL de ``dossier_ice_breakers`` (sin modelo ORM) debe declarar ON DELETE
    CASCADE igual que las tablas de S4.5, o la retención (S6.5) dejaría huérfanos."""
    command.upgrade(alembic_cfg, "head")

    with pg_vacia.connect() as conn:
        regla = conn.execute(
            text(
                "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
                "JOIN information_schema.table_constraints tc "
                "  ON tc.constraint_name = rc.constraint_name "
                "WHERE tc.table_name = 'dossier_ice_breakers'"
            )
        ).scalar_one()

    assert regla == "CASCADE"
