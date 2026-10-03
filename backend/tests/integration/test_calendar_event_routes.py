"""UX-CAL-02 · rutas GET de eventos de calendario con lectura por intervalo (CA2, CA3, CA9).

Usa ``TestClient`` y proveedores simulados: ``requests.get`` se sustituye por un doble
que responde como Google Calendar y Microsoft Graph. Sin red, sin base de datos.
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

app_module = sys.modules["dossier.api.app"]  # ``dossier.api.app`` también es el nombre de la instancia

USER = User(id=uuid.uuid4(), email="usuaria@example.test")
AUTH = {"Authorization": "Bearer jwt-de-prueba"}
RANGO = {"desde": "2026-10-01T00:00:00-03:00", "hasta": "2026-11-01T00:00:00-03:00"}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.ok = payload, status, status < 400
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeDb:
    """Sesión mínima: el filtro de reuniones busca la integración del usuario."""

    def execute(self, *_a, **_k):
        class _R:
            def scalar_one_or_none(self_inner):
                return None

        return _R()


@pytest.fixture
def client(monkeypatch):
    def _db():
        yield _FakeDb()

    app.dependency_overrides[get_db_if_configured] = _db
    monkeypatch.setattr(app_module, "auth_payload_and_user", lambda db, authz: ({}, USER))
    monkeypatch.setattr(app_module, "get_google_calendar_access_token_for_user", lambda db, uid: "tok-google")
    monkeypatch.setattr(app_module, "get_microsoft_graph_access_token_for_user", lambda db, uid: "tok-graph")
    yield TestClient(app)
    app.dependency_overrides.pop(get_db_if_configured, None)


def _ev_google(i):
    return {
        "id": f"g{i}",
        "summary": f"Reunión {i}",
        "start": {"dateTime": "2026-10-05T10:00:00-03:00"},
        "end": {"dateTime": "2026-10-05T11:00:00-03:00"},
    }


def _ev_graph(i, **extra):
    base = {
        "id": f"m{i}",
        "subject": f"Reunión {i}",
        "start": {"dateTime": "2026-10-05T13:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-05T14:00:00.0000000", "timeZone": "UTC"},
        "isAllDay": False,
    }
    base.update(extra)
    return base


def _proveedor(monkeypatch, *, google_pages=None, graph_pages=None, llamadas=None):
    """Simula Google (``pageToken``) y Graph (``@odata.nextLink``) por páginas."""
    google_pages = google_pages if google_pages is not None else [[]]
    graph_pages = graph_pages if graph_pages is not None else [[]]
    llamadas = llamadas if llamadas is not None else []

    def fake_get(url, headers=None, params=None, timeout=None):
        llamadas.append({"url": url, "params": dict(params) if params else None, "headers": headers})
        if "googleapis.com" in url:
            idx = int((params or {}).get("pageToken", "p0")[1:])
            cuerpo = {"items": google_pages[idx]}
            if idx + 1 < len(google_pages):
                cuerpo["nextPageToken"] = f"p{idx + 1}"
            return _Resp(cuerpo)
        if "graph.microsoft.com" in url:
            idx = int(url.rsplit("$skiptoken=p", 1)[1]) if "$skiptoken=p" in url else 0
            cuerpo = {"value": graph_pages[idx]}
            if idx + 1 < len(graph_pages):
                cuerpo["@odata.nextLink"] = (
                    f"https://graph.microsoft.com/v1.0/me/calendar/calendarView?$skiptoken=p{idx + 1}"
                )
            return _Resp(cuerpo)
        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr(requests, "get", fake_get)
    return llamadas


# ── Modo legado: sin intervalo, nada cambia ─────────────────────────────────


def test_google_sin_intervalo_conserva_el_contrato_legado(client, monkeypatch):
    llamadas = _proveedor(monkeypatch, google_pages=[[_ev_google(1)]])
    r = client.get("/calendario/eventos-google?top=5", headers=AUTH)
    assert r.status_code == 200
    assert set(r.json()) == {"total", "reuniones", "mensaje"}
    assert r.json()["total"] == 1
    assert llamadas[0]["params"]["maxResults"] == 5  # top legado, no 250


def test_outlook_sin_intervalo_conserva_el_contrato_legado(client, monkeypatch):
    llamadas = _proveedor(monkeypatch, graph_pages=[[_ev_graph(1)]])
    r = client.get("/calendario/eventos-outlook?top=7", headers=AUTH)
    assert r.status_code == 200
    assert set(r.json()) == {"total", "reuniones", "mensaje"}
    assert llamadas[0]["params"]["$top"] == 7


# ── Modo intervalo ───────────────────────────────────────────────────────────


def test_google_con_intervalo_devuelve_rango_y_completo(client, monkeypatch):
    llamadas = _proveedor(monkeypatch, google_pages=[[_ev_google(1), _ev_google(2)]])
    r = client.get("/calendario/eventos-google", params=RANGO, headers=AUTH)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 2 and len(cuerpo["reuniones"]) == 2
    assert cuerpo["rango"] == {"desde": "2026-10-01T03:00:00Z", "hasta": "2026-11-01T03:00:00Z"}
    assert cuerpo["completo"] is True
    assert cuerpo["motivo_incompleto"] is None
    assert llamadas[0]["params"]["timeMin"] == "2026-10-01T03:00:00Z"


@pytest.mark.parametrize("ruta", ["/calendario/eventos-outlook", "/calendario/eventos"])
def test_outlook_con_intervalo_en_ambas_rutas(client, monkeypatch, ruta):
    _proveedor(monkeypatch, graph_pages=[[_ev_graph(1)]])
    r = client.get(ruta, params=RANGO, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["completo"] is True and r.json()["total"] == 1


def test_mas_de_cincuenta_reuniones_repartidas_en_paginas_se_recuperan_todas(client, monkeypatch):
    """CA2: el límite legado de 50 no aplica al modo intervalo."""
    paginas = [[_ev_google(p * 20 + i) for i in range(20)] for p in range(6)]  # 120 eventos
    _proveedor(monkeypatch, google_pages=paginas)
    r = client.get("/calendario/eventos-google", params=RANGO, headers=AUTH)
    assert r.json()["total"] == 120
    assert r.json()["completo"] is True


def test_limite_de_paginas_marca_carga_incompleta(client, monkeypatch):
    paginas = [[_ev_google(p)] for p in range(15)]
    _proveedor(monkeypatch, google_pages=paginas)
    r = client.get("/calendario/eventos-google", params=RANGO, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["total"] == 10
    assert r.json()["completo"] is False
    assert r.json()["motivo_incompleto"] == "limite_paginas"
    assert r.json()["mensaje"]  # texto explícito, no «sin reuniones»


def test_outlook_dia_completo_llega_como_fecha_civil(client, monkeypatch):
    ev = _ev_graph(
        1,
        isAllDay=True,
        start={"dateTime": "2026-10-12T03:00:00.0000000", "timeZone": "UTC"},
        end={"dateTime": "2026-10-13T03:00:00.0000000", "timeZone": "UTC"},
        originalStartTimeZone="America/Santiago",
        originalEndTimeZone="America/Santiago",
    )
    _proveedor(monkeypatch, graph_pages=[[ev]])
    r = client.get("/calendario/eventos-outlook", params=RANGO, headers=AUTH)
    m = r.json()["reuniones"][0]
    assert (m["inicio"], m["fin"], m["todo_el_dia"]) == ("2026-10-12", "2026-10-13", True)


def test_intervalo_vacio_dice_que_no_hay_reuniones_en_el_intervalo(client, monkeypatch):
    _proveedor(monkeypatch)
    r = client.get("/calendario/eventos-google", params=RANGO, headers=AUTH)
    assert r.json()["total"] == 0 and r.json()["completo"] is True
    assert "intervalo" in r.json()["mensaje"].lower()


# ── CA9 · 422 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ruta", ["/calendario/eventos-google", "/calendario/eventos-outlook"])
@pytest.mark.parametrize(
    "params",
    [
        {"desde": "2026-10-01T00:00:00Z"},
        {"hasta": "2026-10-02T00:00:00Z"},
        {"desde": "2026-10-01T00:00:00", "hasta": "2026-10-02T00:00:00"},
        {"desde": "2026-10-02T00:00:00Z", "hasta": "2026-10-01T00:00:00Z"},
        {"desde": "2026-10-01T00:00:00Z", "hasta": "2026-12-03T00:00:00Z"},
        {"desde": "basura", "hasta": "basura"},
        {**RANGO, "top": "5"},
        {**RANGO, "dias": "30"},
        {**RANGO, "incluir_pasadas": "true"},
    ],
)
def test_parametros_invalidos_devuelven_422_sin_llamar_al_proveedor(client, monkeypatch, ruta, params):
    llamadas = _proveedor(monkeypatch)
    r = client.get(ruta, params=params, headers=AUTH)
    assert r.status_code == 422
    assert llamadas == []


# ── Errores del proveedor y de sesión ────────────────────────────────────────


def test_primera_pagina_fallida_es_502_y_no_sin_reuniones(client, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp({"e": 1}, status=500))
    r = client.get("/calendario/eventos-google", params=RANGO, headers=AUTH)
    assert r.status_code == 502
    assert "reuniones" not in r.json()


def test_timeout_en_primera_pagina_es_504(client, monkeypatch):
    def fake_get(*a, **k):
        raise requests.Timeout("lento")

    monkeypatch.setattr(requests, "get", fake_get)
    r = client.get("/calendario/eventos-outlook", params=RANGO, headers=AUTH)
    assert r.status_code == 504


def test_sin_authorization_devuelve_401(client, monkeypatch):
    def sin_sesion(db, authz):
        raise HTTPException(status_code=401, detail="Falta la cabecera Authorization: Bearer <token>.")

    monkeypatch.setattr(app_module, "auth_payload_and_user", sin_sesion)
    r = client.get("/calendario/eventos-google", params=RANGO)
    assert r.status_code == 401


def test_integracion_ausente_sigue_siendo_404(client, monkeypatch):
    def sin_integracion(db, uid):
        raise HTTPException(status_code=404, detail="No hay Google Calendar conectado.")

    monkeypatch.setattr(app_module, "get_google_calendar_access_token_for_user", sin_integracion)
    r = client.get("/calendario/eventos-google", params=RANGO, headers=AUTH)
    assert r.status_code == 404
