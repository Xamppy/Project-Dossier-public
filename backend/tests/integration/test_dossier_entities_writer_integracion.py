"""S4.6, integración: escritura relacional del payload ejecutivo contra Postgres real.

Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.services.dossier_entities_writer import escribir_entidades_ejecutivas

PAYLOAD = {
    "risk_alerts": [
        {
            "title": "Litigio abierto",
            "severity": "high",
            "description": "Demanda vigente contra la empresa.",
            "sources": [{"source_type": "companies_house", "source_name": "CH"}],
        },
        {
            "title": "Mora tributaria",
            "severity": "medium",
            "description": "Deuda con el fisco reportada en 2025.",
            "sources": [],
        },
    ],
    "conversation_starters": [
        {
            "topic": "Expansión regional",
            "rationale": "Mencionó planes de abrir oficina en Chile.",
            "suggested_opener": "¿Cómo va la apertura de la oficina en Chile?",
        }
    ],
}


def _alertas(conn, dossier_id) -> list:
    return conn.execute(
        text(
            "SELECT level, title, message, sources FROM dossier_alerts "
            "WHERE dossier_id = :d ORDER BY title"
        ),
        {"d": dossier_id},
    ).mappings().all()


def _ice_breakers(conn, dossier_id) -> list:
    return conn.execute(
        text(
            "SELECT content, sort_order FROM dossier_ice_breakers "
            "WHERE dossier_id = :d ORDER BY sort_order"
        ),
        {"d": dossier_id},
    ).mappings().all()


def test_escribe_alertas_e_ice_breakers_del_payload(pg_vacia, alembic_cfg, sembrar_dossier):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        dossier_id = sembrar_dossier(conn)

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=dossier_id, payload=PAYLOAD, reemplazo=False)
        db.commit()

    with pg_vacia.connect() as conn:
        alertas = _alertas(conn, dossier_id)
        starters = _ice_breakers(conn, dossier_id)

    assert [a["level"] for a in alertas] == ["high", "medium"]
    assert alertas[0]["title"] == "Litigio abierto"
    assert alertas[0]["message"] == "Demanda vigente contra la empresa."
    assert alertas[0]["sources"] == [{"source_type": "companies_house", "source_name": "CH"}]
    assert alertas[1]["sources"] == []
    assert starters == [{"content": "¿Cómo va la apertura de la oficina en Chile?", "sort_order": 0}]


def test_sin_payload_no_escribe_filas(pg_vacia, alembic_cfg, sembrar_dossier):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        dossier_id = sembrar_dossier(conn)

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=dossier_id, payload=None, reemplazo=False)
        db.commit()

    with pg_vacia.connect() as conn:
        assert _alertas(conn, dossier_id) == []
        assert _ice_breakers(conn, dossier_id) == []


def test_reemplazo_sustituye_filas_previas_sin_duplicar(pg_vacia, alembic_cfg, sembrar_dossier):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        dossier_id = sembrar_dossier(conn)

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=dossier_id, payload=PAYLOAD, reemplazo=False)
        db.commit()

    nuevo_payload = {
        "risk_alerts": [
            {
                "title": "Riesgo resuelto",
                "severity": "low",
                "description": "El litigio se cerró en 2026.",
                "sources": [],
            }
        ],
        "conversation_starters": [],
    }
    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(
            db, dossier_id=dossier_id, payload=nuevo_payload, reemplazo=True
        )
        db.commit()

    with pg_vacia.connect() as conn:
        alertas = _alertas(conn, dossier_id)
        starters = _ice_breakers(conn, dossier_id)

    assert [a["title"] for a in alertas] == ["Riesgo resuelto"]
    assert starters == []


def test_reemplazo_sin_payload_nuevo_igual_borra_las_filas_anteriores(
    pg_vacia, alembic_cfg, sembrar_dossier
):
    """Si la regeneración cae al respaldo Markdown, las filas del payload anterior
    ya no describen el dossier actual: deben limpiarse igual que su JSONB."""
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        dossier_id = sembrar_dossier(conn)

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=dossier_id, payload=PAYLOAD, reemplazo=False)
        db.commit()

    with Session(pg_vacia) as db:
        escribir_entidades_ejecutivas(db, dossier_id=dossier_id, payload=None, reemplazo=True)
        db.commit()

    with pg_vacia.connect() as conn:
        assert _alertas(conn, dossier_id) == []
        assert _ice_breakers(conn, dossier_id) == []
