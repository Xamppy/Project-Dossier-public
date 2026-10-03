"""UX-CAL-02 · lectura de calendario por intervalo (CA2, CA3, CA4, CA9).

Todo el tráfico a Google y Microsoft Graph es simulado: ninguna prueba sale a la red.
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
import requests

from dossier.services import google_calendar_api as google
from dossier.services import graph_calendar as graph
from dossier.services.calendar_range import (
    MAX_DIAS_RANGO,
    ErrorProveedorCalendario,
    RangoInvalido,
    parse_rango,
)

# ── Utilidades de prueba ─────────────────────────────────────────────────────


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = status < 400
        self.text = str(payload)

    def json(self):
        return self._payload


class _Reloj:
    """Reloj controlable: cada ``avanzar`` simula tiempo transcurrido."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _rango(desde="2026-10-01T00:00:00Z", hasta="2026-11-01T00:00:00Z"):
    return parse_rango(desde, hasta)


def _ev_google(i, **extra):
    base = {
        "id": f"g{i}",
        "summary": f"Reunión {i}",
        "start": {"dateTime": "2026-10-05T10:00:00-03:00"},
        "end": {"dateTime": "2026-10-05T11:00:00-03:00"},
    }
    base.update(extra)
    return base


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


def _zona(nombre):
    try:
        return ZoneInfo(nombre)
    except ZoneInfoNotFoundError:
        pytest.skip(f"Sin base de zonas horarias para {nombre}")


# ── CA9 · validación del intervalo ───────────────────────────────────────────


def test_parse_rango_normaliza_a_utc():
    r = parse_rango("2026-10-01T00:00:00-03:00", "2026-10-08T00:00:00-03:00")
    assert r.desde == datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    assert r.hasta == datetime(2026, 10, 8, 3, 0, tzinfo=UTC)
    assert r.como_dict() == {"desde": "2026-10-01T03:00:00Z", "hasta": "2026-10-08T03:00:00Z"}


def test_parse_rango_acepta_z_y_fracciones():
    r = parse_rango("2026-10-01T00:00:00.000Z", "2026-10-02T00:00:00Z")
    assert r.desde < r.hasta


def test_parse_rango_acepta_exactamente_el_maximo():
    r = parse_rango("2026-10-01T00:00:00Z", "2026-12-02T00:00:00Z")  # 62 días
    assert (r.hasta - r.desde).days == MAX_DIAS_RANGO


@pytest.mark.parametrize(
    "desde,hasta",
    [
        (None, "2026-10-02T00:00:00Z"),
        ("2026-10-01T00:00:00Z", None),
        ("2026-10-01T00:00:00", "2026-10-02T00:00:00Z"),  # sin offset
        ("2026-10-01", "2026-10-02"),  # solo fecha
        ("no-es-fecha", "2026-10-02T00:00:00Z"),
        ("2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"),  # orden inverso
        ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"),  # vacío
        ("2026-10-01T00:00:00Z", "2026-12-02T00:00:01Z"),  # 62 días + 1 s
        ("", ""),
    ],
)
def test_parse_rango_rechaza_entradas_invalidas(desde, hasta):
    with pytest.raises(RangoInvalido):
        parse_rango(desde, hasta)


# ── CA2 · paginación de Google ───────────────────────────────────────────────


def _google_paginado(paginas, visto):
    """``paginas``: lista de listas de eventos; el token de la página i es ``p{i+1}``."""

    def fake_get(url, headers=None, params=None, timeout=None):
        visto.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        idx = int((params or {}).get("pageToken", "p0")[1:])
        cuerpo = {"items": paginas[idx]}
        if idx + 1 < len(paginas):
            cuerpo["nextPageToken"] = f"p{idx + 1}"
        return _Resp(cuerpo)

    return fake_get


def test_google_recorre_todas_las_paginas(monkeypatch):
    visto: list = []
    paginas = [[_ev_google(i) for i in range(p * 3, p * 3 + 3)] for p in range(4)]
    monkeypatch.setattr(google.requests, "get", _google_paginado(paginas, visto))

    res = google.listar_reuniones_google_rango("tok", _rango())

    assert [r["id"] for r in res.reuniones] == [f"g{i}" for i in range(12)]
    assert res.completo is True and res.motivo_incompleto is None
    assert len(visto) == 4


