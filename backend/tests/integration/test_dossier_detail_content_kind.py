"""Tests de integracion - S4.4: GET /dossiers/{id} expone `content_kind` (aditivo).

Camino feliz: dossier historico (solo Markdown) y dossier nuevo (con `executive_payload`
valido) devuelven 200 con el campo nuevo, sin tocar `dossier_data`. El aislamiento por
organizacion/usuario esta en tests/security/test_dossier_detail_seguridad.py.

Mismo patron de mock que tests/integration/test_dossier_stream_route.py: no hay Postgres
real en el entorno de pruebas.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
    def __init__(self, dossier: Dossier, org: Organization):
        self._dossier = dossier
        self._org = org

    def get(self, model, pk):
        if model is Dossier and pk == self._dossier.id:
            return self._dossier
        if model is Organization and pk == self._org.id:
            return self._org
        return None

    def execute(self, _stmt):
        return _FakeResult()

    def expire_all(self):
        pass


def _payload_minimo() -> dict:
    return {
        "meeting_context": {"tema": "Seguimiento trimestral"},
        "executive_summary": "Resumen ejecutivo con más de veinte caracteres.",
        "participants": [{"nombre": "Jane Doe"}],
        "conversation_starters": [
            {
                "topic": "Expansión europea",
                "rationale": "Mencionada en la última memoria anual.",
                "suggested_opener": "¿Cómo va Berlín?",
            }
        ],
        "data_sources_used": [
            {
                "source_type": "companies_house",
                "source_name": "Companies House",
                "retrieved_at": datetime(2026, 9, 12, tzinfo=UTC).isoformat(),
            }
        ],
    }


def _armar_contexto(org: Organization, user: User) -> OrgAuthContext:
    membresia = OrgMembership(
        id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="admin"
    )
    return OrgAuthContext(user=user, org=org, membership=membresia)


def _get(dossier: Dossier, org: Organization, user: User):
    app.dependency_overrides[get_db_if_configured] = lambda: _FakeSession(dossier, org)
    app.dependency_overrides[get_org_auth_context] = lambda: _armar_contexto(org, user)
    try:
        return TestClient(app).get(f"/dossiers/{dossier.id}")
    finally:
        app.dependency_overrides.clear()


def test_dossier_historico_devuelve_content_kind_legacy_markdown():
    org = Organization(id=uuid.uuid4(), name="Propia", slug="propia")
    user = User(id=uuid.uuid4(), email="user@test.local")
    dossier = Dossier(
        id=uuid.uuid4(),
        organization_id=org.id,
        requested_by_user_id=user.id,
        status="complete",
        dossier_data={"format": "markdown", "body": "# Informe histórico"},
    )

    resp = _get(dossier, org, user)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["content_kind"] == "legacy_markdown"
    assert cuerpo["executive_payload"] is None
    assert cuerpo["dossier_data"]["body"] == "# Informe histórico"


def test_dossier_nuevo_con_executive_payload_devuelve_content_kind_structured():
    org = Organization(id=uuid.uuid4(), name="Propia", slug="propia")
    user = User(id=uuid.uuid4(), email="user@test.local")
    dossier = Dossier(
        id=uuid.uuid4(),
        organization_id=org.id,
        requested_by_user_id=user.id,
        status="complete",
        dossier_data={
            "format": "markdown",
            "body": "# Informe",
            "executive_payload": _payload_minimo(),
        },
    )

    resp = _get(dossier, org, user)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["content_kind"] == "structured"
    assert cuerpo["executive_payload"]["executive_summary"].startswith("Resumen ejecutivo")
    # No se rompe el campo que ya consume el frontend.
    assert cuerpo["dossier_data"]["body"] == "# Informe"
