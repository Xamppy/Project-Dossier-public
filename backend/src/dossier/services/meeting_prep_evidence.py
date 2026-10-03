"""
Evidencia mínima de generación (UX-KPI-01): registro idempotente, marca de borrado, purga y
lectura. Guarda hechos —no contenido—: claves de ámbito y evento, origen, finalización real,
inicio de la reunión y el conjunto esperado. Ningún nombre, correo ni cuerpo de dossier.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from dossier.db.models import DossierGenerationFact, PrepEvidenceMeta
from dossier.services.meeting_identity import Fact, meeting_key

#: Un hecho se conserva mientras su reunión pueda caer en el historial de 30 días con margen
#: para preparaciones anticipadas (el calendario se lee hasta 62 días).
FACT_RETENTION_DAYS = 90


def record_generation_fact(
    db: Session,
    *,
    result_key: str,
    organization_id: UUID,
    user_id: UUID,
    provider: str,
    external_event_id: str,
    role_key: str,
    origin: str,
    dossier_id: UUID | None,
    expected_keys: list[str] | None,
    meeting_starts_at: datetime | None,
    completed_at: datetime,
    calendar_key: str = "primary",
) -> bool:
    """Inserta el hecho si ``result_key`` no existe. ``True`` si lo creó, ``False`` si ya estaba.

    No hace commit: viaja en la misma transacción que el resultado que registra.
    """
    stmt = (
        pg_insert(DossierGenerationFact)
        .values(
            result_key=result_key,
            organization_id=organization_id,
            user_id=user_id,
            provider=provider,
            calendar_key=calendar_key,
            external_event_id=external_event_id,
            role_key=role_key,
            origin=origin,
            dossier_id=dossier_id,
            expected_keys=expected_keys,
            meeting_starts_at=meeting_starts_at,
            generation_completed_at=completed_at,
        )
        .on_conflict_do_nothing(index_elements=["result_key"])
        .returning(DossierGenerationFact.id)
    )
    return db.execute(stmt).scalar_one_or_none() is not None


def mark_dossiers_deleted(
    db: Session,
    dossier_ids: Iterable[UUID],
    *,
    when: datetime | None = None,
) -> int:
    """Anota cuándo se borró el documento. La primera marca manda: no se reescribe."""
    ids = list(dossier_ids)
    if not ids:
        return 0
    result = db.execute(
        update(DossierGenerationFact)
        .where(
            DossierGenerationFact.dossier_id.in_(ids),
            DossierGenerationFact.dossier_deleted_at.is_(None),
        )
        .values(dossier_deleted_at=when or datetime.now(UTC))
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def _fact_reference_time():
    """Instante que decide cuánto vive un hecho: el inicio de su reunión, o la finalización."""
    return func.coalesce(
        DossierGenerationFact.meeting_starts_at, DossierGenerationFact.generation_completed_at
    )


def purge_expired_facts(
    db: Session,
    *,
    now: datetime | None = None,
    keep_days: int = FACT_RETENTION_DAYS,
) -> int:
    """Borra hechos cuya reunión (o finalización, si no hay inicio) quedó fuera de la ventana."""
    corte = (now or datetime.now(UTC)) - timedelta(days=keep_days)
    result = db.execute(delete(DossierGenerationFact).where(_fact_reference_time() < corte))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def load_facts(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    since: datetime,
) -> list[Fact]:
    """Hechos del usuario en su organización cuya referencia temporal es ``>= since``."""
    filas = db.execute(
        select(DossierGenerationFact).where(
            DossierGenerationFact.organization_id == organization_id,
            DossierGenerationFact.user_id == user_id,
            or_(
                and_(
                    DossierGenerationFact.meeting_starts_at.is_not(None),
                    DossierGenerationFact.meeting_starts_at >= since,
                ),
                DossierGenerationFact.generation_completed_at >= since,
            ),
        )
    ).scalars().all()
    return [
        Fact(
            result_key=f.result_key,
            meeting_key=meeting_key(f.provider, f.external_event_id, f.calendar_key),
            role_key=f.role_key,
            origin=f.origin,
            completed_at=f.generation_completed_at,
            meeting_starts_at=f.meeting_starts_at,
            expected_keys=frozenset(f.expected_keys) if f.expected_keys is not None else None,
            deleted_at=f.dossier_deleted_at,
        )
        for f in filas
    ]


def recording_started_at(db: Session) -> datetime | None:
    """Desde cuándo se registra la evidencia; ``None`` si la tabla aún no existe o está vacía."""
    return db.execute(select(PrepEvidenceMeta.recording_started_at)).scalar_one_or_none()
