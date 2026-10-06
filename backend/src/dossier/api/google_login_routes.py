"""
Inicio de sesión con Google (OpenID Connect, flujo de código). Contrato en
`specs/proposals/UX-AUTH-01-login-google.md`.

Distinto del flujo de calendario de `app.py` (`/integrations/google/start`): aquí no hay sesión
previa, se piden solo alcances de identidad y no se guardan tokens de Google.

CSRF: el ``state`` es un JWT con un ``nonce`` que también va en una cookie HttpOnly; el callback
exige que ambos coincidan, así un ``code`` ajeno no abre sesión en este navegador.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import jwt
import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from jwt.exceptions import PyJWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.api.auth_routes import (
    _signup_org_credits,
    allocate_org_slug,
    get_db_if_configured,
    load_session_membership,
)
from dossier.db.models import OAuthAccount, Organization, OrgMembership, User
from dossier.org_workspace import ORG_NAME_PERSONAL_PLACEHOLDER
from dossier.security import create_access_token
from dossier.security.jwt_tokens import _secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["Autenticación app"])

COOKIE_NONCE = "dossier_google_login"
_PROPOSITO = "google_login"
_VIGENCIA = timedelta(minutes=10)


def _frontend() -> str:
    return os.getenv("FRONTEND_URL", "").strip().rstrip("/")


def _error() -> RedirectResponse:
    return RedirectResponse(f"{_frontend()}/login?error=google", status_code=302)


def _credenciales() -> tuple[str, str] | None:
    cid = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    secreto = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    return (cid, secreto) if cid and secreto else None


def _redirect_uri(request: Request) -> str:
    fija = (os.getenv("GOOGLE_LOGIN_REDIRECT_URI") or "").strip()
    return fija or str(request.url_for("google_login_callback"))


def _canjear_codigo(code: str, redirect_uri: str) -> dict[str, Any]:
    cid, secreto = _credenciales() or ("", "")
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": cid,
            "client_secret": secreto,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _perfil_google(access_token: str) -> dict[str, Any]:
    r = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def resolver_usuario_google(
    db: Session, perfil: dict[str, Any]
) -> tuple[User, Organization, OrgMembership]:
    """Usuario de la sesión: por ``sub`` vinculado, si no por correo, si no se crea con espacio personal."""
    sub = str(perfil["sub"])
    email = str(perfil["email"]).strip().lower()

    user = db.execute(
        select(User)
        .join(OAuthAccount, OAuthAccount.user_id == User.id)
        .where(OAuthAccount.provider == "google", OAuthAccount.provider_user_id == sub)
    ).scalar_one_or_none()

    if user is None:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            credits_balance, credits_monthly_limit = _signup_org_credits()
            org = Organization(
                name=ORG_NAME_PERSONAL_PLACEHOLDER,
                slug=allocate_org_slug(db, email),
                credits_balance=credits_balance,
                credits_monthly_limit=credits_monthly_limit,
                settings={"workspace_kind": "personal"},
            )
            user = User(email=email, full_name=(str(perfil.get("name") or "").strip()[:255] or None))
            db.add_all([org, user])
            db.flush()
            db.add(OrgMembership(organization_id=org.id, user_id=user.id, role="admin", is_primary_org=True))
        elif not user.email_verified:
            # Nadie probó ser dueño de ese correo: quien creó la cuenta no conserva la contraseña.
            user.password_hash = None
        db.add(OAuthAccount(user_id=user.id, provider="google", provider_user_id=sub))

    user.email_verified = True
    user.last_login_at = datetime.now(UTC)
    db.commit()

    pair = load_session_membership(db, user.id)
    if pair is None:
        raise LookupError("usuario sin organización")
    return user, pair[0], pair[1]


@router.get("/login")
def google_login_inicio(request: Request) -> RedirectResponse:
    credenciales = _credenciales()
    if credenciales is None:
        return _error()
    nonce = secrets.token_urlsafe(24)
    state = jwt.encode(
        {"purpose": _PROPOSITO, "nonce": nonce, "exp": datetime.now(UTC) + _VIGENCIA},
        _secret(),
        algorithm="HS256",
    )
    params = {
        "client_id": credenciales[0],
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    resp = RedirectResponse(
        f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}", status_code=302
    )
    resp.set_cookie(
        COOKIE_NONCE,
        nonce,
        max_age=int(_VIGENCIA.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return resp


@router.get("/callback", name="google_login_callback")
def google_login_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db_if_configured),
) -> RedirectResponse:
    resp = _abrir_sesion(request, db, code=code, state=state, error=error)
    resp.delete_cookie(COOKIE_NONCE, path="/")
    return resp


def _abrir_sesion(
    request: Request, db: Session, *, code: str | None, state: str | None, error: str | None
) -> RedirectResponse:
    if error or not code or not state:
        return _error()
    try:
        payload = jwt.decode(state, _secret(), algorithms=["HS256"])
    except PyJWTError:
        return _error()
    cookie = request.cookies.get(COOKIE_NONCE) or ""
    nonce = str(payload.get("nonce") or "")
    if payload.get("purpose") != _PROPOSITO or not cookie or not secrets.compare_digest(nonce, cookie):
        return _error()

    try:
        tokens = _canjear_codigo(code, _redirect_uri(request))
        perfil = _perfil_google(tokens["access_token"])
    except Exception:  # cualquier fallo de Google vuelve al login, sin detalle
        logger.warning("Fallo al canjear el código de Google", exc_info=True)
        return _error()
    if perfil.get("email_verified") is not True or not perfil.get("sub") or not perfil.get("email"):
        return _error()

    try:
        user, org, membresia = resolver_usuario_google(db, perfil)
    except Exception:  # la sesión no se abre; el detalle queda en el log
        logger.exception("No se pudo resolver el usuario de Google")
        db.rollback()
        return _error()

    token = create_access_token(
        user_id=str(user.id), email=user.email, organization_id=str(org.id), role=membresia.role
    )
    return RedirectResponse(f"{_frontend()}/auth/google#token={token}", status_code=302)
