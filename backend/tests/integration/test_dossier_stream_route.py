"""Tests de integracion - S4.8: ruta SSE /dossier-generation-jobs/{id}/stream.

Camino feliz (200, text/event-stream, frames reales). El acceso y el
aislamiento por organización/usuario están en
tests/security/test_dossier_stream_seguridad.py.

Primera prueba de este repo con TestClient: no hay Postgres real en el
entorno de pruebas (ver docs/dev/testing-policy.md §3, que ya preveía esta
carpeta aunque nadie la hubiera usado todavía).
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from dossier.api.app import app
from dossier.api.auth_routes import get_current_user_and_org, get_db_if_configured
from dossier.db.models import DossierGenerationJob, Organization, User


class _FakeSession:
    def __init__(self, job=None):
        self._job = job

    def get(self, model, pk):
        if model is DossierGenerationJob and self._job is not None and self._job.id == pk:
            return self._job
        return None

    def expire_all(self):
        pass


def _override_db(fake_session: _FakeSession):
    def _dep():
        yield fake_session

    return _dep


def test_stream_job_propio_devuelve_text_event_stream():
    org = Organization(id=uuid.uuid4(), name="Propia", slug="propia")
    user = User(id=uuid.uuid4(), email="user@test.local")
    job = DossierGenerationJob(
        id=uuid.uuid4(),
        organization_id=org.id,
        requested_by_user_id=user.id,
        status="completed",
    )

    app.dependency_overrides[get_db_if_configured] = _override_db(_FakeSession(job))
    app.dependency_overrides[get_current_user_and_org] = lambda: (user, org)
    try:
        with TestClient(app).stream(
            "GET", f"/dossier-generation-jobs/{job.id}/stream"
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            texto = b"".join(resp.iter_bytes()).decode("utf-8")
    finally:
        app.dependency_overrides.clear()
    assert "event: job_completed" in texto
