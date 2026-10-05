"""Token de Google Calendar para el usuario de la app (``calendar_integrations`` + refresh OAuth2)."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import requests
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.db.models import CalendarIntegration
from dossier.services.calendar_integrations import upsert_google_calendar_tokens

logger = logging.getLogger(__name__)

_TOKEN_SKEW = timedelta(seconds=120)
# URL pública del endpoint OAuth2 de Google (no es un secreto).
_GOOGLE_OAUTH2_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # nosec B105


def _client_creds() -> tuple[str, str]:
    cid = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    if not cid or not secret:
        raise HTTPException(
            status_code=500,
            detail="Faltan GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET para renovar el token.",
        )
    return cid, secret


def get_google_calendar_access_token_for_user(db: Session, user_id: UUID) -> str:
    """
    Devuelve un ``access_token`` válido para Google Calendar API para ``user_id``.

    - Usa el token guardado si no está vencido (margen ``_TOKEN_SKEW``).
    - Si expiró y hay ``refresh_token``, llama a OAuth2 token endpoint y actualiza la fila.
    """
    row = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == "google",
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No hay Google Calendar conectado para este usuario. "
                "Usa GET /integrations/google/start (con JWT) y completa el login en Google."
            ),
        )
    if row.revoked_at is not None or not row.is_enabled:
        raise HTTPException(
            status_code=403,
            detail="La integración Google está desactivada o revocada. Vuelve a conectar.",
        )

    access = (row.access_token_encrypted or "").strip()
    if not access:
        raise HTTPException(
            status_code=404,
            detail="No hay token de acceso Google guardado. Vuelve a conectar Google Calendar.",
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
                "El acceso a Google expiró y no hay refresh_token. "
                "Vuelve a conectar Google Calendar desde la app."
            ),
        )

    client_id, client_secret = _client_creds()
    r = requests.post(
        _GOOGLE_OAUTH2_TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    try:
        body = r.json()
    except Exception:  # noqa: BLE001 - parseo tolerante de respuesta OAuth
        body = {}

    if r.status_code != 200 or "access_token" not in body:
        err = body.get("error_description") or body.get("error") or r.text[:300]
        logger.warning("Google token refresh error for user_id=%s: %s", user_id, err)
        raise HTTPException(
            status_code=401,
            detail=f"No se pudo renovar el token de Google: {err}. Vuelve a conectar.",
        )

    new_access = body["access_token"]
    expires_in = int(body.get("expires_in") or 3600)
    new_refresh = body.get("refresh_token") or refresh

    upsert_google_calendar_tokens(
        db,
        user_id=user_id,
        organization_id=row.organization_id,
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in_seconds=expires_in,
        granted_scopes=row.granted_scopes or (body.get("scope") or ""),
        userinfo=None,
    )
    return new_access
