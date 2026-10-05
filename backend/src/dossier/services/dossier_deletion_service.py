"""Eliminación de dossiers con invalidación de caché Redis y calendario."""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from dossier.cache.corporate_dossier_redis import delete_dossier_redis_cache
from dossier.db.models import Dossier
from dossier.services.calendar_automation import suppress_calendar_event_if_no_dossiers_remain
from dossier.services.summary_cache import SUMMARY_CACHE

logger = logging.getLogger(__name__)


def invalidate_dossier_redis_cache(dossier: Dossier) -> None:
    """Elimina la entrada Redis asociada al dossier (si tiene ``cache_key``)."""
    cache_key = (dossier.cache_key or "").strip()
    if not cache_key:
        return
    delete_dossier_redis_cache(cache_key)


def delete_dossier_record(db: Session, dossier: Dossier) -> UUID | None:
    """
    Borra un dossier de la sesión e invalida su caché Redis.

    Devuelve ``calendar_event_id`` para suprimir automatización tras el commit.
    """
    calendar_event_id = dossier.calendar_event_id
    invalidate_dossier_redis_cache(dossier)
    # Indicadores de Resumen: se invalida después del commit; antes, un cálculo vería aún el dossier.
    event.listen(
        db, "after_commit", lambda _s, uid=dossier.requested_by_user_id: SUMMARY_CACHE.invalidate(uid), once=True
    )
    db.delete(dossier)
    return calendar_event_id


def finalize_dossier_deletions(
    db: Session,
    calendar_event_ids: set[UUID | None],
) -> None:
    """Tras ``flush``/``delete``, evita regeneración automática en eventos vacíos."""
    for event_id in calendar_event_ids:
        suppress_calendar_event_if_no_dossiers_remain(db, event_id)


def delete_dossiers_in_folder(
    db: Session,
    *,
    organization_id: UUID,
    folder_id: UUID,
) -> int:
    """Elimina todos los dossiers de una carpeta de la organización."""
    rows = db.execute(
        select(Dossier).where(
            Dossier.organization_id == organization_id,
            Dossier.dossier_folder_id == folder_id,
        )
    ).scalars().all()
    if not rows:
        return 0

    calendar_event_ids: set[UUID | None] = set()
    for dossier in rows:
        calendar_event_ids.add(delete_dossier_record(db, dossier))

    db.flush()
    finalize_dossier_deletions(db, calendar_event_ids)
    return len(rows)