def test_google_envia_intervalo_y_parametros_de_expansion(monkeypatch):
    visto: list = []
    monkeypatch.setattr(google.requests, "get", _google_paginado([[]], visto))

    google.listar_reuniones_google_rango("tok", _rango("2026-10-01T00:00:00-03:00", "2026-10-08T00:00:00-03:00"))

    p = visto[0]["params"]
    assert p["timeMin"] == "2026-10-01T03:00:00Z"
    assert p["timeMax"] == "2026-10-08T03:00:00Z"
    assert p["singleEvents"] is True  # expande recurrencias
    assert p["maxResults"] == 250
    assert p["orderBy"] == "startTime"
    assert "pageToken" not in p


def test_google_limite_de_paginas_devuelve_parcial_y_motivo(monkeypatch):
    visto: list = []
    paginas = [[_ev_google(p)] for p in range(30)]
    monkeypatch.setattr(google.requests, "get", _google_paginado(paginas, visto))

    res = google.listar_reuniones_google_rango("tok", _rango())

    assert len(visto) == 10
    assert len(res.reuniones) == 10
    assert res.completo is False
    assert res.motivo_incompleto == "limite_paginas"


def test_google_fallo_en_pagina_posterior_conserva_lo_recuperado(monkeypatch):
    visto: list = []

    def fake_get(url, headers=None, params=None, timeout=None):
        visto.append(params)
        if "pageToken" in params:
            return _Resp({"error": "boom"}, status=500)
        return _Resp({"items": [_ev_google(1)], "nextPageToken": "p1"})

    monkeypatch.setattr(google.requests, "get", fake_get)
    res = google.listar_reuniones_google_rango("tok", _rango())

    assert [r["id"] for r in res.reuniones] == ["g1"]
    assert res.completo is False
    assert res.motivo_incompleto == "error_proveedor"


