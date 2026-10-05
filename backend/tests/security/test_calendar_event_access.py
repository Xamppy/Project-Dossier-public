"""UX-CAL-02 · CA10: aislamiento por usuario y tokens OAuth solo en el servidor.

Dos identidades distintas consultan el mismo intervalo: cada una debe usar su propio
token ante el proveedor y recibir solo sus reuniones. Ninguna respuesta, ni de éxito ni
de error, puede contener tokens OAuth ni enlaces de paginación del proveedor.
"""
from __future__ import annotations

import sys
import uuid

import pytest
import requests
from fastapi import HTTPException
from fastapi.testclient import TestClient

from dossier.api.app import app
from dossier.api.auth_routes import get_db_if_configured
from dossier.db.models import User

app_module = sys.modules["dossier.api.app"]

ANA = User(id=uuid.uuid4(), email="ana@example.test")
BETO = User(id=uuid.uuid4(), email="beto@example.test")
USUARIOS = {"Bearer jwt-ana": ANA, "Bearer jwt-beto": BETO}
TOKEN_GOOGLE = {ANA.id: "ya29.TOKEN-SECRETO-DE-ANA", BETO.id: "ya29.TOKEN-SECRETO-DE-BETO"}
TOKEN_GRAPH = {ANA.id: "eyJ.GRAPH-SECRETO-DE-ANA", BETO.id: "eyJ.GRAPH-SECRETO-DE-BETO"}
RANGO = {"desde": "2026-10-01T00:00:00Z", "hasta": "2026-11-01T00:00:00Z"}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.ok = payload, status, status < 400
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeDb:
    def execute(self, *_a, **_k):
        class _R:
            def scalar_one_or_none(self_inner):
                return None

        return _R()


def _auth(db, authorization):
    usuario = USUARIOS.get(authorization or "")
    if usuario is None:
        raise HTTPException(status_code=401, detail="Falta la cabecera Authorization: Bearer <token>.")
    return {}, usuario


@pytest.fixture
def client(monkeypatch):
    def _db():
        yield _FakeDb()

    app.dependency_overrides[get_db_if_configured] = _db
    monkeypatch.setattr(app_module, "auth_payload_and_user", _auth)
    monkeypatch.setattr(app_module, "get_google_calendar_access_token_for_user", lambda db, uid: TOKEN_GOOGLE[uid])
    monkeypatch.setattr(app_module, "get_microsoft_graph_access_token_for_user", lambda db, uid: TOKEN_GRAPH[uid])
    yield TestClient(app)
    app.dependency_overrides.pop(get_db_if_configured, None)


def _calendarios_por_token(monkeypatch, llamadas):
    """Cada token ve solo el calendario de su dueño: título = dueño del token."""

    def fake_get(url, headers=None, params=None, timeout=None):
        bearer = (headers or {}).get("Authorization", "")
        llamadas.append({"url": url, "bearer": bearer})
        dueno = "ana" if "DE-ANA" in bearer else "beto" if "DE-BETO" in bearer else "nadie"
        if "googleapis.com" in url:
            return _Resp({"items": [{
                "id": f"g-{dueno}",
                "summary": f"Reunión de {dueno}",
                "start": {"dateTime": "2026-10-05T10:00:00Z"},
                "end": {"dateTime": "2026-10-05T11:00:00Z"},
            }]})
        return _Resp({"value": [{
            "id": f"m-{dueno}",
            "subject": f"Reunión de {dueno}",
            "start": {"dateTime": "2026-10-05T10:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-10-05T11:00:00.0000000", "timeZone": "UTC"},
            "isAllDay": False,
        }]})

    monkeypatch.setattr(requests, "get", fake_get)


@pytest.mark.parametrize("ruta", ["/calendario/eventos-google", "/calendario/eventos-outlook"])
def test_cada_usuaria_ve_solo_su_calendario_con_su_propio_token(client, monkeypatch, ruta):
    llamadas: list = []
    _calendarios_por_token(monkeypatch, llamadas)

    ra = client.get(ruta, params=RANGO, headers={"Authorization": "Bearer jwt-ana"})
    rb = client.get(ruta, params=RANGO, headers={"Authorization": "Bearer jwt-beto"})

    assert [m["tema"] for m in ra.json()["reuniones"]] == ["Reunión de ana"]
    assert [m["tema"] for m in rb.json()["reuniones"]] == ["Reunión de beto"]
    assert "DE-ANA" in llamadas[0]["bearer"] and "DE-BETO" in llamadas[1]["bearer"]


