"""S5.10 · B6: dos pestañas siguen el mismo job y una limpia el bus antes que la otra.

``forget()`` vacía el buffer del job cuando un stream entrega el terminal. Si otro
stream aún no lo había leído, esperaba un evento que ya no iba a llegar hasta el
corte de 600 s. Ahora la consulta de respaldo a la base le entrega el terminal.
"""
from __future__ import annotations

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


def _stream(job_id, estado, reloj):
    return stream_job_events(
        job_id,
        lambda: dict(estado),
        sleep=reloj.avanzar,
        clock=reloj,
        poll_seconds=1.0,
        db_poll_seconds=10.0,
        heartbeat_seconds=1_000.0,
        max_seconds=120.0,
    )


def test_si_otro_stream_limpio_el_bus_este_igual_recibe_el_terminal():
    job_id = uuid.uuid4()
    estado = {"id": str(job_id), "status": "running"}
    reloj = _Reloj()
    try:
        b = _stream(job_id, estado, reloj)
        assert "event: job_status" in next(b)

        bus.publish_if_changed(job_id, "stage_progress", {"stage_id": "person.pdl_enrich"})
        estado["status"] = "completed"
        bus.publish_if_changed(job_id, "job_completed", dict(estado))
        bus.forget(job_id)  # el otro stream entregó el terminal y limpió el bus

        restantes = list(b)

        assert any("event: job_completed" in f for f in restantes)
        assert reloj.t < 30, "no espera al corte de seguridad"
    finally:
        bus.forget(job_id)


def test_tras_un_reinicio_del_bus_a_mitad_de_job_llegan_los_eventos_nuevos():
    job_id = uuid.uuid4()
    estado = {"id": str(job_id), "status": "running"}
    reloj = _Reloj()
    try:
        bus.publish_if_changed(job_id, "job_status", {"n": 1})
        bus.publish_if_changed(job_id, "job_status", {"n": 2})
        b = _stream(job_id, estado, reloj)
        next(b)  # snapshot actual (numeración 3)

        bus.forget(job_id)  # reinicio del bus: numera de nuevo desde 1
        bus.publish_if_changed(job_id, "stage_progress", {"stage_id": "person.pdl_enrich", "status": "running"})
        siguiente = next(b)

        assert "event: stage_progress" in siguiente
    finally:
        bus.forget(job_id)
