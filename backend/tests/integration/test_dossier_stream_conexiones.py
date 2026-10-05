"""S4.8 (seguimiento), contra Postgres real: conexiones del canal SSE y publicación del worker.

Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import DossierGenerationJob
from dossier.services import dossier_progress_events as bus


@pytest.fixture
def job_en_cola(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    # `dossier_generation_jobs` no está en Alembic ni en Migracion.md: solo la crea el ORM
    # con create_all al arrancar la app (hallazgo registrado en progress.md). Se replica aquí.
    DossierGenerationJob.__table__.create(pg_vacia, checkfirst=True)
    with pg_vacia.begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name, slug) VALUES ('Org', 'org-sse') RETURNING id")
        ).scalar_one()
        otra_org = conn.execute(
            text("INSERT INTO organizations (name, slug) VALUES ('Otra', 'org-otra') RETURNING id")
        ).scalar_one()
        user_id = conn.execute(
            text("INSERT INTO users (email) VALUES ('sse@example.test') RETURNING id")
        ).scalar_one()
    with Session(pg_vacia) as db:
        job = DossierGenerationJob(
            organization_id=org_id,
            requested_by_user_id=user_id,
            status="queued",
            job_type="person_manual",
            reunion_snapshot={"person_request": {"full_name": "Ana Prueba"}},
        )
        db.add(job)
        db.commit()
        job_id = job.id
    yield {"job_id": job_id, "org_id": org_id, "otra_org": otra_org, "user_id": user_id}
    bus.forget(job_id)


def test_el_lector_del_stream_no_retiene_la_conexion_entre_consultas(pg_vacia, job_en_cola):
    """Antes cada cliente SSE retenía una conexión del pool durante todo el stream."""
    from dossier.api.dossier_stream_routes import lector_de_job

    with Session(pg_vacia) as db:
        leer = lector_de_job(
            db, job_en_cola["job_id"], user_id=job_en_cola["user_id"], org_id=job_en_cola["org_id"]
        )
        assert leer()["status"] == "queued"
        assert not db.in_transaction()
        assert pg_vacia.pool.checkedout() == 0


def test_el_lector_no_entrega_jobs_de_otra_organizacion(pg_vacia, job_en_cola):
    from dossier.api.dossier_stream_routes import lector_de_job

    with Session(pg_vacia) as db:
        leer = lector_de_job(
            db, job_en_cola["job_id"], user_id=job_en_cola["user_id"], org_id=job_en_cola["otra_org"]
        )
        assert leer() is None


def test_el_worker_publica_en_el_bus_cada_cambio_de_estado(pg_vacia, job_en_cola, monkeypatch):
    from dossier.services import dossier_generation_job_service as servicio

    monkeypatch.setattr(
        servicio,
        "run_person_research_and_persist",
        lambda db, **_: {"saved_dossier": {"id": "d1", "status": "complete", "credits_consumed": 1}},
    )

    with Session(pg_vacia) as db:
        servicio.process_dossier_generation_job(db, job_en_cola["job_id"])

    eventos = [(e, d["status"]) for _, e, d in bus.events_since(job_en_cola["job_id"], 0)]
    assert ("job_status", "running") in eventos
    assert eventos[-1] == ("job_completed", "completed")


def test_el_worker_publica_el_fallo(pg_vacia, job_en_cola, monkeypatch):
    from dossier.services import dossier_generation_job_service as servicio

    def explota(db, **_):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr(servicio, "run_person_research_and_persist", explota)

    with Session(pg_vacia) as db:
        servicio.process_dossier_generation_job(db, job_en_cola["job_id"])

    eventos = bus.events_since(job_en_cola["job_id"], 0)
    assert eventos[-1][1] == "job_failed"