@pytest.mark.parametrize("ruta", ["/calendario/eventos-google", "/calendario/eventos-outlook"])
def test_la_respuesta_nunca_contiene_tokens_oauth(client, monkeypatch, ruta):
    _calendarios_por_token(monkeypatch, [])
    r = client.get(ruta, params=RANGO, headers={"Authorization": "Bearer jwt-ana"})
    cuerpo = r.text
    for secreto in ("SECRETO", "ya29", "eyJ", "jwt-ana"):
        assert secreto not in cuerpo
    assert "access_token" not in cuerpo and "refresh_token" not in cuerpo


@pytest.mark.parametrize("ruta", ["/calendario/eventos-google", "/calendario/eventos-outlook"])
def test_el_error_del_proveedor_no_filtra_token_ni_cuerpo_remoto(client, monkeypatch, ruta):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _Resp({"error": "Bearer ya29.TOKEN-SECRETO-DE-ANA rechazado"}, status=500)

    monkeypatch.setattr(requests, "get", fake_get)
    r = client.get(ruta, params=RANGO, headers={"Authorization": "Bearer jwt-ana"})
    assert r.status_code == 502
    assert "SECRETO" not in r.text and "ya29" not in r.text


def test_carga_incompleta_no_expone_enlaces_de_paginacion_del_proveedor(client, monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _Resp({
            "value": [{
                "id": "m1", "subject": "x", "isAllDay": False,
                "start": {"dateTime": "2026-10-05T10:00:00.0000000"},
                "end": {"dateTime": "2026-10-05T11:00:00.0000000"},
            }],
            "@odata.nextLink": "https://evil.example.com/v1.0/me/calendar/calendarView?$skiptoken=1",
        })

    monkeypatch.setattr(requests, "get", fake_get)
    r = client.get("/calendario/eventos-outlook", params=RANGO, headers={"Authorization": "Bearer jwt-ana"})
    assert r.status_code == 200 and r.json()["completo"] is False
    assert "evil.example.com" not in r.text and "nextLink" not in r.text


@pytest.mark.parametrize("ruta", ["/calendario/eventos-google", "/calendario/eventos-outlook"])
def test_sin_sesion_no_se_consulta_al_proveedor(client, monkeypatch, ruta):
    llamadas: list = []
    _calendarios_por_token(monkeypatch, llamadas)
    r = client.get(ruta, params=RANGO)  # sin Authorization
    assert r.status_code == 401
    assert llamadas == []


@pytest.mark.parametrize("ruta", ["/calendario/eventos-google", "/calendario/eventos-outlook"])
def test_jwt_invalido_devuelve_401_sin_consultar_al_proveedor(client, monkeypatch, ruta):
    llamadas: list = []
    _calendarios_por_token(monkeypatch, llamadas)
    r = client.get(ruta, params=RANGO, headers={"Authorization": "Bearer jwt-falso"})
    assert r.status_code == 401
    assert llamadas == []


def test_el_filtro_de_reuniones_se_resuelve_con_el_usuario_autenticado(client, monkeypatch):
    """La integración consultada para filtrar es la del usuario del JWT, no otra."""
    vistos: list = []
    original = app_module._filter_reuniones_for_app_user

    def espia(db, authorization, access_token, provider, reuniones, **kw):
        vistos.append((authorization, provider))
        return original(db, authorization, access_token, provider, reuniones, **kw)

    monkeypatch.setattr(app_module, "_filter_reuniones_for_app_user", espia)
    _calendarios_por_token(monkeypatch, [])
    client.get("/calendario/eventos-google", params=RANGO, headers={"Authorization": "Bearer jwt-beto"})
    assert vistos == [("Bearer jwt-beto", "google")]
