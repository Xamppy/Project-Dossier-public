"""
JWT de acceso para sesiones del dashboard (HS256).

El token lleva el id de usuario (`sub`) y el email; el cliente lo envía en
`Authorization: Bearer ...`. La clave `JWT_SECRET` debe ser larga y aleatoria
en producción (nunca commitear en el repo).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt


def _secret() -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if len(secret) < 16:
        raise RuntimeError(
            "JWT_SECRET no está definida o es demasiado corta (mínimo 16 caracteres). "
            "Añádela en .env; en producción usa al menos 32 bytes aleatorios."
        )
    return secret


def create_access_token(
    *,
    user_id: str,
    email: str,
    organization_id: str | None = None,
    role: str | None = None,
) -> str:
    """
    Genera un JWT firmado con tiempo de expiración configurable.

    `organization_id`: tenant activo (organización primaria del usuario en registro/login).
    `role`: rol RBAC en la organización (`admin`, `user`, `viewer`).
    """
    minutes = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 días por defecto
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    if organization_id:
        payload["org_id"] = organization_id
    if role:
        payload["role"] = role.strip().lower()
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Valida firma y expiración; lanza PyJWTError si el token es inválido."""
    return jwt.decode(token, _secret(), algorithms=["HS256"])


def create_microsoft_oauth_state(*, user_id: str, organization_id: str) -> str:
    """
    Token corto (JWT) que Microsoft devuelve en ``state`` al callback.
    Vincula el flujo OAuth al usuario de la app (``sub``) y a su organización (``org_id``).
    Caducidad breve para reducir riesgo si el enlace filtra.
    """
    expire = datetime.now(UTC) + timedelta(minutes=15)
    payload: dict[str, Any] = {
        "purpose": "microsoft_oauth",
        "sub": user_id,
        "org_id": organization_id,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_microsoft_oauth_state(token: str) -> dict[str, Any]:
    """Valida el ``state`` del callback Microsoft; lanza PyJWTError si no aplica."""
    payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    if payload.get("purpose") != "microsoft_oauth":
        raise ValueError("state inválido: propósito incorrecto")
    return payload


def create_google_oauth_state(*, user_id: str, organization_id: str) -> str:
    """
    Token corto (JWT) que Google devuelve en ``state`` al callback.
    Vincula el flujo OAuth al usuario de la app (``sub``) y a su organización (``org_id``).
    """
    expire = datetime.now(UTC) + timedelta(minutes=15)
    payload: dict[str, Any] = {
        "purpose": "google_oauth",
        "sub": user_id,
        "org_id": organization_id,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_google_oauth_state(token: str) -> dict[str, Any]:
    """Valida el ``state`` del callback Google; lanza PyJWTError o ValueError si no aplica."""
    payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    if payload.get("purpose") != "google_oauth":
        raise ValueError("state inválido: propósito incorrecto")
    return payload


def assert_jwt_secret_configured() -> None:
    """Útil al arrancar rutas de auth: falla con mensaje claro si falta JWT_SECRET."""
    _secret()
