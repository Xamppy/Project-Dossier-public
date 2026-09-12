"""Bus de eventos en memoria del canal SSE de un job (ver dossier_progress_stream.py, S4.8).

Vive en memoria de un solo proceso: valido para el despliegue actual, donde el
worker de generacion corre en un hilo en background del mismo proceso que la
API (``dossier_generation_worker.py``). Si el servicio pasa a varios
procesos/dynos, esto deja de alcanzar a todos los suscriptores y hace falta
Redis pub/sub — no antes, seria over-engineering para el despliegue de hoy.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Any
from uuid import UUID

_LOCK = threading.Lock()
_MAX_EVENTS_PER_JOB = 200

_events: dict[UUID, deque[tuple[int, str, dict[str, Any]]]] = defaultdict(
    lambda: deque(maxlen=_MAX_EVENTS_PER_JOB)
)
_seq: dict[UUID, int] = defaultdict(int)


def publish_if_changed(job_id: UUID, event: str, data: dict[str, Any]) -> int | None:
    """Agrega un evento solo si difiere del último publicado para ese job.

    Devuelve el id asignado, o ``None`` si no había cambio (evita duplicar
    eventos cuando varias conexiones sondean el mismo job).
    """
    with _LOCK:
        buf = _events[job_id]
        if buf and buf[-1][1] == event and buf[-1][2] == data:
            return None
        _seq[job_id] += 1
        seq = _seq[job_id]
        buf.append((seq, event, data))
        return seq


def events_since(job_id: UUID, last_seq: int) -> list[tuple[int, str, dict[str, Any]]]:
    """Eventos con id mayor a ``last_seq`` (para resincronizar tras una reconexión)."""
    with _LOCK:
        return [e for e in _events.get(job_id, ()) if e[0] > last_seq]


def forget(job_id: UUID) -> None:
    """Libera el estado de un job (se llama al llegar a un estado terminal)."""
    with _LOCK:
        _events.pop(job_id, None)
        _seq.pop(job_id, None)
