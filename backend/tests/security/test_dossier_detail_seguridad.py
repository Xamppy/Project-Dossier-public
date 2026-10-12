"""Tests de seguridad - S4.4: aislamiento por organizacion en GET /dossiers/{id}.

El campo nuevo (`content_kind` / `executive_payload`) viaja en la misma respuesta que
`dossier_data`; si el aislamiento por organizacion falla, tambien filtra el payload
estructurado de otra organizacion. Cubre eso, no las reglas de visibilidad ya existentes
(propietario/compartido/viewer), que no cambian en esta tarea.

Mismo patron que tests/security/test_dossier_stream_seguridad.py.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from dossier.api.app import app
from dossier.api.auth_routes import (
    OrgAuthContext,
    get_db_if_configured,
    get_org_auth_context,
)
from dossier.db.models import Dossier, Organization, OrgMembership, User


class _FakeResult:
    def all(self):
        return []

    def scalars(self):
        return self

    def first(self):
        return None

    def scalar_one_or_none(self):
        return None


class _FakeSession:
    def __init__(self, dossier: Dossier | None = None, org: Organization | None = None):
        self._dossier = dossier
        self._org = org

    def get(self, model, pk):
        if model is Dossier and self._dossier is not None and pk == self._dossier.id:
            return self._dossier
        if model is Organization and self._org is not None and pk == self._org.id:
            return self._org
        return None

    def execute(self, _stmt):
        return _FakeResult()

    def expire_all(self):
        pass


def test_dossier_de_otra_organizacion_devuelve_404_no_403():
    """404, no 403: no se revela que el dossier existe en otra organización."""
    org_propia = Organization(id=uuid.uuid4(), name="Propia", slug="propia")
    org_ajena_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), email="user@test.local")
    membresia = OrgMembership(
        id=uuid.uuid4(), organization_id=org_propia.id, user_id=user.id, role="admin"
    )
    dossier_ajeno = Dossier(
        id=uuid.uuid4(),
        organization_id=org_ajena_id,
        requested_by_user_id=uuid.uuid4(),
        status="complete",
        dossier_data={
            "format": "markdown",
            "body": "# Informe ajeno",
            "executive_payload": None,
        },
    )

    app.dependency_overrides[get_db_if_configured] = lambda: _FakeSession(
        dossier_ajeno, org_propia
    )
    app.dependency_overrides[get_org_auth_context] = lambda: OrgAuthContext(
        user=user, org=org_propia, membership=membresia
    )
    try:
        resp = TestClient(app).get(f"/dossiers/{dossier_ajeno.id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert "executive_payload" not in resp.text
    assert "Informe ajeno" not in resp.text


def test_dossier_sin_authorization_header_devuelve_401():
    app.dependency_overrides[get_db_if_configured] = lambda: _FakeSession()
    try:
        resp = TestClient(app).get(f"/dossiers/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.pop(get_db_if_configured, None)
    assert resp.status_code == 401
