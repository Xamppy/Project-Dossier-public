"""S4.5, seguridad: integridad de severidades y borrado sin datos residuales.

Las tres tablas guardan datos de personas reales investigadas (cargos,
menciones de prensa, alertas). Borrar un dossier —a mano o por la retención de
S6.5— no puede dejar filas huérfanas, ni afectar dossiers de otra organización.

Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError

from alembic import command

TABLAS = ("dossier_alerts", "dossier_media_mentions", "dossier_career_entries")


def _poblar(conn, dossier_id) -> None:
    conn.execute(
        text(
            "INSERT INTO dossier_alerts (dossier_id, level, title, message) "
            "VALUES (:d, 'high', 'Alerta', 'Detalle')"
        ),
        {"d": dossier_id},
    )
    conn.execute(
        text(
            "INSERT INTO dossier_media_mentions (dossier_id, title, url) "
            "VALUES (:d, 'Titular', 'https://example.test/nota')"
        ),
        {"d": dossier_id},
    )
    conn.execute(
        text(
            "INSERT INTO dossier_career_entries (dossier_id, company_name, start_date_text) "
            "VALUES (:d, 'Empresa', '2019')"
        ),
        {"d": dossier_id},
    )


def _filas(conn, tabla: str, dossier_id) -> int:
    return conn.execute(
        text(f"SELECT count(*) FROM {tabla} WHERE dossier_id = :d"), {"d": dossier_id}
    ).scalar_one()


@pytest.mark.parametrize("nivel", ["bogus", "CRITICAL", "", "high'); DROP TABLE dossiers;--"])
def test_check_rechaza_severidades_fuera_del_contrato(
    pg_vacia, alembic_cfg, sembrar_dossier, nivel
):
    command.upgrade(alembic_cfg, "head")

    with pytest.raises((IntegrityError, DataError)), pg_vacia.begin() as conn:
        dossier_id = sembrar_dossier(conn)
        conn.execute(
            text("INSERT INTO dossier_alerts (dossier_id, level, message) VALUES (:d, :n, 'x')"),
            {"d": dossier_id, "n": nivel},
        )

    with pg_vacia.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.dossiers')")).scalar_one()


def test_borrar_un_dossier_no_deja_datos_residuales_ni_toca_otra_organizacion(
    pg_vacia, alembic_cfg, sembrar_dossier
):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        borrado = sembrar_dossier(conn)
        ajeno = sembrar_dossier(conn)
        _poblar(conn, borrado)
        _poblar(conn, ajeno)

    with pg_vacia.begin() as conn:
        conn.execute(text("DELETE FROM dossiers WHERE id = :d"), {"d": borrado})

    with pg_vacia.connect() as conn:
        for tabla in TABLAS:
            assert _filas(conn, tabla, borrado) == 0, tabla
            assert _filas(conn, tabla, ajeno) == 1, tabla
