"""S4.6, integración: el pipeline de persona persiste risk_alerts/conversation_starters
en las tablas relacionales, en la misma transacción que ``dossiers``.

Sigue el patrón de
``test_person_research_structured.py::test_pipeline_guarda_el_payload_sin_tocar_body_ni_billing``.
Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import Organization, User
from dossier.schemas.person_research import PersonResearchRequest
from dossier.services import person_research_pipeline

PERFIL = {
    "full_name": "Ana Prueba",
    "job_title": "Gerente general",
    "job_company_name": "Empresa de Prueba SA",
    "linkedin_urls": ["https://example.test/ana"],
}


def _resultado_investigacion(payload: dict, md: str = "## Resumen\n\nAna Prueba.") -> dict:
    return {
        "filters_applied": {"research_source": "pdl"},
        "profiles": [dict(PERFIL)],
        "profile_urls": [],
        "warnings": [],
        "llm_analysis_markdown": md,
        "executive_payload": payload,
    }


def _sembrar_org_y_usuario(conn, sufijo: str):
    org_id = conn.execute(
        text("INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id"),
        {"n": f"Org {sufijo}", "s": f"org-{sufijo}"},
    ).scalar_one()
    user_id = conn.execute(
        text("INSERT INTO users (email) VALUES (:e) RETURNING id"),
        {"e": f"{sufijo}@example.test"},
    ).scalar_one()
    return org_id, user_id


def _filas(conn, tabla: str, dossier_id) -> int:
    return conn.execute(
        text(f"SELECT count(*) FROM {tabla} WHERE dossier_id = :d"), {"d": dossier_id}
    ).scalar_one()


def test_pipeline_escribe_alertas_e_ice_breakers_del_payload(pg_vacia, alembic_cfg, monkeypatch):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id, user_id = _sembrar_org_y_usuario(conn, "s46")

    payload = {
        "schema_version": "2.0.0",
        "meeting_context": {},
        "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
        "participants": [],
        "risk_alerts": [
            {
                "title": "Litigio abierto",
                "severity": "high",
                "description": "Demanda vigente contra la empresa.",
                "sources": [],
            }
        ],
        "conversation_starters": [
            {
                "topic": "Expansión",
                "rationale": "Planea abrir oficina nueva.",
                "suggested_opener": "¿Cómo va la oficina nueva?",
            }
        ],
    }
    monkeypatch.setattr(
        person_research_pipeline, "run_person_research", lambda *a, **k: _resultado_investigacion(payload)
    )

    with Session(pg_vacia) as db:
        org = db.get(Organization, org_id)
        user = db.get(User, user_id)
        respuesta = person_research_pipeline.run_person_research_and_persist(
            db, user=user, org=org, body=PersonResearchRequest(full_name="Ana Prueba")
        )

    dossier_id = respuesta["saved_dossier"]["id"]
    with pg_vacia.connect() as conn:
        assert _filas(conn, "dossier_alerts", dossier_id) == 1
        assert _filas(conn, "dossier_ice_breakers", dossier_id) == 1
        alerta = conn.execute(
            text("SELECT level, message FROM dossier_alerts WHERE dossier_id = :d"), {"d": dossier_id}
        ).mappings().one()
        assert alerta["level"] == "high"
        starter = conn.execute(
            text("SELECT content FROM dossier_ice_breakers WHERE dossier_id = :d"), {"d": dossier_id}
        ).mappings().one()
        assert starter["content"] == "¿Cómo va la oficina nueva?"


def test_pipeline_sin_payload_no_escribe_filas(pg_vacia, alembic_cfg, monkeypatch):
    """Respaldo Markdown (sin contrato estructurado): no hay filas que escribir."""
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id, user_id = _sembrar_org_y_usuario(conn, "s46b")

    monkeypatch.setattr(
        person_research_pipeline,
        "run_person_research",
        lambda *a, **k: _resultado_investigacion(None, md="## Informe libre"),
    )

    with Session(pg_vacia) as db:
        org = db.get(Organization, org_id)
        user = db.get(User, user_id)
        respuesta = person_research_pipeline.run_person_research_and_persist(
            db, user=user, org=org, body=PersonResearchRequest(full_name="Ana Prueba")
        )

    dossier_id = respuesta["saved_dossier"]["id"]
    with pg_vacia.connect() as conn:
        assert _filas(conn, "dossier_alerts", dossier_id) == 0
        assert _filas(conn, "dossier_ice_breakers", dossier_id) == 0


def test_pipeline_al_reemplazar_sustituye_las_filas_en_vez_de_duplicarlas(
    pg_vacia, alembic_cfg, monkeypatch
):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id, user_id = _sembrar_org_y_usuario(conn, "s46c")

    payload_1 = {
        "schema_version": "2.0.0",
        "meeting_context": {},
        "executive_summary": "Primer resumen ejecutivo suficientemente largo.",
        "participants": [],
        "risk_alerts": [
            {"title": "A", "severity": "high", "description": "Primera alerta.", "sources": []}
        ],
        "conversation_starters": [
            {"topic": "t", "rationale": "r", "suggested_opener": "Primera idea"}
        ],
    }
    monkeypatch.setattr(
        person_research_pipeline, "run_person_research", lambda *a, **k: _resultado_investigacion(payload_1)
    )
    with Session(pg_vacia) as db:
        org = db.get(Organization, org_id)
        user = db.get(User, user_id)
        primera = person_research_pipeline.run_person_research_and_persist(
            db, user=user, org=org, body=PersonResearchRequest(full_name="Ana Prueba")
        )
    dossier_id = primera["saved_dossier"]["id"]

    payload_2 = {
        "schema_version": "2.0.0",
        "meeting_context": {},
        "executive_summary": "Segundo resumen ejecutivo suficientemente largo.",
        "participants": [],
        "risk_alerts": [],
        "conversation_starters": [
            {"topic": "t2", "rationale": "r2", "suggested_opener": "Segunda idea"}
        ],
    }
    monkeypatch.setattr(
        person_research_pipeline, "run_person_research", lambda *a, **k: _resultado_investigacion(payload_2)
    )
    with Session(pg_vacia) as db:
        org = db.get(Organization, org_id)
        user = db.get(User, user_id)
        segunda = person_research_pipeline.run_person_research_and_persist(
            db,
            user=user,
            org=org,
            body=PersonResearchRequest(full_name="Ana Prueba", replace_dossier_id=dossier_id),
        )

    assert segunda["saved_dossier"]["id"] == dossier_id
    with pg_vacia.connect() as conn:
        assert _filas(conn, "dossier_alerts", dossier_id) == 0
        assert _filas(conn, "dossier_ice_breakers", dossier_id) == 1
        starter = conn.execute(
            text("SELECT content FROM dossier_ice_breakers WHERE dossier_id = :d"), {"d": dossier_id}
        ).mappings().one()
        assert starter["content"] == "Segunda idea"
