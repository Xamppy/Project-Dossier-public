"""Worker en background que procesa la cola de generación de dossiers."""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

from dossier.db.connection import is_database_configured
from dossier.db.session import _factory
from dossier.services.dossier_generation_job_service import (
    claim_next_queued_job,
    process_dossier_generation_job,
)

logger = logging.getLogger(__name__)


def worker_enabled() -> bool:
    raw = os.getenv("DOSSIER_GENERATION_WORKER_ENABLED", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def poll_interval_seconds() -> float:
    raw = os.getenv("DOSSIER_GENERATION_POLL_SECONDS", "2").strip()
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 2.0


def _worker_loop(stop: threading.Event) -> None:
    interval = poll_interval_seconds()
    logger.info(
        "Worker generación dossiers: iniciado (intervalo=%ss, enabled=%s)",
        interval,
        worker_enabled(),
    )
    while not stop.wait(interval):
        if not worker_enabled() or not is_database_configured():
            continue
        db = _factory()()
        try:
            while True:
                job = claim_next_queued_job(db)
                if job is None:
                    break
                process_dossier_generation_job(db, job.id)
        except Exception:
            logger.exception("Error en worker de generación de dossiers")
        finally:
            db.close()


def start_dossier_generation_worker() -> Callable[[], None]:
    stop = threading.Event()
    if not worker_enabled():
        logger.info("Worker generación dossiers desactivado (DOSSIER_GENERATION_WORKER_ENABLED=0)")
        return stop.set
    if not is_database_configured():
        logger.info("Worker generación dossiers omitido: PostgreSQL no configurado")
        return stop.set

    thread = threading.Thread(
        target=_worker_loop,
        args=(stop,),
        name="dossier-generation-worker",
        daemon=True,
    )
    thread.start()

    def shutdown() -> None:
        stop.set()
        thread.join(timeout=8)

    return shutdown
