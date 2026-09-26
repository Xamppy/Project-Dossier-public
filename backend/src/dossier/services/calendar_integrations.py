"""Persistencia de tokens OAuth de calendario (Microsoft Graph y Google Calendar)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.db.models import CalendarIntegration


def _initial_advance_minutes() -> int:
    """Valor inicial de anticipación al crear una integración (evita import circular)."""
    from dossier.services.calendar_automation import default_advance_minutes

    return default_advance_minutes()


def upsert_microsoft_calendar_tokens(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    access_token: str,
    refresh_token: str | None,
    expires_in_seconds: int,
    granted_scopes: str,
    id_token_claims: dict,
) -> CalendarIntegration:
    """
    Inserta o actualiza la fila ``calendar_integrations`` para ``provider='microsoft'``.

    Los campos ``*_encrypted`` guardan el valor en claro por ahora (MVP); cifrar en app antes.
    """
    claims = id_token_claims or {}
    provider_email = (claims.get("preferred_username") or claims.get("email") or None)
    if isinstance(provider_email, str):
        provider_email = provider_email.strip() or None
    provider_subject = (
        claims.get("oid") or claims.get("sub") or (str(provider_email) if provider_email else None)
    )
    if provider_subject is not None:
        provider_subject = str(provider_subject)[:255]

    expires_at = datetime.now(UTC) + timedelta(
        seconds=max(60, int(expires_in_seconds or 3600))
    )

    row = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == "microsoft",
        )
    ).scalar_one_or_none()

    if row is None:
        row = CalendarIntegration(
            user_id=user_id,
            organization_id=organization_id,
            provider="microsoft",
            advance_minutes=_initial_advance_minutes(),
            skip_internal_meetings=False,
        )
        db.add(row)

    row.organization_id = organization_id
    row.access_token_encrypted = access_token
    row.refresh_token_encrypted = refresh_token
    row.access_token_expires_at = expires_at
    row.granted_scopes = granted_scopes or None
    row.provider_email = provider_email
    row.provider_subject = provider_subject
    row.revoked_at = None
    row.is_enabled = True

    db.commit()
    db.refresh(row)
    return row


def upsert_google_calendar_tokens(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    access_token: str,
    refresh_token: str | None,
    expires_in_seconds: int,
    granted_scopes: str,
    userinfo: dict | None,
) -> CalendarIntegration:
    """
    Inserta o actualiza ``calendar_integrations`` para ``provider='google'``.

    ``userinfo`` suele venir de ``GET https://www.googleapis.com/oauth2/v2/userinfo``.
    """
    info = userinfo if userinfo is not None else {}
    provider_email = info.get("email") if info else None
    if isinstance(provider_email, str):
        provider_email = provider_email.strip() or None
    sub = info.get("id") or info.get("sub") if info else None
    provider_subject = None
    if sub is not None:
        provider_subject = str(sub)[:255]
    elif provider_email:
        provider_subject = str(provider_email)[:255]

    expires_at = datetime.now(UTC) + timedelta(
        seconds=max(60, int(expires_in_seconds or 3600))
    )

    row = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == "google",
        )
    ).scalar_one_or_none()

    if row is None:
        row = CalendarIntegration(
            user_id=user_id,
            organization_id=organization_id,
            provider="google",
            advance_minutes=_initial_advance_minutes(),
            skip_internal_meetings=False,
        )
        db.add(row)

    row.organization_id = organization_id
    row.access_token_encrypted = access_token
    if refresh_token:
        row.refresh_token_encrypted = refresh_token
    row.access_token_expires_at = expires_at
    row.granted_scopes = granted_scopes or None
    if userinfo is not None:
        row.provider_email = provider_email
        row.provider_subject = provider_subject
    row.revoked_at = None
    row.is_enabled = True

    db.commit()
    db.refresh(row)
    return row


def revoke_calendar_integration_for_user(
    db: Session,
    *,
    user_id: UUID,
    provider: str,
) -> CalendarIntegration:
    """Revoca la integración de calendario del usuario."""
    provider_key = (provider or "").strip().lower()
    if provider_key == "outlook":
        provider_key = "microsoft"
    if provider_key not in ("microsoft", "google"):
        raise ValueError("Proveedor no válido. Usa 'microsoft'/'outlook' o 'google'.")

    row = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == provider_key,
        )
    ).scalar_one_or_none()

    if row is None or row.revoked_at is not None or not row.is_enabled:
        raise LookupError("No hay una conexión activa con ese calendario.")

    now = datetime.now(UTC)
    row.revoked_at = now
    row.is_enabled = False
    row.access_token_encrypted = None
    row.refresh_token_encrypted = None

    from dossier.db.models import CalendarEvent

    pending = db.execute(
        select(CalendarEvent).where(
            CalendarEvent.calendar_integration_id == row.id,
            CalendarEvent.processing_status == "scheduled",
        )
    ).scalars().all()
    for event in pending:
        event.processing_status = "skipped"
        event.skip_reason = "Calendario desconectado por el usuario."

    db.commit()
    db.refresh(row)
    return row
