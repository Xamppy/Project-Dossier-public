"""Tests - S4.8: generador de frames SSE (independiente de FastAPI/DB).

No instrumenta agent_progress por-agente: eso exige tocar el pipeline
LangGraph (ver .harness/progress.md, S4.8). Este generador traduce cambios de
`status` del job a eventos job_status/job_completed/job_failed, mas heartbeat.
"""
from __future__ import annotations

import uuid

from dossier.services.dossier_progress_events import forget
from dossier.services.dossier_progress_stream import sse_frame, stream_job_events


class _RelojFalso:
    def __init__(self):
        self.t = 0.0

    def avanzar(self, segundos: float) -> None:
        self.t += segundos

    def __call__(self) -> float:
        return self.t


def _fetch_secuencia(estados: list[dict | None]):
    it = iter(estados)

    def fetch():
        return next(it, estados[-1] if estados else None)

    return fetch


def test_sse_frame_formato_w3c():
    frame = sse_frame("job_status", {"status": "queued"}, 7)
    assert frame == 'id: 7\nevent: job_status\ndata: {"status": "queued"}\n\n'


def test_emite_job_status_inmediato_al_conectar():
    job_id = uuid.uuid4()
    fetch = _fetch_secuencia([{"status": "running"}, {"status": "running"}])
    reloj = _RelojFalso()
    frames = []
    gen = stream_job_events(
        job_id, fetch, sleep=lambda s: reloj.avanzar(s), clock=reloj, max_seconds=0.01
    )
    frames.append(next(gen))
    assert "event: job_status" in frames[0]
    assert '"status": "running"' in frames[0]


def test_termina_en_estado_terminal_y_limpia_el_bus():
    job_id = uuid.uuid4()
    fetch = _fetch_secuencia([{"status": "completed"}])
    reloj = _RelojFalso()
    frames = list(
        stream_job_events(job_id, fetch, sleep=lambda s: reloj.avanzar(s), clock=reloj)
    )
    assert len(frames) == 1
    assert "event: job_completed" in frames[0]
    # forget() ya se llamó: el próximo publish para este job vuelve a numerar desde 1.
    from dossier.services.dossier_progress_events import publish_if_changed

    assert publish_if_changed(job_id, "job_status", {"status": "queued"}) == 1
    forget(job_id)


def test_emite_heartbeat_si_no_hay_cambios():
    job_id = uuid.uuid4()
    estado = {"status": "running"}
    reloj = _RelojFalso()

    def fetch():
        return estado

    def dormir(segundos: float) -> None:
        reloj.avanzar(segundos)

    gen = stream_job_events(
        job_id,
        fetch,
        sleep=dormir,
        clock=reloj,
        heartbeat_seconds=15.0,
        poll_seconds=5.0,
        max_seconds=40.0,
    )
    frames = list(gen)
    assert frames[0].startswith("id: 1\nevent: job_status")
    assert ": ping\n\n" in frames


def test_reconexion_con_last_event_id_no_duplica_el_estado_actual():
    job_id = uuid.uuid4()
    estado = {"status": "running"}
    reloj1 = _RelojFalso()
    primero = list(
        stream_job_events(
            job_id,
            lambda: estado,
            sleep=lambda s: reloj1.avanzar(s),
            clock=reloj1,
            max_seconds=0.0,
        )
    )
    assert len(primero) == 1  # solo el job_status inicial, seq=1

    reloj2 = _RelojFalso()
    segundo = list(
        stream_job_events(
            job_id,
            lambda: estado,
            last_event_id=1,
            sleep=lambda s: reloj2.avanzar(s),
            clock=reloj2,
            max_seconds=0.0,
        )
    )
    assert segundo == []  # nada nuevo desde seq=1: mismo estado, no se duplica
    forget(job_id)


def test_corte_de_seguridad_max_seconds_termina_el_stream():
    job_id = uuid.uuid4()
    estado = {"status": "running"}
    reloj = _RelojFalso()

    def dormir(segundos: float) -> None:
        reloj.avanzar(segundos)

    frames = list(
        stream_job_events(
            job_id,
            lambda: estado,
            sleep=dormir,
            clock=reloj,
            heartbeat_seconds=1000.0,
            poll_seconds=1.0,
            max_seconds=3.0,
        )
    )
    # No hay heartbeat (heartbeat_seconds altisimo) ni cambios de estado: solo el inicial.
    assert len(frames) == 1
    forget(job_id)


def test_job_inexistente_termina_el_stream_sin_frames():
    job_id = uuid.uuid4()
    frames = list(stream_job_events(job_id, lambda: None, sleep=lambda s: None, clock=lambda: 0.0))
    assert frames == []
