"""UX-KPI-01 · estrés del resumen: volumen, concurrencia y proveedor lento o caído (CA5, CA11).

Sin base de datos ni red: la lectura de calendarios y el acceso a datos se sustituyen. Se
verifica que los resultados son completos, acotados y que cualquier incompletitud se señala.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from dossier.services import dashboard_summary as ds
from dossier.services.calendar_range import ErrorProveedorCalendario, RangoConsulta, ResultadoRango
from dossier.services.meeting_identity import Fact, meeting_key
from dossier.services.meeting_prep_kpi import (
    CalendarEntry,
    collect_meetings,
    summarize_history,
    summarize_upcoming,
)

AS_OF = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)
RANGO = RangoConsulta(desde=AS_OF - timedelta(days=30), hasta=AS_OF + timedelta(days=7))


def _reunion(i, inicio):
    return {
        "id": f"ev{i}", "tema": "Reunión — Tesla", "descripcion": "Empresa: Tesla\nContacto: Ana Pérez",
        "participantes": "a@mi-empresa.test, ana@tesla.test", "correos": ["a@mi-empresa.test", "ana@tesla.test"],
        "inicio": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"), "todo_el_dia": False,
    }


# ── volumen ──────────────────────────────────────────────────────────────────


def test_volumen_miles_de_reuniones_y_hechos_se_resuelven_completos_y_rapido():
    n = 3000
    entradas = [
        CalendarEntry("google", "primary", "mi-empresa.test", _reunion(i, AS_OF - timedelta(minutes=10 * (i + 1))))
        for i in range(n)
    ]
    t0 = time.perf_counter()
    snap = collect_meetings(entradas, plan="pro")
    hechos = []
    for i in range(n):
        inicio = AS_OF - timedelta(minutes=10 * (i + 1))
        for rol in ("corporate", "person:1"):
            hechos.append(Fact(f"r{i}:{rol}", meeting_key("google", f"ev{i}"), rol, "manual",
                               inicio - timedelta(hours=1), inicio, frozenset({"corporate", "person:1"}), None))
    r = summarize_history(snap.meetings, snap.seen, hechos, measured_from=AS_OF - timedelta(days=30), as_of=AS_OF)
    assert time.perf_counter() - t0 < 5
    assert (r.eligible, r.on_time_meetings, r.on_time_dossiers) == (n, n, 2 * n)


def test_volumen_mas_de_ochenta_reuniones_futuras_no_se_truncan():
    ms = collect_meetings(
        [CalendarEntry("google", "primary", "mi-empresa.test", _reunion(i, AS_OF + timedelta(minutes=30 * (i + 1))))
         for i in range(200)],
        plan="pro",
    ).meetings
    disponible = {m.keys[0]: frozenset({"corporate", "person:1"}) for m in ms[:150]}
    r = summarize_upcoming(ms, disponible, as_of=AS_OF)
    assert (r.eligible, r.prepared, r.pending, r.percent) == (200, 150, 50, 75.0)


# ── degradación: proveedor lento o caído ─────────────────────────────────────


def _integracion(provider):
    return SimpleNamespace(provider=provider, provider_email="yo@mi-empresa.test", user_id=uuid.uuid4())


class _Db:
    def __init__(self, integraciones):
        self._i = integraciones

    def scalars(self, *_a, **_k):
        return SimpleNamespace(all=lambda: self._i)


def _leer(monkeypatch, integraciones, lector):
    monkeypatch.setattr(ds, "get_google_calendar_access_token_for_user", lambda db, uid: "t")
    monkeypatch.setattr(ds, "get_microsoft_graph_access_token_for_user", lambda db, uid: "t")
    monkeypatch.setattr(ds, "_leer_proveedor", lector)
    user = SimpleNamespace(id=uuid.uuid4(), email="yo@mi-empresa.test")
    return ds._leer_calendarios(_Db(integraciones), user, RANGO)


def test_un_proveedor_lento_corta_en_el_plazo_y_se_declara_no_disponible(monkeypatch):
    monkeypatch.setattr(ds, "PLAZO_PROVEEDORES_SEGUNDOS", 0.2)
    liberar = threading.Event()

    def lento(provider, token, rango):
        liberar.wait(3)
        return ResultadoRango()

    t0 = time.perf_counter()
    lectura = _leer(monkeypatch, [_integracion("google")], lento)
    liberar.set()
    assert time.perf_counter() - t0 < 2
    assert (lectura.estado, lectura.motivo) == ("unavailable", ds.R_NO_DISPONIBLE)


def test_un_proveedor_caido_invalida_la_lectura_aunque_el_otro_responda(monkeypatch):
    def lector(provider, token, rango):
        if provider == "microsoft":
            raise ErrorProveedorCalendario(502, "falla")
        return ResultadoRango(reuniones=[_reunion(1, AS_OF + timedelta(days=1))])

    lectura = _leer(monkeypatch, [_integracion("google"), _integracion("microsoft")], lector)
    assert lectura.estado == "unavailable" and lectura.entradas is None


def test_una_lectura_incompleta_nunca_se_declara_completa(monkeypatch):
    lectura = _leer(
        monkeypatch, [_integracion("google")],
        lambda p, t, r: ResultadoRango(reuniones=[_reunion(1, AS_OF)], completo=False, motivo_incompleto="limite_paginas"),
    )
    assert (lectura.estado, lectura.motivo) == ("unavailable", ds.R_INCOMPLETO)


def test_una_excepcion_inesperada_del_proveedor_no_tumba_el_resumen(monkeypatch):
    def roto(provider, token, rango):
        raise ValueError("respuesta corrupta")

    assert _leer(monkeypatch, [_integracion("google")], roto).estado == "unavailable"


def test_un_motivo_de_reconexion_gana_sobre_los_demas(monkeypatch):
    def lector(provider, token, rango):
        if provider == "google":
            raise ErrorProveedorCalendario(502, "x", reautenticar=True)
        return ResultadoRango(completo=False, motivo_incompleto="tiempo_agotado")

    lectura = _leer(monkeypatch, [_integracion("google"), _integracion("microsoft")], lector)
    assert lectura.motivo == ds.R_REAUTENTICAR


# ── concurrencia ─────────────────────────────────────────────────────────────


def test_el_cupo_de_calculos_simultaneos_esta_acotado_y_se_declara_ocupado(monkeypatch):
    monkeypatch.setattr(ds, "ESPERA_CUPO_SEGUNDOS", 0.05)
    tomados = [ds._CUPO.acquire() for _ in range(ds.MAX_CALCULOS_SIMULTANEOS)]
    try:
        user = SimpleNamespace(id=uuid.uuid4(), email="y@x.test", timezone="UTC", dossier_retention_days=None)
        org = SimpleNamespace(id=uuid.uuid4(), plan="pro", credits_balance=3, credits_monthly_limit=10)
        r = ds.build_dashboard_summary(_Db([]), user=user, org=org, now=AS_OF)
    finally:
        for _ in tomados:
            ds._CUPO.release()
        ds.SUMMARY_CACHE.clear()
    assert r["upcoming"]["state"] == "unavailable" and r["upcoming"]["reason"] == ds.R_OCUPADO
    assert r["credits"]["balance"] == 3  # los créditos no dependen del calendario
