"""Worker en background que purga dossiers según la retención configurada por usuario."""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from dossier.db.connection import is_database_configured
from dossier.db.models import Dossier, User
from dossier.db.session import _factory
from dossier.services.dossier_deletion_service import (
    delete_dossier_record,
    finalize_dossier_deletions,
)
from dossier.services.meeting_prep_evidence import purge_expired_facts

logger = logging.getLogger(__name__)


def worker_enabled() -> bool:
    raw = os.getenv("DOSSIER_RETENTION_WORKER_ENABLED", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def poll_interval_seconds() -> float:
    raw = os.getenv("DOSSIER_RETENTION_POLL_SECONDS", "3600").strip()
    try:
        return max(300.0, float(raw))
    except ValueError:
        return 3600.0


def purge_expired_dossiers(db) -> int:
    """
    Elimina dossiers cuya antigüedad supera ``users.dossier_retention_days``.

    Solo aplica a usuarios con retención numérica (7, 14, 30 o 90). ``NULL`` = sin purga.
    """
    now = datetime.now(UTC)
    users = db.execute(
        select(User).where(User.dossier_retention_days.is_not(None))
    ).scalars().all()
    if not users:
        return 0

    total_deleted = 0
    for user in users:
        days = user.dossier_retention_days
        if days is None or days <= 0:
            continue
        cutoff = now - timedelta(days=int(days))
        rows = db.execute(
            select(Dossier).where(
                Dossier.requested_by_user_id == user.id,
                Dossier.created_at < cutoff,
            )
        ).scalars().all()
        if not rows:
            continue

        calendar_event_ids: set = set()
        for dossier in rows:
            calendar_event_ids.add(delete_dossier_record(db, dossier))

        db.flush()
        finalize_dossier_deletions(db, calendar_event_ids)
        total_deleted += len(rows)
        logger.info(
            "Retención: %s dossier(s) purgados para user=%s (>%s días)",
            len(rows),
            user.id,
            days,
        )

    if total_deleted:
        db.commit()
    return total_deleted


def _worker_loop(stop: threading.Event) -> None:
    interval = poll_interval_seconds()
    logger.info(
        "Worker retención dossiers: iniciado (intervalo=%ss, enabled=%s)",
        interval,
        worker_enabled(),
    )
    while not stop.wait(interval):
        if not worker_enabled() or not is_database_configured():
            continue
        db = _factory()()
        try:
            purge_expired_dossiers(db)
            purge_expired_facts(db)
            db.commit()
        except Exception:
            logger.exception("Error en worker de retención de dossiers")
            db.rollback()
        finally:
            db.close()


def start_dossier_retention_worker() -> Callable[[], None]:
    stop = threading.Event()
    if not worker_enabled():
        logger.info(
            "Worker retención dossiers desactivado (DOSSIER_RETENTION_WORKER_ENABLED=0)"
        )
        return stop.set
    if not is_database_configured():
        logger.info("Worker retención dossiers omitido: PostgreSQL no configurado")
        return stop.set

    thread = threading.Thread(
        target=_worker_loop,
        args=(stop,),
        name="dossier-retention-worker",
        daemon=True,
    )
    thread.start()

    def shutdown() -> None:
        stop.set()
        thread.join(timeout=8)

    return shutdown
