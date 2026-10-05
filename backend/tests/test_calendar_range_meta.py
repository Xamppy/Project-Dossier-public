"""UX-KPI-01 · metadatos que la lectura por intervalo debe conservar para los indicadores.

Los indicadores necesitan tres datos que el normalizador legado descarta: la identidad
interoperable del evento (iCalUID), la respuesta del propio usuario (rechazada) y las
direcciones de correo reales (Graph entrega nombres en vez de correos). Solo la ruta por
intervalo los añade: el shape legado que consumen la UI y la generación no cambia.
"""
from __future__ import annotations

import pytest

from dossier.services import google_calendar_api as google
from dossier.services import graph_calendar as graph
from dossier.services.calendar_range import parse_rango


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.ok = payload, status, status < 400
        self.text = str(payload)

    def json(self):
        return self._payload


RANGO = parse_rango("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")


def _google_evento(**extra):
    base = {
        "id": "g1",
        "iCalUID": "uid-1@google.com",
        "summary": "Reunión comercial — Tesla",
        "start": {"dateTime": "2026-10-05T10:00:00-03:00"},
        "end": {"dateTime": "2026-10-05T11:00:00-03:00"},
        "organizer": {"email": "yo@mi-empresa.test"},
        "attendees": [
            {"email": "yo@mi-empresa.test", "self": True, "responseStatus": "accepted"},
            {"email": "Cliente@Tesla.test", "responseStatus": "needsAction"},
        ],
    }
    base.update(extra)
    return base


def _graph_evento(**extra):
    base = {
        "id": "m1",
        "iCalUId": "uid-1@outlook.com",
        "subject": "Reunión comercial — Tesla",
        "start": {"dateTime": "2026-10-05T13:00:00.0000000"},
        "end": {"dateTime": "2026-10-05T14:00:00.0000000"},
        "isAllDay": False,
        "responseStatus": {"response": "accepted"},
        "organizer": {"emailAddress": {"name": "Yo", "address": "yo@mi-empresa.test"}},
        "attendees": [
            {"emailAddress": {"name": "Cliente Tesla", "address": "cliente@tesla.test"}},
        ],
    }
    base.update(extra)
    return base


def _leer_google(monkeypatch, evento):
    monkeypatch.setattr(google.requests, "get", lambda *a, **k: _Resp({"items": [evento]}))
    return google.listar_reuniones_google_rango("tok", RANGO).reuniones[0]


def _leer_graph(monkeypatch, evento):
    monkeypatch.setattr(graph.requests, "get", lambda *a, **k: _Resp({"value": [evento]}))
    return graph.listar_reuniones_rango("tok", RANGO).reuniones[0]


def test_google_rango_conserva_identidad_correos_y_respuesta(monkeypatch):
    r = _leer_google(monkeypatch, _google_evento())
    assert r["ical_uid"] == "uid-1@google.com"
    assert r["correos"] == ["yo@mi-empresa.test", "cliente@tesla.test"]
    assert "respuesta_usuario" not in r  # el propio usuario aceptó: nada que señalar


def test_google_rango_marca_la_reunion_rechazada_por_el_usuario(monkeypatch):
    evento = _google_evento(
        attendees=[
            {"email": "yo@mi-empresa.test", "self": True, "responseStatus": "declined"},
            {"email": "cliente@tesla.test"},
        ]
    )
    assert _leer_google(monkeypatch, evento)["respuesta_usuario"] == "declined"


def test_google_rechazo_de_otro_asistente_no_cuenta(monkeypatch):
    evento = _google_evento(
        attendees=[
            {"email": "yo@mi-empresa.test", "self": True, "responseStatus": "accepted"},
            {"email": "cliente@tesla.test", "responseStatus": "declined"},
        ]
    )
    assert "respuesta_usuario" not in _leer_google(monkeypatch, evento)


def test_google_rango_sin_ical_uid_ni_asistentes_no_inventa_claves(monkeypatch):
    evento = {
        "id": "g2",
        "summary": "Solo",
        "start": {"dateTime": "2026-10-05T10:00:00Z"},
        "end": {"dateTime": "2026-10-05T11:00:00Z"},
    }
    r = _leer_google(monkeypatch, evento)
    assert "ical_uid" not in r and "respuesta_usuario" not in r
    assert r["correos"] == []


def test_graph_rango_conserva_identidad_correos_y_respuesta(monkeypatch):
    r = _leer_graph(monkeypatch, _graph_evento())
    assert r["ical_uid"] == "uid-1@outlook.com"
    assert r["correos"] == ["yo@mi-empresa.test", "cliente@tesla.test"]
    assert "respuesta_usuario" not in r
    # los nombres siguen siendo lo que ve la persona; los correos viajan aparte
    assert "Cliente Tesla" in r["participantes"]


def test_graph_rango_marca_la_reunion_rechazada(monkeypatch):
    evento = _graph_evento(responseStatus={"response": "declined"})
    assert _leer_graph(monkeypatch, evento)["respuesta_usuario"] == "declined"


def test_graph_pide_los_campos_nuevos_al_proveedor():
    assert "iCalUId" in graph._SELECT_RANGO
    assert "responseStatus" in graph._SELECT_RANGO


@pytest.mark.parametrize(
    "normalizar,evento",
    [
        (google.normalizar_evento_google, _google_evento()),
        (graph.normalizar_evento, _graph_evento()),
    ],
)
def test_el_normalizador_legado_no_cambia_de_forma(normalizar, evento):
    r = normalizar(evento)
    assert not {"ical_uid", "correos", "respuesta_usuario"} & set(r)


# ── el resumen distingue «hay que reconectar» de «el proveedor falló» ─────────


@pytest.mark.parametrize(
    "modulo,funcion,estado,reautenticar",
    [
        (google, "listar_reuniones_google_rango", 401, True),
        (google, "listar_reuniones_google_rango", 503, False),
        (graph, "listar_reuniones_rango", 401, True),
        (graph, "listar_reuniones_rango", 500, False),
    ],
)
def test_el_error_del_proveedor_indica_si_hay_que_reconectar(
    monkeypatch, modulo, funcion, estado, reautenticar
):
    from dossier.services.calendar_range import ErrorProveedorCalendario

    monkeypatch.setattr(modulo.requests, "get", lambda *a, **k: _Resp({}, status=estado))
    with pytest.raises(ErrorProveedorCalendario) as e:
        getattr(modulo, funcion)("tok", RANGO)
    assert e.value.reautenticar is reautenticar
