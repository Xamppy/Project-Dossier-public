"""S4.8 (seguimiento): el canal SSE reacciona a eventos en vez de sondear Postgres cada segundo.

Ver el resumen técnico de conexión frontend-backend (2026-10-01): el stream consultaba
la base cada segundo por conexión. Ahora el worker publica cada cambio de estado en el
bus en memoria y el stream lo espera; la base queda como respaldo periódico.
"""
from __future__ import annotations

import threading
import time
import uuid

from dossier.services import dossier_progress_events as bus
from dossier.services.dossier_progress_stream import stream_job_events


class _Reloj:
    def __init__(self):
        self.t = 0.0

    def avanzar(self, s: float) -> None:
        self.t += s

    def __call__(self) -> float:
        return self.t


# --- CA1: estado inmediato al conectar ---------------------------------------


def test_cliente_nuevo_recibe_el_estado_actual_aunque_el_bus_ya_lo_tenga():
    """Segunda pestaña o recarga sin Last-Event-ID: antes no recibía nada hasta otro cambio."""
    job_id = uuid.uuid4()
    estado = {"status": "running"}
    bus.publish_if_changed(job_id, "job_status", estado)  # lo publicó el worker antes
    reloj = _Reloj()
    try:
        frames = list(
            stream_job_events(
                job_id, lambda: estado, sleep=reloj.avanzar, clock=reloj, max_seconds=0.0
            )
        )
        assert len(frames) == 1
        assert '"status": "running"' in frames[0]
    finally:
        bus.forget(job_id)


def test_reconexion_tras_reinicio_del_servidor_recibe_el_estado_actual():
    """El bus vive en memoria: tras un reinicio numera desde 1 y el Last-Event-ID del cliente
    (p. ej. 5) quedaría por encima de todo evento nuevo si no se detecta."""
    job_id = uuid.uuid4()
    reloj = _Reloj()
    try:
        frames = list(
            stream_job_events(
                job_id,
                lambda: {"status": "running"},
                last_event_id=5,
                sleep=reloj.avanzar,
                clock=reloj,
                max_seconds=0.0,
            )
        )
        assert len(frames) == 1
        assert '"status": "running"' in frames[0]
    finally:
        bus.forget(job_id)


# --- Despertar por evento, sin sondear la base --------------------------------


def test_el_stream_despierta_con_el_evento_del_worker_sin_consultar_la_base():
    job_id = uuid.uuid4()
    consultas = {"n": 0}

    def fetch():
        consultas["n"] += 1
        return {"status": "running"}

    frames: list[str] = []

    def consumir():
        frames.extend(
            stream_job_events(job_id, fetch, poll_seconds=5.0, db_poll_seconds=60.0, max_seconds=10.0)
        )

    hilo = threading.Thread(target=consumir)
    inicio = time.perf_counter()
    hilo.start()
    time.sleep(0.2)
    bus.publish_if_changed(job_id, "job_completed", {"status": "completed"})
    hilo.join(timeout=3)

    assert not hilo.is_alive()
    assert time.perf_counter() - inicio < 2.0, "debía despertar con el evento, no al vencer el sondeo"
    assert consultas["n"] == 1, "solo la lectura inicial: el resto llega por el bus"
    assert any("event: job_completed" in f for f in frames)


def test_respaldo_por_base_detecta_cambios_si_nadie_publica():
    """Worker en otro proceso: el bus no se entera, la consulta periódica sí."""
    job_id = uuid.uuid4()
    estados = iter([{"status": "running"}, {"status": "running"}, {"status": "completed"}])
    ultimo = {"v": {"status": "running"}}

    def fetch():
        ultimo["v"] = next(estados, ultimo["v"])
        return ultimo["v"]

    reloj = _Reloj()
    frames = list(
        stream_job_events(
            job_id,
            fetch,
            sleep=reloj.avanzar,
            clock=reloj,
            poll_seconds=5.0,
            db_poll_seconds=10.0,
            heartbeat_seconds=1000.0,
            max_seconds=120.0,
        )
    )

    assert "event: job_completed" in frames[-1]
    assert reloj.t < 120.0


# --- Bus: espera con aviso y memoria acotada ---------------------------------


def test_esperar_cambio_vuelve_apenas_hay_un_evento_nuevo():
    job_id = uuid.uuid4()
    try:
        threading.Timer(0.1, lambda: bus.publish_if_changed(job_id, "job_status", {"s": 1})).start()
        inicio = time.perf_counter()
        bus.wait_for_change(job_id, 0, timeout=5.0)
        assert time.perf_counter() - inicio < 1.0
    finally:
        bus.forget(job_id)


def test_esperar_cambio_respeta_el_tiempo_maximo_sin_eventos():
    inicio = time.perf_counter()
    bus.wait_for_change(uuid.uuid4(), 0, timeout=0.1)
    assert time.perf_counter() - inicio < 1.0


def test_el_bus_no_acumula_jobs_sin_limite(monkeypatch):
    """Jobs que terminan sin que nadie los mire no deben quedar en memoria para siempre."""
    monkeypatch.setattr(bus, "_MAX_JOBS", 50)
    ids = [uuid.uuid4() for _ in range(200)]
    try:
        for job_id in ids:
            bus.publish_if_changed(job_id, "job_completed", {"status": "completed"})
        assert len(bus._events) <= 50
        assert bus.events_since(ids[-1], 0), "el más reciente sigue disponible"
    finally:
        for job_id in ids:
            bus.forget(job_id)
