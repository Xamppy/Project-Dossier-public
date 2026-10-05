"""Bus de eventos en memoria del canal SSE de un job (ver dossier_progress_stream.py, S4.8).

Vive en memoria de un solo proceso: valido para el despliegue actual, donde el
worker de generacion corre en un hilo en background del mismo proceso que la
API (``dossier_generation_worker.py``) y publica aquí cada cambio de estado.
Si el servicio pasa a varios procesos/dynos, el stream sigue enterándose por su
consulta de respaldo a la base, pero con la latencia de ese intervalo; para
tiempo real entre procesos haría falta Redis pub/sub.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Any
from uuid import UUID

_LOCK = threading.Lock()
# Despierta a los streams que esperan un evento (en vez de sondear la base cada segundo).
_CAMBIO = threading.Condition(_LOCK)
_MAX_EVENTS_PER_JOB = 200
# Jobs que terminan sin que nadie los mire no se olvidan nunca: se descarta el más antiguo.
_MAX_JOBS = 1000

_events: dict[UUID, deque[tuple[int, str, dict[str, Any]]]] = defaultdict(
    lambda: deque(maxlen=_MAX_EVENTS_PER_JOB)
)
_seq: dict[UUID, int] = defaultdict(int)


def event_name_for_status(status: str | None) -> str:
    if status == "completed":
        return "job_completed"
    if status in ("failed", "cancelled"):
        return "job_failed"
    return "job_status"


def publish_if_changed(job_id: UUID, event: str, data: dict[str, Any]) -> int | None:
    """Agrega un evento solo si difiere del último publicado para ese job.

    Devuelve el id asignado, o ``None`` si no había cambio (evita duplicar
    eventos cuando el worker y el respaldo por base publican el mismo estado).
    """
    with _CAMBIO:
        buf = _events[job_id]
        if buf and buf[-1][1] == event and buf[-1][2] == data:
            return None
        _seq[job_id] += 1
        seq = _seq[job_id]
        buf.append((seq, event, data))
        while len(_events) > _MAX_JOBS:
            mas_antiguo = next(iter(_events))
            _events.pop(mas_antiguo, None)
            _seq.pop(mas_antiguo, None)
        _CAMBIO.notify_all()
        return seq


def wait_for_change(job_id: UUID, after_seq: int, timeout: float) -> None:
    """Bloquea hasta que el job tenga un evento posterior a ``after_seq`` o venza ``timeout``."""
    with _CAMBIO:
        _CAMBIO.wait_for(lambda: _seq.get(job_id, 0) > after_seq, timeout=timeout)


def latest_event(job_id: UUID) -> tuple[int, str, dict[str, Any]] | None:
    with _LOCK:
        buf = _events.get(job_id)
        return buf[-1] if buf else None


def events_since(job_id: UUID, last_seq: int) -> list[tuple[int, str, dict[str, Any]]]:
    """Eventos con id mayor a ``last_seq`` (para resincronizar tras una reconexión)."""
    with _LOCK:
        return [e for e in _events.get(job_id, ()) if e[0] > last_seq]


def forget(job_id: UUID) -> None:
    """Libera el estado de un job (se llama al llegar a un estado terminal)."""
    with _CAMBIO:
        _events.pop(job_id, None)
        _seq.pop(job_id, None)
