"""Canal de estados progresivos (SSE) de un job de generacion de dossiers.

Ver specs/proposals/S0.11-protocolo-estados-progresivos.md (tarea S4.8). El
worker de generacion (``dossier_generation_worker.py``) sigue siendo el mismo
bucle de sondeo a Postgres cada 2s: este modulo sondea la misma fila con mas
frecuencia y traduce los cambios de ``status`` a eventos SSE.

No instrumenta el interior del pipeline LangGraph: no hay eventos
``agent_progress`` por-agente todavia (requeriria tocar
``corporate_dossier_graph.py`` y compania). Ver ``.harness/progress.md``, S4.8.

Separado de FastAPI y de la sesion de base de datos a proposito: ``fetch_job``
es cualquier callable que devuelva el dict de ``serialize_job()`` o ``None``,
lo que permite testear el generador entero sin levantar la app ni Postgres.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

from dossier.services.dossier_progress_events import events_since, forget, publish_if_changed

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

DEFAULT_POLL_SECONDS = 1.0
DEFAULT_HEARTBEAT_SECONDS = 15.0
DEFAULT_MAX_SECONDS = 600.0  # corte de seguridad: 10 minutos de stream abierto


def sse_frame(event: str, data: dict[str, Any], event_id: int) -> str:
    """Un frame segun la especificacion W3C de Server-Sent Events."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


def _event_name_for_status(status: str | None) -> str:
    if status == "completed":
        return "job_completed"
    if status in ("failed", "cancelled"):
        return "job_failed"
    return "job_status"


def stream_job_events(
    job_id: UUID,
    fetch_job: Callable[[], dict[str, Any] | None],
    *,
    last_event_id: int | None = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[str]:
    """Genera frames SSE para un job hasta que llega a un estado terminal.

    CA1 (estado inmediato al conectar) y CA3 (reconexion sin duplicar) se
    resuelven con el mismo mecanismo: ``publish_if_changed`` solo emite si el
    dato difiere del ultimo publicado, asi que repetir el estado actual tras
    un replay no genera un evento nuevo. CA4 (heartbeat a los 15s de
    inactividad) es el ``: ping`` del bucle principal.
    """
    start = clock()
    last_sent = start

    if last_event_id is not None:
        for seq, event, data in events_since(job_id, last_event_id):
            yield sse_frame(event, data, seq)
            last_sent = clock()

    job = fetch_job()
    if job is None:
        return
    status = job.get("status")
    new_seq = publish_if_changed(job_id, _event_name_for_status(status), job)
    if new_seq is not None:
        yield sse_frame(_event_name_for_status(status), job, new_seq)
        last_sent = clock()
    if status in TERMINAL_STATUSES:
        forget(job_id)
        return

    while True:
        now = clock()
        if now - last_sent >= heartbeat_seconds:
            yield ": ping\n\n"
            last_sent = now
        if now - start >= max_seconds:
            return

        sleep(poll_seconds)

        job = fetch_job()
        if job is None:
            return
        status = job.get("status")
        new_seq = publish_if_changed(job_id, _event_name_for_status(status), job)
        if new_seq is not None:
            yield sse_frame(_event_name_for_status(status), job, new_seq)
            last_sent = clock()
        if status in TERMINAL_STATUSES:
            forget(job_id)
            return