def test_google_timeout_en_pagina_posterior_es_tiempo_agotado(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if "pageToken" in params:
            raise requests.Timeout("lento")
        return _Resp({"items": [_ev_google(1)], "nextPageToken": "p1"})

    monkeypatch.setattr(google.requests, "get", fake_get)
    res = google.listar_reuniones_google_rango("tok", _rango())

    assert res.completo is False
    assert res.motivo_incompleto == "tiempo_agotado"
    assert len(res.reuniones) == 1


def test_google_presupuesto_total_se_respeta_y_ajusta_timeout(monkeypatch):
    reloj = _Reloj()
    visto: list = []

    def fake_get(url, headers=None, params=None, timeout=None):
        visto.append(timeout)
        reloj.t += 8.0  # cada página tarda 8 s
        idx = int((params or {}).get("pageToken", "p0")[1:])
        return _Resp({"items": [_ev_google(idx)], "nextPageToken": f"p{idx + 1}"})

    monkeypatch.setattr(google.requests, "get", fake_get)
    res = google.listar_reuniones_google_rango("tok", _rango(), reloj=reloj)

    # 20 s de presupuesto: páginas a t=0, 8, 16; la cuarta no se pide (t=24).
    assert len(visto) == 3
    assert visto == [20.0, 12.0, 4.0]  # el timeout se ajusta al presupuesto restante
    assert res.completo is False
    assert res.motivo_incompleto == "tiempo_agotado"


def test_google_primera_pagina_fallida_es_error_tipado(monkeypatch):
    monkeypatch.setattr(google.requests, "get", lambda *a, **k: _Resp({"e": 1}, status=503))
    with pytest.raises(ErrorProveedorCalendario) as exc:
        google.listar_reuniones_google_rango("tok", _rango())
    assert exc.value.status_code == 502


def test_google_primera_pagina_con_timeout_es_504(monkeypatch):
    def fake_get(*a, **k):
        raise requests.Timeout("lento")

    monkeypatch.setattr(google.requests, "get", fake_get)
    with pytest.raises(ErrorProveedorCalendario) as exc:
        google.listar_reuniones_google_rango("tok", _rango())
    assert exc.value.status_code == 504


def test_google_error_de_red_en_primera_pagina_es_502(monkeypatch):
    def fake_get(*a, **k):
        raise requests.ConnectionError("sin red")

    monkeypatch.setattr(google.requests, "get", fake_get)
    with pytest.raises(ErrorProveedorCalendario) as exc:
        google.listar_reuniones_google_rango("tok", _rango())
    assert exc.value.status_code == 502


def test_google_sin_eventos_no_es_error_y_es_completo(monkeypatch):
    monkeypatch.setattr(google.requests, "get", _google_paginado([[]], []))
    res = google.listar_reuniones_google_rango("tok", _rango())
    assert res.reuniones == [] and res.completo is True


# ── CA3 / CA4 · fechas, día completo, recurrencias, canceladas (Google) ──────


def test_google_dia_completo_conserva_fechas_civiles_con_fin_exclusivo(monkeypatch):
    ev = {
        "id": "ad1",
        "summary": "Feriado",
        "start": {"date": "2026-10-12"},
        "end": {"date": "2026-10-13"},
    }
    monkeypatch.setattr(google.requests, "get", _google_paginado([[ev]], []))
    res = google.listar_reuniones_google_rango("tok", _rango())
    r = res.reuniones[0]
    assert (r["inicio"], r["fin"], r["todo_el_dia"]) == ("2026-10-12", "2026-10-13", True)


def test_google_conserva_offset_y_cruce_de_medianoche(monkeypatch):
    ev = _ev_google(
        1,
        start={"dateTime": "2026-10-05T23:30:00-03:00"},
        end={"dateTime": "2026-10-06T00:30:00-03:00"},
    )
    monkeypatch.setattr(google.requests, "get", _google_paginado([[ev]], []))
    r = google.listar_reuniones_google_rango("tok", _rango()).reuniones[0]
    assert r["inicio"] == "2026-10-05T23:30:00-03:00"
    assert r["fin"] == "2026-10-06T00:30:00-03:00"


def test_google_excluye_ocurrencias_canceladas_e_incluye_recurrentes(monkeypatch):
    items = [
        _ev_google("a", id="serie_20261005T130000Z", recurringEventId="serie"),
        _ev_google("b", id="serie_20261012T130000Z", recurringEventId="serie", status="cancelled"),
        _ev_google("c", id="serie_20261019T130000Z", recurringEventId="serie"),
    ]
    monkeypatch.setattr(google.requests, "get", _google_paginado([items], []))
    res = google.listar_reuniones_google_rango("tok", _rango())
    assert [r["id"] for r in res.reuniones] == ["serie_20261005T130000Z", "serie_20261019T130000Z"]


# ── CA2 · paginación de Microsoft Graph ──────────────────────────────────────

_NEXT_OK = "https://graph.microsoft.com/v1.0/me/calendar/calendarView?startDateTime=x&$skiptoken=abc"


def _graph_paginado(paginas, visto, base_next=_NEXT_OK):
    def fake_get(url, headers=None, params=None, timeout=None):
        visto.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        idx = 0 if params else int(url.rsplit("$skiptoken=p", 1)[1]) if "$skiptoken=p" in url else 0
        cuerpo = {"value": paginas[idx]}
        if idx + 1 < len(paginas):
            cuerpo["@odata.nextLink"] = base_next.replace("abc", f"p{idx + 1}")
        return _Resp(cuerpo)

    return fake_get


def test_graph_recorre_next_link_hasta_el_final(monkeypatch):
    visto: list = []
    paginas = [[_ev_graph(i) for i in range(p * 2, p * 2 + 2)] for p in range(3)]
    monkeypatch.setattr(graph.requests, "get", _graph_paginado(paginas, visto))

    res = graph.listar_reuniones_rango("tok", _rango())

    assert [r["id"] for r in res.reuniones] == [f"m{i}" for i in range(6)]
    assert res.completo is True
    assert len(visto) == 3
    # El nextLink se sigue tal cual: sin reenviar params (ya vienen en la URL).
    assert visto[1]["params"] is None


def test_graph_envia_intervalo_y_tamano_de_pagina(monkeypatch):
    visto: list = []
    monkeypatch.setattr(graph.requests, "get", _graph_paginado([[]], visto))
    graph.listar_reuniones_rango("tok", _rango("2026-10-01T00:00:00-03:00", "2026-10-08T00:00:00-03:00"))
    p = visto[0]["params"]
    assert p["startDateTime"] == "2026-10-01T03:00:00Z"
    assert p["endDateTime"] == "2026-10-08T03:00:00Z"
    assert p["$top"] == 250
    assert "isCancelled" in p["$select"] and "originalStartTimeZone" in p["$select"]


@pytest.mark.parametrize(
    "enlace",
    [
        "https://evil.example.com/v1.0/me/calendar/calendarView?$skiptoken=1",
        "http://graph.microsoft.com/v1.0/me/calendar/calendarView?$skiptoken=1",
        "https://graph.microsoft.com.evil.example/v1.0/me/calendar/calendarView?$skiptoken=1",
        "https://graph.microsoft.com/v1.0/users/otro/calendar/calendarView?$skiptoken=1",
        "https://user@graph.microsoft.com/v1.0/me/calendar/calendarView?$skiptoken=1",
        "//evil.example.com/v1.0/me/calendar/calendarView",
    ],
)
def test_graph_no_sigue_next_link_de_otro_host_o_ruta(monkeypatch, enlace):
    llamadas: list = []

    def fake_get(url, headers=None, params=None, timeout=None):
        llamadas.append(url)
        return _Resp({"value": [_ev_graph(1)], "@odata.nextLink": enlace})

    monkeypatch.setattr(graph.requests, "get", fake_get)
    res = graph.listar_reuniones_rango("tok", _rango())

    assert len(llamadas) == 1, "no debe seguir el enlace sospechoso (ni enviar el token allí)"
    assert res.completo is False and res.motivo_incompleto == "error_proveedor"
    assert [r["id"] for r in res.reuniones] == ["m1"]


def test_graph_limite_de_paginas(monkeypatch):
    visto: list = []

    def fake_get(url, headers=None, params=None, timeout=None):
        visto.append(url)
        return _Resp({"value": [_ev_graph(len(visto))], "@odata.nextLink": _NEXT_OK})

    monkeypatch.setattr(graph.requests, "get", fake_get)
    res = graph.listar_reuniones_rango("tok", _rango())
    assert len(visto) == 10
    assert res.completo is False and res.motivo_incompleto == "limite_paginas"


def test_graph_error_en_pagina_posterior_es_parcial(monkeypatch):
    estado = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        estado["n"] += 1
        if estado["n"] == 1:
            return _Resp({"value": [_ev_graph(1)], "@odata.nextLink": _NEXT_OK})
        return _Resp({"error": {}}, status=429)

    monkeypatch.setattr(graph.requests, "get", fake_get)
    res = graph.listar_reuniones_rango("tok", _rango())
    assert len(res.reuniones) == 1
    assert res.completo is False and res.motivo_incompleto == "error_proveedor"


def test_graph_primera_pagina_fallida_es_error_tipado(monkeypatch):
    monkeypatch.setattr(graph.requests, "get", lambda *a, **k: _Resp({"e": 1}, status=500))
    with pytest.raises(ErrorProveedorCalendario) as exc:
        graph.listar_reuniones_rango("tok", _rango())
    assert exc.value.status_code == 502


def test_graph_primera_pagina_timeout_es_504(monkeypatch):
    def fake_get(*a, **k):
        raise requests.Timeout("lento")

    monkeypatch.setattr(graph.requests, "get", fake_get)
    with pytest.raises(ErrorProveedorCalendario) as exc:
        graph.listar_reuniones_rango("tok", _rango())
    assert exc.value.status_code == 504


def test_graph_presupuesto_total(monkeypatch):
    reloj = _Reloj()
    tiempos: list = []

    def fake_get(url, headers=None, params=None, timeout=None):
        tiempos.append(timeout)
        reloj.t += 10.0
        return _Resp({"value": [_ev_graph(len(tiempos))], "@odata.nextLink": _NEXT_OK})

    monkeypatch.setattr(graph.requests, "get", fake_get)
    res = graph.listar_reuniones_rango("tok", _rango(), reloj=reloj)
    assert tiempos == [20.0, 10.0]
    assert res.completo is False and res.motivo_incompleto == "tiempo_agotado"


# ── CA4 · canceladas y recurrencias (Graph) ──────────────────────────────────


def test_graph_excluye_canceladas_y_conserva_ocurrencias(monkeypatch):
    items = [
        _ev_graph(1, type="occurrence"),
        _ev_graph(2, type="occurrence", isCancelled=True),
        _ev_graph(3, type="occurrence", isCancelled=False),
    ]
    monkeypatch.setattr(graph.requests, "get", _graph_paginado([items], []))
    res = graph.listar_reuniones_rango("tok", _rango())
    assert [r["id"] for r in res.reuniones] == ["m1", "m3"]


# ── CA3 · día completo en Outlook ────────────────────────────────────────────


def _graph_dia_completo(inicio_utc, fin_utc, zona):
    return _ev_graph(
        9,
        isAllDay=True,
        start={"dateTime": inicio_utc, "timeZone": "UTC"},
        end={"dateTime": fin_utc, "timeZone": "UTC"},
        originalStartTimeZone=zona,
        originalEndTimeZone=zona,
    )


@pytest.mark.parametrize(
    "zona_original,inicio_utc,fin_utc",
    [
        # Santiago: UTC-3 en octubre de 2026 (horario de verano), nombre de Windows.
        ("Pacific SA Standard Time", "2026-10-12T03:00:00.0000000", "2026-10-13T03:00:00.0000000"),
        # Mismo caso con nombre IANA.
        ("America/Santiago", "2026-10-12T03:00:00.0000000", "2026-10-13T03:00:00.0000000"),
        # Londres: UTC+1 en octubre (BST) → medianoche local = 23:00 UTC del día anterior.
        ("GMT Standard Time", "2026-10-11T23:00:00.0000000", "2026-10-12T23:00:00.0000000"),
        # UTC puro.
        ("UTC", "2026-10-12T00:00:00.0000000", "2026-10-13T00:00:00.0000000"),
        # Sídney: UTC+11 en octubre (horario de verano austral).
        ("AUS Eastern Standard Time", "2026-10-11T13:00:00.0000000", "2026-10-12T13:00:00.0000000"),
    ],
)
def test_graph_dia_completo_se_resuelve_en_la_zona_original(
    monkeypatch, zona_original, inicio_utc, fin_utc
):
    _zona("America/Santiago")
    ev = _graph_dia_completo(inicio_utc, fin_utc, zona_original)
    monkeypatch.setattr(graph.requests, "get", _graph_paginado([[ev]], []))
    r = graph.listar_reuniones_rango("tok", _rango()).reuniones[0]
    assert (r["inicio"], r["fin"], r["todo_el_dia"]) == ("2026-10-12", "2026-10-13", True)


def test_graph_dia_completo_en_cambio_de_horario_de_santiago(monkeypatch):
    """Cambio a horario de verano en Santiago: 2026-09-06 (UTC-4 → UTC-3).

    El 5 de septiembre la medianoche local es 04:00 UTC; el 7, 03:00 UTC. Un evento
    de varios días que cruza el cambio no debe desplazar ni el inicio ni el fin.
    """
    _zona("America/Santiago")
    ev = _graph_dia_completo(
        "2026-09-05T04:00:00.0000000", "2026-09-08T03:00:00.0000000", "Pacific SA Standard Time"
    )
    monkeypatch.setattr(graph.requests, "get", _graph_paginado([[ev]], []))
    r = graph.listar_reuniones_rango("tok", _rango("2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")).reuniones[0]
    assert (r["inicio"], r["fin"]) == ("2026-09-05", "2026-09-08")


def test_graph_dia_completo_con_zona_desconocida_usa_medianoche_mas_cercana(monkeypatch):
    ev = _graph_dia_completo("2026-10-12T03:00:00.0000000", "2026-10-13T03:00:00.0000000", "Zona Inventada")
    monkeypatch.setattr(graph.requests, "get", _graph_paginado([[ev]], []))
    r = graph.listar_reuniones_rango("tok", _rango()).reuniones[0]
    assert (r["inicio"], r["fin"]) == ("2026-10-12", "2026-10-13")


def test_graph_dia_completo_sin_zona_original_usa_medianoche_mas_cercana(monkeypatch):
    ev = _graph_dia_completo("2026-10-11T13:00:00.0000000", "2026-10-12T13:00:00.0000000", None)
    ev.pop("originalStartTimeZone")
    ev.pop("originalEndTimeZone")
    monkeypatch.setattr(graph.requests, "get", _graph_paginado([[ev]], []))
    r = graph.listar_reuniones_rango("tok", _rango()).reuniones[0]
    # +11 h: 13:00 UTC está más cerca de la medianoche siguiente (UTC+11 → día 12).
    assert (r["inicio"], r["fin"]) == ("2026-10-12", "2026-10-13")


def test_graph_evento_con_hora_se_entrega_como_instante_utc(monkeypatch):
    ev = _ev_graph(
        1,
        start={"dateTime": "2026-10-05T23:30:00.0000000", "timeZone": "UTC"},
        end={"dateTime": "2026-10-06T00:30:00.0000000", "timeZone": "UTC"},
    )
    monkeypatch.setattr(graph.requests, "get", _graph_paginado([[ev]], []))
    r = graph.listar_reuniones_rango("tok", _rango()).reuniones[0]
    assert (r["inicio"], r["fin"], r["todo_el_dia"]) == (
        "2026-10-05T23:30:00Z",
        "2026-10-06T00:30:00Z",
        False,
    )


def test_modo_legado_de_graph_sigue_forzando_utc_sin_cambios():
    """El modo sin intervalo conserva su contrato: no se toca ``normalizar_evento``."""
    ev = _graph_dia_completo("2026-10-12T03:00:00.0000000", "2026-10-13T03:00:00.0000000", "UTC")
    out = graph.normalizar_evento(ev)
    assert out["inicio"] == "2026-10-12T03:00:00Z"
    assert out["todo_el_dia"] is True
