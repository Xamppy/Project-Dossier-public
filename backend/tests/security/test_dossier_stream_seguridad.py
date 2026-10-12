"""Tests de seguridad - S4.8: acceso y aislamiento por organización en la ruta SSE.

Ver tests/integration/test_dossier_stream_route.py para el camino feliz
(200, text/event-stream).
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

    def rollback(self):
        pass


def _override_db(fake_session: _FakeSession):
    def _dep():
        yield fake_session

    return _dep


def test_stream_sin_authorization_header_devuelve_401():
    app.dependency_overrides[get_db_if_configured] = _override_db(_FakeSession())
    try:
        resp = TestClient(app).get(f"/dossier-generation-jobs/{uuid.uuid4()}/stream")
    finally:
        app.dependency_overrides.pop(get_db_if_configured, None)
    assert resp.status_code == 401


def test_stream_job_de_otra_organizacion_devuelve_404_no_403():
    """404, no 403: no se revela que el job existe en otra organización (misma
    convención que api/dossier_job_routes.py)."""
    org_propia = Organization(id=uuid.uuid4(), name="Propia", slug="propia")
    org_ajena_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), email="user@test.local")
    job_ajeno = DossierGenerationJob(
        id=uuid.uuid4(),
        organization_id=org_ajena_id,
        requested_by_user_id=uuid.uuid4(),
        status="running",
    )

    app.dependency_overrides[get_db_if_configured] = _override_db(_FakeSession(job_ajeno))
    app.dependency_overrides[get_current_user_and_org] = lambda: (user, org_propia)
    try:
        resp = TestClient(app).get(f"/dossier-generation-jobs/{job_ajeno.id}/stream")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404


def test_stream_job_de_otro_usuario_misma_org_devuelve_404():
    """Aislamiento por usuario, no solo por organización: el dueño del job importa."""
    org = Organization(id=uuid.uuid4(), name="Compartida", slug="compartida")
    yo = User(id=uuid.uuid4(), email="yo@test.local")
    otro_usuario_id = uuid.uuid4()
    job_de_otro = DossierGenerationJob(
        id=uuid.uuid4(),
        organization_id=org.id,
        requested_by_user_id=otro_usuario_id,
        status="running",
    )

    app.dependency_overrides[get_db_if_configured] = _override_db(_FakeSession(job_de_otro))
    app.dependency_overrides[get_current_user_and_org] = lambda: (yo, org)
    try:
        resp = TestClient(app).get(f"/dossier-generation-jobs/{job_de_otro.id}/stream")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404


def test_stream_job_inexistente_devuelve_404():
    app.dependency_overrides[get_db_if_configured] = _override_db(_FakeSession())
    app.dependency_overrides[get_current_user_and_org] = lambda: (
        User(id=uuid.uuid4(), email="yo@test.local"),
        Organization(id=uuid.uuid4(), name="Propia", slug="propia"),
    )
    try:
        resp = TestClient(app).get(f"/dossier-generation-jobs/{uuid.uuid4()}/stream")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404
