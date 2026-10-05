"""Token de Microsoft Graph para el usuario de la app (fila ``calendar_integrations`` + refresh MSAL)."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import msal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.db.models import CalendarIntegration
from dossier.services.calendar_integrations import upsert_microsoft_calendar_tokens

logger = logging.getLogger(__name__)

# Mismos scopes que ``app.py`` (OAuth); deben coincidir para refresh.
_MICROSOFT_SCOPES = ["Calendars.Read", "User.Read"]
_TOKEN_SKEW = timedelta(seconds=120)


def _msal_app() -> msal.ConfidentialClientApplication:
    client_id = os.getenv("MICROSOFT_CLIENT_ID")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET")
    tenant = os.getenv("MICROSOFT_TENANT_ID", "common")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="Faltan MICROSOFT_CLIENT_ID o MICROSOFT_CLIENT_SECRET para refrescar el token.",
        )
    authority = f"https://login.microsoftonline.com/{tenant}"
    return msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )


def get_microsoft_graph_access_token_for_user(db: Session, user_id: UUID) -> str:
    """
    Devuelve un ``access_token`` válido para Microsoft Graph para ``user_id``.

    - Usa el token guardado si no está vencido (margen ``_TOKEN_SKEW``).
    - Si expiró y hay ``refresh_token``, llama a MSAL, actualiza la fila y devuelve el nuevo token.
    """
    row = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == "microsoft",
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No hay calendario Microsoft conectado para este usuario. "
                "Usa GET /integrations/microsoft/start (con JWT) y completa el login en Microsoft."
            ),
        )
    if row.revoked_at is not None or not row.is_enabled:
        raise HTTPException(
            status_code=403,
            detail="La integración Microsoft está desactivada o revocada. Vuelve a conectar Outlook.",
        )

    access = (row.access_token_encrypted or "").strip()
    if not access:
        raise HTTPException(
            status_code=404,
            detail="No hay token de acceso Microsoft guardado. Vuelve a conectar Outlook.",
        )

    now = datetime.now(UTC)
    exp = row.access_token_expires_at
    if exp is not None and now + _TOKEN_SKEW < exp:
        return access

    refresh = (row.refresh_token_encrypted or "").strip()
    if not refresh:
        raise HTTPException(
            status_code=401,
            detail=(
                "El acceso a Microsoft expiró y no hay refresh_token. "
                "Vuelve a conectar Outlook desde la app."
            ),
        )

    app = _msal_app()
    result = app.acquire_token_by_refresh_token(refresh, scopes=_MICROSOFT_SCOPES)
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or "refresh fallido"
        logger.warning("MSAL refresh error for user_id=%s: %s", user_id, err)
        raise HTTPException(
            status_code=401,
            detail=f"No se pudo renovar el token de Microsoft: {err}. Vuelve a conectar Outlook.",
        )

    new_refresh = result.get("refresh_token") or refresh
    expires_in = int(result.get("expires_in") or 3600)
    claims = result.get("id_token_claims") or {}
    granted = row.granted_scopes or " ".join(_MICROSOFT_SCOPES)

    upsert_microsoft_calendar_tokens(
        db,
        user_id=user_id,
        organization_id=row.organization_id,
        access_token=result["access_token"],
        refresh_token=new_refresh,
        expires_in_seconds=expires_in,
        granted_scopes=granted,
        id_token_claims=claims if isinstance(claims, dict) else {},
    )
    return result["access_token"]
