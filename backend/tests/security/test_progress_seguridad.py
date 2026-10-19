"""S5.10 · BE5 y BE11: el progreso no filtra datos ni se cruza entre usuarios o jobs.

Rutas reales con Postgres de prueba (``TEST_DATABASE_URL``) y el bus en memoria.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.api.app import app
from dossier.api.auth_routes import get_current_user_and_org, get_db_if_configured
from dossier.db.models import DossierGenerationJob, Organization, User
from dossier.services import dossier_generation_job_service as servicio
from dossier.services import dossier_progress_events as bus
from dossier.services import dossier_progress_model as m
from dossier.services import pdl_research, person_research_service
from dossier.services.dossier_job_progress import JobProgress
from dossier.services.dossier_progress_stream import stream_job_events

CORREO_PEDIDO = "ana.privada@empresa.example"
LINKEDIN_PEDIDO = "https://www.linkedin.com/in/ana-privada"
CORREO_PDL = "ana@personal.example"
TELEFONO_PDL = "+56 9 3333 4444"


@pytest.fixture
def base(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id = conn.execute(
            text(
                "INSERT INTO organizations (name, slug, plan, credits_balance) "
                "VALUES ('Org', 'org-seg', 'pro', 100) RETURNING id"
            )
        ).scalar_one()
        dueno = conn.execute(text("INSERT INTO users (email) VALUES ('duena@example.com') RETURNING id")).scalar_one()
        otro = conn.execute(text("INSERT INTO users (email) VALUES ('otro@example.com') RETURNING id")).scalar_one()
    return pg_vacia, org_id, dueno, otro


def _job_persona(engine, org_id, user_id):
    with Session(engine) as db:
        job = DossierGenerationJob(
            organization_id=org_id,
            requested_by_user_id=user_id,
            status="queued",
            job_type="person_manual",
            external_event_id=f"person:{uuid.uuid4().hex}",
            reunion_snapshot={
                "person_request": {
                    "full_name": "Ana Prueba",
                    "email": CORREO_PEDIDO,
                    "linkedin_url": LINKEDIN_PEDIDO,
                    "research_source": "pdl",
                    "max_profiles": 1,
                }
            },
            depth_level="basic",
            credits_estimated=1,
        )
        db.add(job)
        db.commit()
        return job.id


@pytest.fixture
def pdl_con_contactos(monkeypatch):
    class Pdl:
        def person_enrich(self, params):
            return {
                "data": {
                    "id": "pdl-secreto-9",
                    "full_name": "Ana Prueba",
                    "job_title": "Directora",
                    "emails": [{"address": CORREO_PDL}],
                    "phone_numbers": [TELEFONO_PDL],
                    "mobile_phone": TELEFONO_PDL,
                },
                "likelihood": 9,
            }

        def person_search(self, **_):
            return {"data": [], "total": 0}

    monkeypatch.setattr(pdl_research, "PdlClient", Pdl)
    monkeypatch.setattr(person_research_service, "deepseek_api_key", lambda: "")


def test_el_progreso_y_sus_eventos_no_llevan_contactos_ni_datos_crudos(base, pdl_con_contactos):
    engine, org_id, dueno, _ = base
    job_id = _job_persona(engine, org_id, dueno)
    try:
        with Session(engine) as db:
            servicio.process_dossier_generation_job(db, job_id)
        with Session(engine) as db:
            progreso = servicio.serialize_job(db.get(DossierGenerationJob, job_id))["progress"]
        eventos = json.dumps([d for _, e, d in bus.events_since(job_id, 0) if e != "job_failed"])
    finally:
        bus.forget(job_id)

    perfiles = next(p for p in progreso["scopes"][0]["partial_results"] if p["section"] == "person_profiles")
    assert perfiles["data"]["profiles"][0]["full_name"] == "Ana Prueba", "el parcial sí existe"
    for texto in (json.dumps(progreso), eventos):
        for prohibido in (CORREO_PEDIDO, LINKEDIN_PEDIDO, CORREO_PDL, TELEFONO_PDL, "pdl-secreto-9"):
            assert prohibido not in texto


def _cliente(engine, user_id, org_id):
    def db_override():
        with Session(engine) as db:
            yield db

    with Session(engine) as db:
        user = db.get(User, user_id)
        org = db.get(Organization, org_id)
        db.expunge_all()
    app.dependency_overrides[get_db_if_configured] = db_override
    app.dependency_overrides[get_current_user_and_org] = lambda: (user, org)
    return TestClient(app)


def test_la_duena_ve_el_progreso_y_otro_usuario_de_la_org_recibe_404(base):
    engine, org_id, dueno, otro = base
    job_id = _job_persona(engine, org_id, dueno)
    JobProgress(job_id, servicio.SqlProgressStore(lambda: Session(engine, expire_on_commit=False), servicio.serialize_job),
                publish=lambda *a: None).declare([m.person_scope("person:0", "Ana Prueba", "pdl")])
    try:
        propia = _cliente(engine, dueno, org_id).get(f"/dossier-generation-jobs/{job_id}")
        listado = _cliente(engine, dueno, org_id).get("/dossier-generation-jobs")
        ajena = _cliente(engine, otro, org_id).get(f"/dossier-generation-jobs/{job_id}")
        ajeno_listado = _cliente(engine, otro, org_id).get("/dossier-generation-jobs")
    finally:
        app.dependency_overrides.clear()

    assert propia.status_code == 200
    assert propia.json()["progress"]["scopes"][0]["scope_id"] == "person:0"
    assert [j["id"] for j in listado.json()["jobs"]] == [str(job_id)]
    assert listado.json()["jobs"][0]["progress"] is not None
    assert ajena.status_code == 404 and "progress" not in ajena.text
    assert ajeno_listado.json()["jobs"] == []


def test_los_eventos_de_un_job_no_llegan_al_stream_de_otro():
    job_a, job_b = uuid.uuid4(), uuid.uuid4()
    try:
        bus.publish_if_changed(job_a, "stage_progress", {"job_id": str(job_a), "stage_id": "person.pdl_enrich"})
        bus.publish_if_changed(job_a, "partial_result", {"job_id": str(job_a), "section": "person_profiles"})
        frames = list(
            stream_job_events(
                job_b,
                lambda: {"id": str(job_b), "status": "completed"},
                max_seconds=0,
            )
        )
    finally:
        bus.forget(job_a)
        bus.forget(job_b)

    assert len(frames) == 1 and str(job_a) not in frames[0]
