"""S4.5 contra Postgres real: migración 0002 de ida y vuelta, y el camino de arranque.

Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import DossierAlert, DossierCareerEntry, DossierMediaMention
from dossier.db.schema_patches import apply_schema_patches
from dossier.schemas.dossier_executive_payload import SourceCitation, SourceType

LINEA_BASE = "a3f1c9e2b7d4"

COLUMNAS_NUEVAS = {
    "dossier_alerts": {"title", "sources"},
    "dossier_media_mentions": {"source_citation", "query_context"},
    "dossier_career_entries": {"start_date_text", "end_date_text", "source_citation"},
}


def _columnas(engine, tabla: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(tabla)}


def _cita() -> dict:
    return SourceCitation(
        source_type=SourceType.gdelt_news,
        source_name="GDELT",
        url="https://example.test/nota",
        retrieved_at=datetime(2026, 9, 26, tzinfo=UTC),
    ).model_dump(mode="json")


def test_upgrade_head_agrega_las_columnas_del_contrato(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")

    for tabla, nuevas in COLUMNAS_NUEVAS.items():
        assert nuevas <= _columnas(pg_vacia, tabla), tabla


def test_modelos_orm_leen_y_escriben_el_payload_del_contrato(
    pg_vacia, alembic_cfg, sembrar_dossier
):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        dossier_id = sembrar_dossier(conn)

    with Session(pg_vacia) as s:
        s.add_all(
            [
                DossierAlert(
                    dossier_id=dossier_id,
                    level="high",
                    title="Litigio abierto",
                    message="Demanda vigente contra la empresa.",
                    sources=[_cita()],
                ),
                DossierMediaMention(
                    dossier_id=dossier_id,
                    title="La empresa anuncia fusión",
                    source_name="Diario de Prueba",
                    url="https://example.test/nota",
                    summary="Resumen breve.",
                    source_citation=_cita(),
                    query_context="Empresa de Prueba SA",
                ),
                DossierCareerEntry(
                    dossier_id=dossier_id,
                    company_name="Empresa de Prueba SA",
                    job_title="Gerente general",
                    start_date_text="2019",
                    is_current=True,
                    source_citation=_cita(),
                ),
            ]
        )
        s.commit()

        alerta = s.query(DossierAlert).one()
        assert alerta.sources[0]["source_type"] == "gdelt_news"
        assert s.query(DossierMediaMention).one().query_context == "Empresa de Prueba SA"
        assert s.query(DossierCareerEntry).one().start_date_text == "2019"


def test_downgrade_quita_columnas_y_restaura_el_check_original(
    pg_vacia, alembic_cfg, sembrar_dossier
):
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, LINEA_BASE)

    for tabla, nuevas in COLUMNAS_NUEVAS.items():
        assert not nuevas & _columnas(pg_vacia, tabla), tabla

    with pytest.raises(IntegrityError), pg_vacia.begin() as conn:
        dossier_id = sembrar_dossier(conn)
        conn.execute(
            text("INSERT INTO dossier_alerts (dossier_id, level, message) VALUES (:d, 'high', 'x')"),
            {"d": dossier_id},
        )


def test_arranque_de_la_app_extiende_una_base_existente_y_es_idempotente(pg_vacia, alembic_cfg):
    """Bases como la local de desarrollo no tienen ``alembic_version``: las
    extiende ``apply_schema_patches`` en cada arranque, así que debe tolerar
    correr dos veces seguidas."""
    command.upgrade(alembic_cfg, LINEA_BASE)

    apply_schema_patches(pg_vacia)
    apply_schema_patches(pg_vacia)

    for tabla, nuevas in COLUMNAS_NUEVAS.items():
        assert nuevas <= _columnas(pg_vacia, tabla), tabla
