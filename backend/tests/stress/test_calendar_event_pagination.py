"""UX-CAL-02 · estrés de la lectura de calendario por intervalo (CA2).

Tres preguntas (docs/dev/testing-policy.md §4): volumen alto, muchas llamadas a la
vez y proveedor lento o roto. Todo en proceso, sin red.
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from fastapi.testclient import TestClient

from dossier.api.app import app
from dossier.api.auth_routes import get_db_if_configured
from dossier.db.models import User
from dossier.services import google_calendar_api as google
from dossier.services import graph_calendar as graph
from dossier.services.calendar_range import parse_rango

app_module = sys.modules["dossier.api.app"]
RANGO = parse_rango("2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z")


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.ok = payload, status, status < 400
        self.text = ""

    def json(self):
        return self._payload


def _ev_google(i):
    return {
        "id": f"g{i}",
        "summary": f"R{i}",
        "start": {"dateTime": "2026-10-05T10:00:00Z"},
        "end": {"dateTime": "2026-10-05T11:00:00Z"},
    }


def _ev_graph(i):
    return {
        "id": f"m{i}",
        "subject": f"R{i}",
        "isAllDay": False,
        "start": {"dateTime": "2026-10-05T10:00:00.0000000"},
        "end": {"dateTime": "2026-10-05T11:00:00.0000000"},
    }


# ── Volumen ──────────────────────────────────────────────────────────────────


def test_volumen_maximo_de_google_se_recupera_completo(monkeypatch):
    """10 páginas × 250 = 2 500 eventos: exactamente el techo, sin avisar de incompleto."""
    por_pagina = 250

    def fake_get(url, headers=None, params=None, timeout=None):
        idx = int((params or {}).get("pageToken", "p0")[1:])
        cuerpo = {"items": [_ev_google(idx * por_pagina + i) for i in range(por_pagina)]}
        if idx + 1 < 10:
            cuerpo["nextPageToken"] = f"p{idx + 1}"
        return _Resp(cuerpo)

    monkeypatch.setattr(google.requests, "get", fake_get)
    inicio = time.perf_counter()
    res = google.listar_reuniones_google_rango("tok", RANGO)
    assert time.perf_counter() - inicio < 2.0  # normalizar 2 500 eventos no es el cuello de botella
    assert len(res.reuniones) == 2500
    assert res.completo is True
    assert len({r["id"] for r in res.reuniones}) == 2500


def test_volumen_por_encima_del_techo_se_trunca_con_aviso(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        idx = int((params or {}).get("pageToken", "p0")[1:])
        return _Resp({"items": [_ev_google(idx * 250 + i) for i in range(250)], "nextPageToken": f"p{idx + 1}"})

    monkeypatch.setattr(google.requests, "get", fake_get)
    res = google.listar_reuniones_google_rango("tok", RANGO)
    assert len(res.reuniones) == 2500
    assert res.completo is False and res.motivo_incompleto == "limite_paginas"


def test_volumen_maximo_de_graph_se_recupera_completo(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        idx = int(url.rsplit("$skiptoken=p", 1)[1]) if "$skiptoken=p" in url else 0
        cuerpo = {"value": [_ev_graph(idx * 250 + i) for i in range(250)]}
        if idx + 1 < 10:
            cuerpo["@odata.nextLink"] = (
                f"https://graph.microsoft.com/v1.0/me/calendar/calendarView?$skiptoken=p{idx + 1}"
            )
        return _Resp(cuerpo)

    monkeypatch.setattr(graph.requests, "get", fake_get)
    res = graph.listar_reuniones_rango("tok", RANGO)
    assert len(res.reuniones) == 2500 and res.completo is True


# ── Concurrencia ─────────────────────────────────────────────────────────────


def test_consultas_simultaneas_de_dos_usuarias_no_se_cruzan(monkeypatch):
    ana = User(id=uuid.uuid4(), email="ana@example.test")
    beto = User(id=uuid.uuid4(), email="beto@example.test")
    usuarios = {"Bearer ana": ana, "Bearer beto": beto}
    tokens = {ana.id: "tok-ana", beto.id: "tok-beto"}

    class _Db:
        def execute(self, *a, **k):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None

            return _R()

    def _db():
        yield _Db()

    def fake_get(url, headers=None, params=None, timeout=None):
        time.sleep(0.002)  # cede el hilo para provocar intercalado
        dueno = (headers or {})["Authorization"].split("-")[-1]
        return _Resp({"items": [{
            "id": f"g-{dueno}", "summary": dueno,
            "start": {"dateTime": "2026-10-05T10:00:00Z"}, "end": {"dateTime": "2026-10-05T11:00:00Z"},
        }]})

    app.dependency_overrides[get_db_if_configured] = _db
    monkeypatch.setattr(app_module, "auth_payload_and_user", lambda db, authz: ({}, usuarios[authz]))
    monkeypatch.setattr(app_module, "get_google_calendar_access_token_for_user", lambda db, uid: tokens[uid])
    monkeypatch.setattr(requests, "get", fake_get)
    try:
        client = TestClient(app)
        params = {"desde": "2026-10-01T00:00:00Z", "hasta": "2026-11-01T00:00:00Z"}

        def consulta(i):
            who = "ana" if i % 2 == 0 else "beto"
            r = client.get("/calendario/eventos-google", params=params, headers={"Authorization": f"Bearer {who}"})
            return who, [m["tema"] for m in r.json()["reuniones"]]

        with ThreadPoolExecutor(max_workers=16) as pool:
            resultados = list(pool.map(consulta, range(80)))
    finally:
        app.dependency_overrides.pop(get_db_if_configured, None)

    assert all(temas == [who] for who, temas in resultados)


def test_paginacion_concurrente_sobre_el_mismo_cliente_es_independiente(monkeypatch):
    """Cada llamada lleva su propio presupuesto y su propio estado de página."""
    lock = threading.Lock()
    llamadas = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        with lock:
            llamadas["n"] += 1
        idx = int((params or {}).get("pageToken", "p0")[1:])
        cuerpo = {"items": [_ev_google(idx)]}
        if idx + 1 < 5:
            cuerpo["nextPageToken"] = f"p{idx + 1}"
        return _Resp(cuerpo)

    monkeypatch.setattr(google.requests, "get", fake_get)
    with ThreadPoolExecutor(max_workers=12) as pool:
        res = list(pool.map(lambda _: google.listar_reuniones_google_rango("tok", RANGO), range(40)))
    assert all(len(r.reuniones) == 5 and r.completo for r in res)
    assert llamadas["n"] == 40 * 5


# ── Degradación ──────────────────────────────────────────────────────────────


def test_proveedor_lento_no_excede_el_presupuesto(monkeypatch):
    t = {"v": 0.0}
    esperas: list = []

    def fake_get(url, headers=None, params=None, timeout=None):
        esperas.append(timeout)
        t["v"] += timeout  # cada petición consume todo su timeout
        raise requests.Timeout("lento")

    monkeypatch.setattr(google.requests, "get", fake_get)
    try:
        google.listar_reuniones_google_rango("tok", RANGO, reloj=lambda: t["v"])
    except Exception as e:  # noqa: BLE001 - se verifica el tipo abajo
        assert getattr(e, "status_code", None) == 504
    assert sum(esperas) <= 20.0 + 1e-9


def test_proveedor_que_cae_a_mitad_conserva_lo_recuperado(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        idx = int((params or {}).get("pageToken", "p0")[1:])
        if idx == 4:
            return _Resp({"error": "cae"}, status=503)
        return _Resp({"items": [_ev_google(idx * 10 + i) for i in range(10)], "nextPageToken": f"p{idx + 1}"})

    monkeypatch.setattr(google.requests, "get", fake_get)
    res = google.listar_reuniones_google_rango("tok", RANGO)
    assert len(res.reuniones) == 40
    assert res.completo is False and res.motivo_incompleto == "error_proveedor"
