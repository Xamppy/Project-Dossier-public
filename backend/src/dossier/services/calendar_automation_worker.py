"""Hilo en background que ejecuta la automatización de calendario periódicamente."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from dossier.db.connection import is_database_configured
from dossier.db.session import _factory
from dossier.services.calendar_automation import (
    automation_enabled,
    poll_interval_seconds,
    run_calendar_automation_tick,
)

logger = logging.getLogger(__name__)


def _automation_loop(stop: threading.Event) -> None:
    interval = poll_interval_seconds()
    logger.info(
        "Automatización de calendario: hilo iniciado (intervalo=%ss, enabled=%s)",
        interval,
        automation_enabled(),
    )
    while not stop.wait(interval):
        if not automation_enabled() or not is_database_configured():
            continue
        db = _factory()()
        try:
            summary = run_calendar_automation_tick(db)
            logger.info("Automatización calendario: tick %s", summary)
        except Exception:
            logger.exception("Error en tick de automatización de calendario")
        finally:
            db.close()


def start_calendar_automation_thread() -> Callable[[], None]:
    """Arranca el worker daemon. Devuelve función para detenerlo."""
    stop = threading.Event()
    if not automation_enabled():
        logger.info("Automatización de calendario desactivada (CALENDAR_AUTOMATION_ENABLED=0)")
        return stop.set
    if not is_database_configured():
        logger.info("Automatización de calendario omitida: PostgreSQL no configurado")
        return stop.set

    thread = threading.Thread(
        target=_automation_loop,
        args=(stop,),
        name="calendar-automation",
        daemon=True,
    )
    thread.start()

    def shutdown() -> None:
        stop.set()
        thread.join(timeout=5)

    return shutdown
