"""Canal de estados progresivos (SSE) de un job de generacion de dossiers.

Ver specs/proposals/S0.11-protocolo-estados-progresivos.md (tarea S4.8). El
worker de generacion publica cada cambio de ``status`` en el bus en memoria
(``dossier_progress_events``); este modulo espera esos avisos y los traduce a
eventos SSE. La fila en Postgres solo se relee como respaldo cada
``DEFAULT_DB_POLL_SECONDS`` (job borrado, permisos, worker en otro proceso).

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

from dossier.services.dossier_progress_events import (
    event_name_for_status,
    events_since,
    forget,
    latest_event,
    publish_if_changed,
    wait_for_change,
)

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
TERMINAL_EVENTS = frozenset({"job_completed", "job_failed"})

# Tope de espera por vuelta: el worker despierta el stream antes si publica algo.
DEFAULT_POLL_SECONDS = 5.0
# Respaldo: la base solo se consulta cada tanto (job borrado, worker en otro proceso).
DEFAULT_DB_POLL_SECONDS = 10.0
DEFAULT_HEARTBEAT_SECONDS = 15.0
DEFAULT_MAX_SECONDS = 600.0  # corte de seguridad: 10 minutos de stream abierto


def sse_frame(event: str, data: dict[str, Any], event_id: int) -> str:
    """Un frame segun la especificacion W3C de Server-Sent Events."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


def stream_job_events(
    job_id: UUID,
    fetch_job: Callable[[], dict[str, Any] | None],
    *,
    last_event_id: int | None = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    db_poll_seconds: float = DEFAULT_DB_POLL_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[str]:
    """Genera frames SSE para un job hasta que llega a un estado terminal.

    El worker publica cada cambio de estado en el bus; el stream lo espera
    (``wait_for_change``) en vez de sondear la base, que queda como respaldo
    cada ``db_poll_seconds``. CA1: todo cliente recibe el estado actual al
    conectar, aunque el bus ya lo tuviera. CA3: con ``Last-Event-ID`` se
    reenvía solo lo posterior. CA4: ``: ping`` tras ``heartbeat_seconds``
    sin actividad. ``sleep`` es inyectable para las pruebas.
    """
    start = clock()
    last_sent = start
    last_seq = last_event_id or 0

    def esperar(segundos: float) -> None:
        if sleep is not None:
            sleep(segundos)
        else:
            wait_for_change(job_id, last_seq, segundos)

    if last_event_id is not None:
        for seq, event, data in events_since(job_id, last_event_id):
            yield sse_frame(event, data, seq)
            last_seq = seq
            last_sent = clock()

    job = fetch_job()
    last_db = clock()
    if job is None:
        return
    status = job.get("status")
    publish_if_changed(job_id, event_name_for_status(status), job)
    actual = latest_event(job_id)
    # Cliente nuevo, o el bus se reinició (su numeración quedó por debajo del Last-Event-ID).
    if last_event_id is None or (actual is not None and actual[0] < last_event_id):
        if actual is not None:
            yield sse_frame(actual[1], actual[2], actual[0])
            last_seq = actual[0]
            last_sent = clock()
    else:
        for seq, event, data in events_since(job_id, last_seq):
            yield sse_frame(event, data, seq)
            last_seq = seq
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

        esperar(poll_seconds)

        if clock() - last_db >= db_poll_seconds:
            job = fetch_job()
            last_db = clock()
            if job is None:
                return
            publish_if_changed(job_id, event_name_for_status(job.get("status")), job)

        terminal = False
        for seq, event, data in events_since(job_id, last_seq):
            yield sse_frame(event, data, seq)
            last_seq = seq
            last_sent = clock()
            terminal = terminal or event in TERMINAL_EVENTS
        if terminal:
            forget(job_id)
            return
