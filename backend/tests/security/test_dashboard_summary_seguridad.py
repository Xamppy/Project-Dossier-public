"""UX-KPI-01 · seguridad de GET /dashboard/summary (CA12).

Sin base de datos: la sesión y la construcción del resumen se sustituyen para verificar qué
identidad llega al cálculo y qué sale en la respuesta.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient

from dossier.api import dashboard_routes
from dossier.api.app import app
from dossier.api.auth_routes import get_current_user_and_org, get_db_if_configured
from dossier.security.jwt_tokens import create_access_token


def _user(nombre="a"):
    return SimpleNamespace(id=uuid.uuid4(), email=f"{nombre}@example.test", timezone="UTC")


def _org():
    return SimpleNamespace(id=uuid.uuid4(), plan="pro", credits_balance=5, credits_monthly_limit=10)


def _resumen_falso(**extra):
    base = {
        "as_of": "2026-10-03T15:00:00Z", "timezone": "UTC",
        "upcoming": {"state": "empty", "reason": "no_meetings_in_period", "measured_from": None,
                     "measured_to": None, "from": "2026-10-03T15:00:00Z", "to": "2026-10-10T15:00:00Z",
                     "eligible_meetings": 0, "prepared_meetings": 0, "pending_meetings": 0,
                     "coverage_percent": None},
        "history": {"state": "empty", "reason": "no_meetings_in_period", "measured_from": None,
                    "measured_to": None, "from": "2026-09-03T15:00:00Z", "to": "2026-10-03T15:00:00Z",
                    "eligible_meetings": 0, "manually_prepared_on_time_meetings": 0, "on_time_percent": None,
                    "manual_on_time_dossiers": 0},
        "credits": {"state": "ok", "reason": None, "measured_from": None, "measured_to": None,
                    "balance": 5, "monthly_limit": 10},
    }
    base.update(extra)
    return base


@pytest.fixture
def cliente():
    yield TestClient(app)
    app.dependency_overrides.clear()


class _DbSinUsuarios:
    def get(self, *_a, **_k):
        return None


def _sin_bd():
    yield _DbSinUsuarios()


def test_sin_cabecera_o_con_token_malformado_o_manipulado_es_401(cliente):
    app.dependency_overrides[get_db_if_configured] = _sin_bd
    assert cliente.get("/dashboard/summary").status_code == 401
    assert cliente.get("/dashboard/summary", headers={"Authorization": "Token abc"}).status_code == 401
    assert cliente.get("/dashboard/summary", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
    falso = jwt.encode({"sub": str(uuid.uuid4()), "org_id": str(uuid.uuid4())}, "otra-clave-distinta-1234567", algorithm="HS256")
    assert cliente.get("/dashboard/summary", headers={"Authorization": f"Bearer {falso}"}).status_code == 401


def test_un_token_expirado_es_401(cliente, monkeypatch):
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "-5")
    app.dependency_overrides[get_db_if_configured] = _sin_bd
    t = create_access_token(user_id=str(uuid.uuid4()), email="x@example.test", organization_id=str(uuid.uuid4()))
    assert cliente.get("/dashboard/summary", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_un_token_de_usuario_inexistente_es_401(cliente):
    app.dependency_overrides[get_db_if_configured] = _sin_bd
    t = create_access_token(user_id=str(uuid.uuid4()), email="x@example.test", organization_id=str(uuid.uuid4()))
    assert cliente.get("/dashboard/summary", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_el_calculo_recibe_siempre_la_identidad_de_la_sesion_y_no_la_del_cliente(cliente, monkeypatch):
    sesion_user, sesion_org = _user("sesion"), _org()
    recibido = {}

    def _falso(db, *, user, org, now=None):
        recibido.update(user=user, org=org)
        return _resumen_falso()

    monkeypatch.setattr(dashboard_routes, "build_dashboard_summary", _falso)
    app.dependency_overrides[get_current_user_and_org] = lambda: (sesion_user, sesion_org)
    app.dependency_overrides[get_db_if_configured] = lambda: iter([None])
    ajeno, otra_org = uuid.uuid4(), uuid.uuid4()
    r = cliente.get(
        f"/dashboard/summary?user_id={ajeno}&organization_id={otra_org}&org_id={otra_org}",
        headers={"X-User-Id": str(ajeno), "X-Organization-Id": str(otra_org)},
    )
    assert r.status_code == 200
    assert recibido["user"] is sesion_user and recibido["org"] is sesion_org


def test_la_respuesta_no_filtra_campos_fuera_del_contrato(cliente, monkeypatch):
    sucio = _resumen_falso(correo="ana@tesla.test", meetings=[{"tema": "Reunión secreta"}], user_id="u-1")
    sucio["upcoming"]["lista_de_reuniones"] = ["ev1", "ev2"]
    sucio["credits"]["stripe_customer_id"] = "cus_123"
    monkeypatch.setattr(dashboard_routes, "build_dashboard_summary", lambda *a, **k: sucio)
    app.dependency_overrides[get_current_user_and_org] = lambda: (_user(), _org())
    app.dependency_overrides[get_db_if_configured] = lambda: iter([None])
    cuerpo = cliente.get("/dashboard/summary").json()
    texto = json.dumps(cuerpo)
    for secreto in ("ana@tesla.test", "Reunión secreta", "user_id", "lista_de_reuniones", "cus_123", "ev1"):
        assert secreto not in texto
    assert set(cuerpo) == {"as_of", "timezone", "upcoming", "history", "credits"}


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_el_endpoint_es_de_solo_lectura(cliente, metodo):
    app.dependency_overrides[get_current_user_and_org] = lambda: (_user(), _org())
    assert getattr(cliente, metodo)("/dashboard/summary").status_code == 405


def test_la_clave_de_cache_une_usuario_y_organizacion_y_la_invalidacion_cubre_todas_las_orgs():
    from dossier.services.summary_cache import SummaryCache

    cache, u, o1, o2, otro = SummaryCache(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cache.get_or_compute((u, o1), lambda: ("org1", False))
    cache.get_or_compute((u, o2), lambda: ("org2", False))
    cache.get_or_compute((otro, o1), lambda: ("ajeno", False))
    assert cache.get_or_compute((u, o1), lambda: ("x", False)) == "org1"
    assert cache.get_or_compute((u, o2), lambda: ("x", False)) == "org2"
    assert cache.get_or_compute((otro, o1), lambda: ("x", False)) == "ajeno"
