"""Pruebas de estrés - S4.8: canal de estados progresivos.

Ver docs/dev/testing-policy.md §4: volumen, concurrencia, degradación.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from dossier.services.dossier_progress_events import events_since, forget, publish_if_changed
from dossier.services.dossier_progress_stream import stream_job_events


# --------------------------------------------------------------------------
# Volumen: ¿qué pasa con muchos eventos en un mismo job?
# --------------------------------------------------------------------------

def test_volumen_el_buffer_no_crece_sin_limite():
    """10 000 eventos en un job no deben acumularse sin límite (fuga de memoria)."""
    job_id = uuid.uuid4()
    try:
        inicio = time.perf_counter()
        for i in range(10_000):
            publish_if_changed(job_id, "job_status", {"status": "running", "i": i})
        transcurrido = time.perf_counter() - inicio

        pendientes = events_since(job_id, 0)
        assert len(pendientes) <= 200, "el buffer por job debe estar acotado (deque maxlen)"
        assert transcurrido < 2.0, f"10 000 publicaciones tardaron {transcurrido:.2f}s"
    finally:
        forget(job_id)


# --------------------------------------------------------------------------
# Concurrencia: ¿qué pasa con muchos jobs publicando a la vez?
# --------------------------------------------------------------------------

def test_concurrencia_jobs_distintos_no_se_mezclan_entre_hilos():
    """50 jobs, cada uno publicando 20 eventos desde su propio hilo: sin cruces."""
    job_ids = [uuid.uuid4() for _ in range(50)]

    def trabajar(job_id):
        for i in range(20):
            publish_if_changed(job_id, "job_status", {"status": "running", "paso": i})
        return job_id

    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(trabajar, job_ids))

        for job_id in job_ids:
            eventos = events_since(job_id, 0)
            assert len(eventos) == 20
            assert [e[2]["paso"] for e in eventos] == list(range(20))
    finally:
        for job_id in job_ids:
            forget(job_id)


# --------------------------------------------------------------------------
# Degradación: ¿qué pasa con muchos streams concurrentes consumiéndose?
# --------------------------------------------------------------------------

def test_degradacion_muchos_streams_concurrentes_terminan_rapido():
    """20 streams concurrentes, cada uno hasta estado terminal, sin bloquearse entre sí."""

    def consumir(_indice):
        job_id = uuid.uuid4()
        estados = iter([{"status": "running"}, {"status": "completed"}])

        def fetch():
            return next(estados, {"status": "completed"})

        frames = list(
            stream_job_events(job_id, fetch, sleep=lambda s: None, clock=time.monotonic)
        )
        return len(frames)

    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=20) as pool:
        conteos = list(pool.map(consumir, range(20)))
    transcurrido = time.perf_counter() - inicio

    assert conteos == [2] * 20  # running + completed, cada uno
    assert transcurrido < 2.0, f"20 streams concurrentes tardaron {transcurrido:.2f}s"
