"""Aplicación FastAPI (rutas HTTP). El punto de entrada del servidor está en `main.py` en la raíz."""
from __future__ import annotations

import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

import msal
import requests
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from jwt.exceptions import PyJWTError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import Request

from dossier.api.admin_routes import router as admin_router
from dossier.api.auth_routes import (
    OrgAuthContext,
    auth_payload_and_user,
    get_current_user,
    get_current_user_and_org,
    get_db_if_configured,
    require_mutator,
)
from dossier.api.auth_routes import (
    router as auth_router,
)
from dossier.api.dossier_job_routes import router as dossier_jobs_router
from dossier.api.dossier_routes import router as dossiers_router
from dossier.api.dossier_stream_routes import router as dossier_stream_router
from dossier.api.integrations_routes import router as integrations_router
from dossier.billing.credit_policy import (
    assert_sufficient_credits,
    credit_charging_enabled,
)
from dossier.billing.entitlements import (
    assert_automation_allowed,
    assert_depth_allowed,
    default_depth_for_plan,
    normalize_depth_for_plan,
)
from dossier.cache.corporate_dossier_redis import (
    dossier_corporate_redis_health,
    warmup_corporate_dossier_redis,
)
from dossier.config import PROJECT_ROOT, load_env
from dossier.db import is_database_configured
from dossier.db.connection import get_engine
from dossier.db.models import Organization, User
from dossier.org_dossier_context import format_dossier_context_for_prompt
from dossier.schemas.calendar_dossier import CalendarGenerarDossiersBody
from dossier.schemas.dossier_generation import DossierDepth
from dossier.security.jwt_tokens import (
    create_google_oauth_state,
    create_microsoft_oauth_state,
    decode_google_oauth_state,
    decode_microsoft_oauth_state,
)
from dossier.services import listar_reuniones, obtener_reunion_por_id
from dossier.services.calendar_automation_worker import start_calendar_automation_thread
from dossier.services.calendar_event_dossiers import (
    generate_dossiers_from_calendar_event,
    persist_calendar_dossiers,
)
from dossier.services.calendar_integrations import (
    upsert_google_calendar_tokens,
    upsert_microsoft_calendar_tokens,
)
from dossier.services.calendar_range import (
    ErrorProveedorCalendario,
    RangoConsulta,
    RangoInvalido,
    ResultadoRango,
    parse_rango,
)
from dossier.services.dossier_generation_job_service import (
    enqueue_calendar_dossier_job,
    estimate_reunion_credits,
)
from dossier.services.dossier_generation_worker import start_dossier_generation_worker
from dossier.services.dossier_retention_worker import start_dossier_retention_worker
from dossier.services.google_calendar_api import (
    diagnostico_google_calendar,
    listar_reuniones_google,
    listar_reuniones_google_rango,
    obtener_reunion_google_por_id,
)
from dossier.services.google_calendar_token import get_google_calendar_access_token_for_user
from dossier.services.graph_calendar import (
    coerce_reunion_payload,
    diagnostico_microsoft_calendar,
    listar_reuniones_rango,
)
from dossier.services.microsoft_calendar_token import get_microsoft_graph_access_token_for_user
from dossier.services.output_language import effective_output_language

load_env()

logger = logging.getLogger(__name__)


def _parse_cors_origins(raw: str) -> list[str]:
    """
    Normaliza CORS_ORIGINS: quita BOM/espacios, comillas (ASCII/tipográficas) y barra final.
    El navegador envía Origin sin barra final; si en Railway dejaste una, no coincidía.
    """
    # Comillas “curvas” típicas al copiar desde Word/Slack
    t = (
        raw.strip()
        .strip("\ufeff")
        .translate(
            str.maketrans(
                {  # type: ignore[arg-type]  # dict[str,str] literal, maketrans acepta str|int|None en el valor
                    "\u201c": '"',
                    "\u201d": '"',
                    "\u2018": "'",
                    "\u2019": "'",
                }
            )
        )
    )
    out: list[str] = []
    for part in t.split(","):
        o = part.strip().strip('"').strip("'").rstrip("/")
        if o:
            out.append(o)
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Arranque/apagado de la app.

    Tras aplicar el SQL de migración (`docs/sql/schema_project_dossier.sql`), puedes
    poner `DATABASE_AUTO_CREATE_TABLES=0` en `.env` para no ejecutar `create_all`
    al arrancar (solo tu DDL en PostgreSQL).

    Si dejas el valor por defecto, SQLAlchemy crea tablas/columnas que falten
    (útil en desarrollo sin haber corrido aún toda la migración).
    """
    if is_database_configured():
        engine = get_engine()
        from dossier.db.schema_patches import apply_schema_patches

        auto = os.getenv("DATABASE_AUTO_CREATE_TABLES", "1").strip().lower()
        if auto not in ("0", "false", "no"):
            from dossier.db import models  # noqa: F401 — registra modelos en metadata
            from dossier.db.base import Base

            Base.metadata.create_all(bind=engine)
        apply_schema_patches(engine)
    warmup_corporate_dossier_redis()
    logger.info(
        "CORS: allow_origin_regex=%s, origins=%s",
        "on" if _cors_origin_regex else "off",
        _cors_origins,
    )
    stop_automation = start_calendar_automation_thread()
    stop_generation = start_dossier_generation_worker()
    stop_retention = start_dossier_retention_worker()
    try:
        yield
    finally:
        stop_retention()
        stop_generation()
        stop_automation()


app = FastAPI(
    title="Project Dossier API",
    description="Backend para la generación automática de informes de reuniones",
    version="0.2.0",
    lifespan=lifespan,
)

# Orígenes permitidos para el dashboard Next.js (navegador bloquea sin CORS).
def _default_cors_origins_csv() -> str:
    """Puertos 3000–3009 en localhost / 127.0.0.1 / ::1 (Next suele saltar de puerto si 3000 está ocupado)."""
    parts: list[str] = []
    for port in range(3000, 3010):
        parts.extend(
            [
                f"http://localhost:{port}",
                f"http://127.0.0.1:{port}",
                f"http://[::1]:{port}",
            ]
        )
    return ",".join(parts)


_cors_raw = os.getenv("CORS_ORIGINS", _default_cors_origins_csv())
_cors_origins = _parse_cors_origins(_cors_raw)
# Cada preview en Vercel tiene un subdominio distinto (hash, rama, equipo).
# fullmatch() sobre el header Origin (sin path). Desactivar: CORS_ALLOW_VERCEL_APP_REGEX=0
_cors_vercel_re = os.getenv("CORS_ALLOW_VERCEL_APP_REGEX", "1").strip().lower()
_cors_origin_regex: str | None = None
if _cors_vercel_re not in ("0", "false", "no"):
    _custom = (os.getenv("CORS_VERCEL_ORIGIN_REGEX") or "").strip()
    if _custom:
        try:
            re.compile(_custom)
        except re.error:
            logger.warning("CORS_VERCEL_ORIGIN_REGEX inválida; se usa el patrón por defecto.")
        else:
            _cors_origin_regex = _custom
    if _cors_origin_regex is None:
        # Amplio pero solo host *.vercel.app (Origin nunca incluye path).
        _cors_origin_regex = r"https://.+\.vercel\.app"
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(dossiers_router)
app.include_router(dossier_jobs_router)
app.include_router(dossier_stream_router)
app.include_router(integrations_router)

CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")
REDIRECT_URI = (
    (os.getenv("MICROSOFT_REDIRECT_URI") or os.getenv("MICROSOFT_REDIRECT_URL") or "").strip() or None
)

GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip() or None
GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip() or None
# Acepta GOOGLE_REDIRECT_URL por si el .env usa el nombre antiguo (typo).
GOOGLE_REDIRECT_URI = (
    (os.getenv("GOOGLE_REDIRECT_URI") or os.getenv("GOOGLE_REDIRECT_URL") or "").strip() or None
)
GOOGLE_OAUTH_SCOPES = (
    "openid https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/calendar.readonly"
)

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
# User.Read: perfil /me en Graph (nombre, correo). Calendars.Read: eventos.
SCOPES = ["Calendars.Read", "User.Read"]


def get_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
    )


def _status(name: str) -> str:
    return "Configurada ✅" if os.getenv(name) else "Faltante ❌"


_CALENDAR_GET_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Token de calendario inválido o error al consultar el proveedor."},
    404: {"description": "Evento o reunión no encontrada."},
    422: {"description": "Parámetros de consulta inválidos."},
    502: {"description": "Modo intervalo: el proveedor no entregó ninguna página válida."},
    504: {"description": "Modo intervalo: el proveedor no respondió a tiempo."},
}

_OAUTH_CALLBACK_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Error OAuth o falta el código de autorización."},
    422: {"description": "Parámetros de consulta inválidos."},
}


def _sanitize_legacy_access_token(access_token: str | None) -> str | None:
    """OAuth tokens son ASCII; rechaza basura de fuzzing antes de llamar a Graph/Google."""
    if access_token is None:
        return None
    token = access_token.strip()
    if not token:
        return None
    if len(token) > 8192:
        raise HTTPException(status_code=422, detail="access_token demasiado largo.")
    try:
        token.encode("ascii")
    except UnicodeEncodeError as e:
        raise HTTPException(
            status_code=422,
            detail="access_token contiene caracteres no válidos.",
        ) from e
    return token


def _graph_token_for_calendar_route(
    db: Session,
    authorization: str | None,
    access_token: str | None,
) -> str:
    """
    Token de Microsoft Graph para rutas de calendario.

    - Si viene ``?access_token=`` (Graph), se usa tal cual (pruebas / legado).
    - Si no: ``Authorization: Bearer`` debe ser el **JWT de la app**; se lee o renueva
      el token desde ``calendar_integrations``.
    """
    if access_token:
        leg = _sanitize_legacy_access_token(access_token)
        if not leg:
            raise HTTPException(status_code=422, detail="access_token vacío.")
        return leg
    _, user = auth_payload_and_user(db, authorization)
    return get_microsoft_graph_access_token_for_user(db, user.id)


def _google_authorize_url(state: str) -> str:
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Faltan GOOGLE_CLIENT_ID o GOOGLE_REDIRECT_URI.",
        )
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def _google_exchange_authorization_code(code: str) -> dict:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Faltan GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET o GOOGLE_REDIRECT_URI.",
        )
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    try:
        body = r.json()
    except Exception:  # noqa: BLE001 - parseo tolerante de respuesta OAuth
        body = {}
    if r.status_code != 200 or "access_token" not in body:
        msg = body.get("error_description") or body.get("error") or r.text[:400]
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo intercambiar el código OAuth de Google: {msg}",
        )
    return body


def _google_userinfo(access_token: str) -> dict:
    r = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if not r.ok:
        return {}
    try:
        out = r.json()
        return out if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001 - parseo tolerante de respuesta OAuth
        return {}


def _google_token_for_calendar_route(
    db: Session,
    authorization: str | None,
    access_token: str | None,
) -> str:
    if access_token:
        leg = _sanitize_legacy_access_token(access_token)
        if not leg:
            raise HTTPException(status_code=422, detail="access_token vacío.")
        return leg
    _, user = auth_payload_and_user(db, authorization)
    return get_google_calendar_access_token_for_user(db, user.id)


def _filter_reuniones_for_app_user(
    db: Session,
    authorization: str | None,
    access_token: str | None,
    provider: str,
    reuniones: list,
    *,
    work_meetings_only: bool = False,
    skip_internal_meetings: bool | None = None,
) -> list:
    """Aplica filtros de reunión de trabajo / externos cuando la ruta usa JWT de la app."""
    if access_token:
        return reuniones
    from dossier.db.models import CalendarIntegration
    from dossier.services.calendar_event_filters import filter_calendar_reuniones

    _, user = auth_payload_and_user(db, authorization)
    integration = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user.id,
            CalendarIntegration.provider == provider,
            CalendarIntegration.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    return filter_calendar_reuniones(
        reuniones,
        integration=integration,
        user=user,
        work_meetings_only=work_meetings_only,
        skip_internal_meetings=skip_internal_meetings,
    )


def _oauth_frontend_base(*, for_calendar_callback: bool = False) -> str:
    """URL del front (sin barra final) para redirigir tras OAuth con ``state``."""
    base = (
        os.getenv("FRONTEND_URL", "").strip().rstrip("/")
        or os.getenv("MICROSOFT_OAUTH_SUCCESS_URL", "").strip().rstrip("/")
    )
    if not base or not for_calendar_callback:
        return base
    # El banner ``calendar_*=ok|error`` vive en el dashboard del SPA.
    if not base.endswith("/dashboard"):
        base = f"{base}/dashboard"
    return base


def _redirect_calendar_oauth(**params: str) -> RedirectResponse | None:
    base = _oauth_frontend_base(for_calendar_callback=True)
    if not base:
        return None
    return RedirectResponse(f"{base}?{urlencode(params)}", status_code=302)


@app.get("/")
def read_root():
    return {
        "message": "Bienvenido a la API de Project Dossier",
        "status": "Online",
        "project_root": str(PROJECT_ROOT),
        "config_check": {
            "companies_house": _status("COMPANIES_HOUSE_API_KEY"),
            "gemini": _status("DEEPSEEK_API_KEY"),
            "deepseek": _status("DEEPSEEK_API_KEY"),
            "pdl": "configurada ✅"
            if (os.getenv("PDL_API_KEY") or os.getenv("PEOPLE_DATA_LABS_API_KEY") or "").strip()
            else "no configurada ❌",
            "person_research_provider": (os.getenv("PERSON_RESEARCH_PROVIDER") or "pdl").strip().lower(),
            "openai": _status("OPENAI_API_KEY"),
            "google_oauth": _status("GOOGLE_CLIENT_ID"),
            "microsoft": _status("MICROSOFT_CLIENT_ID"),
            "app_auth_jwt": _status("JWT_SECRET"),
            "postgresql": "configurada ✅"
            if is_database_configured()
            else "no configurada (opcional)",
        },
    }


@app.get("/integrations/microsoft/start", tags=["Integraciones"])
def integrations_microsoft_start(
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    as_json: bool = Query(
        False,
        description="Si true, devuelve JSON con authorize_url (recomendado para SPA: fetch + Bearer).",
    ),
):
    """
    Inicia OAuth Microsoft ligado al usuario de la app (JWT).

    - **Navegador sin cabecera:** no sirve abrir esta URL a mano; devuelve 401.
    - **SPA:** ``fetch(..., { headers: { Authorization: Bearer }, redirect: 'manual' })``
      con ``as_json=true`` y luego ``window.location = data.authorize_url``.
    - **Redirect directo:** ``as_json=false`` (por defecto) responde 302 a Microsoft
      (útil con ``curl -L -H 'Authorization: Bearer …'``).
    """
    if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Faltan MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET o MICROSOFT_REDIRECT_URI.",
        )

    user, org = user_org
    state = create_microsoft_oauth_state(
        user_id=str(user.id),
        organization_id=str(org.id),
    )
    msal_app = get_msal_app()
    auth_url = msal_app.get_authorization_request_url(
        SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state,
    )
    if as_json:
        return JSONResponse({"authorize_url": auth_url, "redirect_uri": REDIRECT_URI})
    return RedirectResponse(auth_url)


@app.get("/integrations/microsoft/oauth-config", tags=["Integraciones"])
def integrations_microsoft_oauth_config():
    """
    URI de callback que la API envía a Microsoft (sin secretos).
    Debe estar **idéntica** en Azure → App registration → Redirect URIs.
    """
    return {
        "redirect_uri": REDIRECT_URI,
        "client_id_configured": bool(CLIENT_ID),
        "client_id_suffix": (CLIENT_ID or "")[-20:] if CLIENT_ID else None,
        "tenant_id": TENANT_ID,
        "hint": (
            "Si ves redirect_uri_mismatch, copia redirect_uri tal cual en Azure "
            "(localhost y 127.0.0.1 son distintos)."
        ),
    }


@app.get("/integrations/google/start", tags=["Integraciones"])
def integrations_google_start(
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    as_json: bool = Query(
        False,
        description="Si true, devuelve JSON con authorize_url (recomendado para SPA: fetch + Bearer).",
    ),
):
    """
    Inicia OAuth Google Calendar ligado al usuario de la app (JWT).

    Igual patrón que ``/integrations/microsoft/start``: usar ``as_json=true`` desde el SPA.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Faltan GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET o GOOGLE_REDIRECT_URI.",
        )

    user, org = user_org
    state = create_google_oauth_state(
        user_id=str(user.id),
        organization_id=str(org.id),
    )
    auth_url = _google_authorize_url(state)
    if as_json:
        return JSONResponse(
            {
                "authorize_url": auth_url,
                "redirect_uri": GOOGLE_REDIRECT_URI,
            }
        )
    return RedirectResponse(auth_url)


@app.get("/integrations/google/oauth-config", tags=["Integraciones"])
def integrations_google_oauth_config():
    """
    URI de callback que la API envía a Google (sin secretos).
    Debe estar **idéntica** en Google Cloud → Credentials → Authorized redirect URIs.
    """
    return {
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "client_id_configured": bool(GOOGLE_CLIENT_ID),
        "client_id_suffix": (GOOGLE_CLIENT_ID or "")[-20:] if GOOGLE_CLIENT_ID else None,
        "hint": (
            "Si ves redirect_uri_mismatch, copia redirect_uri tal cual en la consola de Google "
            "(localhost y 127.0.0.1 son distintos)."
        ),
    }


@app.get("/login-microsoft", tags=["Autenticación Microsoft"])
def login_microsoft():
    """Redirige a Microsoft **sin** vincular usuario de la app (solo pruebas / legado)."""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Faltan las credenciales de Microsoft en el archivo .env",
        )

    msal_app = get_msal_app()
    auth_url = msal_app.get_authorization_request_url(SCOPES, redirect_uri=REDIRECT_URI)
    return RedirectResponse(auth_url)


@app.get("/callback", tags=["Autenticación Microsoft"], responses=_OAUTH_CALLBACK_RESPONSES)
@app.get("/callback-microsoft", tags=["Autenticación Microsoft"], responses=_OAUTH_CALLBACK_RESPONSES)
def callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db_if_configured),
):
    """
    Intercambia ``code`` por tokens. Si venía ``state`` de ``/integrations/microsoft/start``,
    guarda tokens en ``calendar_integrations`` y redirige al front (``FRONTEND_URL``).
    Sin ``state``, mantiene respuesta JSON (pruebas / legado).
    """
    if error:
        redir = _redirect_calendar_oauth(calendar_microsoft="error", reason=error[:180])
        if redir and state:
            return redir
        raise HTTPException(status_code=400, detail=f"Error de Microsoft: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No se recibió el código de autorización.")

    msal_app = get_msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    if "access_token" not in result:
        msg = result.get("error_description") or result.get("error") or "token desconocido"
        redir = _redirect_calendar_oauth(calendar_microsoft="error", reason=str(msg)[:180])
        if redir and state:
            return redir
        raise HTTPException(status_code=400, detail=f"No se pudo obtener el token: {msg}")

    access_token = result["access_token"]
    claims = result.get("id_token_claims") or {}
    refresh_token = result.get("refresh_token")
    expires_in = int(result.get("expires_in") or 3600)
    granted = " ".join(SCOPES)

    if state:
        if not _oauth_frontend_base():
            raise HTTPException(
                status_code=500,
                detail=(
                    "Define FRONTEND_URL o MICROSOFT_OAUTH_SUCCESS_URL para redirigir tras OAuth "
                    "cuando se usa state (flujo integrado)."
                ),
            )
        try:
            payload = decode_microsoft_oauth_state(state)
            user_id = UUID(str(payload["sub"]))
            org_id = UUID(str(payload["org_id"]))
        except (PyJWTError, KeyError, ValueError) as e:
            redir = _redirect_calendar_oauth(
                calendar_microsoft="error",
                reason=f"state_invalid:{type(e).__name__}",
            )
            if redir:
                return redir
            raise HTTPException(status_code=400, detail="state inválido o expirado.") from e

        try:
            upsert_microsoft_calendar_tokens(
                db,
                user_id=user_id,
                organization_id=org_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in_seconds=expires_in,
                granted_scopes=granted,
                id_token_claims=claims,
            )
        except SQLAlchemyError as e:
            logger.exception("No se pudo guardar calendar_integrations")
            redir = _redirect_calendar_oauth(
                calendar_microsoft="error",
                reason="db_error",
            )
            if redir:
                return redir
            raise HTTPException(status_code=500, detail="Error al guardar la integración.") from e

        redir_ok = _redirect_calendar_oauth(calendar_microsoft="ok")
        if redir_ok:
            return redir_ok
        raise HTTPException(status_code=500, detail="FRONTEND_URL no configurada.")

    return {
        "mensaje": "Autenticación exitosa con Microsoft",
        "usuario": claims.get("name"),
        "correo": claims.get("preferred_username"),
        "access_token": access_token,
    }


@app.get("/callback-google", tags=["Integraciones"], responses=_OAUTH_CALLBACK_RESPONSES)
def callback_google(
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db_if_configured),
):
    """
    Callback OAuth Google: intercambia ``code`` por tokens y guarda en ``calendar_integrations``.
    Redirige al frontend con ``calendar_google=ok`` o ``calendar_google=error``.
    """
    if error:
        msg = (error_description or error or "unknown")[:180]
        redir = _redirect_calendar_oauth(calendar_google="error", reason=msg)
        if redir and state:
            return redir
        raise HTTPException(status_code=400, detail=f"Error de Google: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No se recibió el código de autorización.")

    try:
        tok = _google_exchange_authorization_code(code)
    except HTTPException as e:
        det = e.detail
        rsn = (det[:180] if isinstance(det, str) else "token_exchange")[:180]
        redir = _redirect_calendar_oauth(calendar_google="error", reason=rsn)
        if redir and state:
            return redir
        raise

    access_token = tok["access_token"]
    refresh_token = tok.get("refresh_token")
    expires_in = int(tok.get("expires_in") or 3600)
    granted = str(tok.get("scope") or GOOGLE_OAUTH_SCOPES)

    userinfo = _google_userinfo(access_token)

    if not state:
        return {
            "mensaje": "Autenticación exitosa con Google (sin state; solo pruebas)",
            "userinfo": userinfo,
        }

    if not _oauth_frontend_base():
        raise HTTPException(
            status_code=500,
            detail="Define FRONTEND_URL o MICROSOFT_OAUTH_SUCCESS_URL para redirigir tras OAuth.",
        )

    try:
        payload = decode_google_oauth_state(state)
        user_id = UUID(str(payload["sub"]))
        org_id = UUID(str(payload["org_id"]))
    except (PyJWTError, KeyError, ValueError) as e:
        redir = _redirect_calendar_oauth(
            calendar_google="error",
            reason=f"state_invalid:{type(e).__name__}",
        )
        if redir:
            return redir
        raise HTTPException(status_code=400, detail="state inválido o expirado.") from e

    try:
        upsert_google_calendar_tokens(
            db,
            user_id=user_id,
            organization_id=org_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in_seconds=expires_in,
            granted_scopes=granted,
            userinfo=userinfo,
        )
    except SQLAlchemyError as e:
        logger.exception("No se pudo guardar calendar_integrations Google")
        redir = _redirect_calendar_oauth(calendar_google="error", reason="db_error")
        if redir:
            return redir
        raise HTTPException(status_code=500, detail="Error al guardar la integración.") from e

    redir_ok = _redirect_calendar_oauth(calendar_google="ok")
    if redir_ok:
        return redir_ok
    raise HTTPException(status_code=500, detail="FRONTEND_URL no configurada.")


_PARAMS_LEGADOS_DE_LISTADO = ("top", "dias", "incluir_pasadas")

_MENSAJES_CARGA_INCOMPLETA = {
    "limite_paginas": "Hay más reuniones de las que se pueden cargar de una vez. Reduce el intervalo.",
    "tiempo_agotado": "El proveedor tardó demasiado y la carga quedó incompleta. Reintenta o reduce el intervalo.",
    "error_proveedor": "El proveedor falló a mitad de la carga y la lista está incompleta. Reintenta.",
}


def _rango_de_la_consulta(
    request: Request,
    desde: str | None,
    hasta: str | None,
) -> RangoConsulta | None:
    """``None`` = modo legado. Con intervalo no se aceptan ``top``/``dias``/``incluir_pasadas``."""
    if desde is None and hasta is None:
        return None
    mezclados = [p for p in _PARAMS_LEGADOS_DE_LISTADO if p in request.query_params]
    if mezclados:
        raise HTTPException(
            status_code=422,
            detail=(
                "No combines «desde»/«hasta» con "
                + ", ".join(f"«{p}»" for p in mezclados)
                + ": el intervalo ya define qué reuniones se devuelven."
            ),
        )
    try:
        return parse_rango(desde, hasta)
    except RangoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _respuesta_por_intervalo(rango: RangoConsulta, resultado: ResultadoRango, reuniones: list) -> dict:
    """Misma forma que el modo legado más ``rango``, ``completo`` y ``motivo_incompleto``."""
    if not resultado.completo:
        mensaje = _MENSAJES_CARGA_INCOMPLETA.get(resultado.motivo_incompleto or "")
    elif not reuniones:
        mensaje = "No hay reuniones en el intervalo consultado."
    else:
        mensaje = None
    return {
        "total": len(reuniones),
        "reuniones": reuniones,
        "mensaje": mensaje,
        "rango": rango.como_dict(),
        "completo": resultado.completo,
        "motivo_incompleto": resultado.motivo_incompleto,
    }


@app.get("/calendario/eventos", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
@app.get("/calendario/eventos-outlook", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
def api_listar_eventos_calendario(
    request: Request,
    desde: str | None = Query(
        None,
        description="RFC3339 con offset, inicio inclusivo. Va junto con «hasta»; máximo 62 días.",
    ),
    hasta: str | None = Query(None, description="RFC3339 con offset, final exclusivo."),
    top: int = Query(10, ge=1, le=50, description="Cantidad máxima de reuniones"),
    dias: int = Query(90, ge=1, le=365, description="Días hacia adelante a buscar"),
    incluir_pasadas: bool = Query(
        False,
        description="Si true, muestra también eventos pasados (útil para probar)",
    ),
    access_token: str | None = Query(
        None,
        description="Opcional: token de Graph (legado). Si se omite, Authorization es el JWT de la app.",
    ),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    """Lista reuniones de Outlook: JWT de la app + tokens en BD, o ``?access_token=`` para pruebas.

    Con ``desde``/``hasta`` devuelve las reuniones que se solapan con ese intervalo
    (recorriendo la paginación de Graph); sin ellos conserva el comportamiento legado.
    """
    rango = _rango_de_la_consulta(request, desde, hasta)
    token = _graph_token_for_calendar_route(db, authorization, access_token)
    if rango is not None:
        try:
            resultado = listar_reuniones_rango(token, rango)
        except ErrorProveedorCalendario as e:
            raise HTTPException(status_code=e.status_code, detail=e.detalle) from e
        reuniones = _filter_reuniones_for_app_user(
            db, authorization, access_token, "microsoft", resultado.reuniones,
            skip_internal_meetings=False,
        )
        return _respuesta_por_intervalo(rango, resultado, reuniones)
    try:
        reuniones = listar_reuniones(
            token,
            top=top,
            dias_adelante=dias,
            incluir_pasadas=incluir_pasadas,
        )
        reuniones = _filter_reuniones_for_app_user(
            db,
            authorization,
            access_token,
            "microsoft",
            reuniones,
            skip_internal_meetings=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except UnicodeError as e:
        raise HTTPException(status_code=422, detail="Parámetros con caracteres no válidos.") from e

    mensaje = None
    if not reuniones:
        mensaje = (
            "No hay reuniones próximas en tu calendario. "
            "Crea un evento en Outlook con «Empresa:» y «Contacto:» en la descripción."
        )

    return {"total": len(reuniones), "reuniones": reuniones, "mensaje": mensaje}


@app.get("/calendario/eventos-google", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
def api_listar_eventos_google_calendar(
    request: Request,
    desde: str | None = Query(
        None,
        description="RFC3339 con offset, inicio inclusivo. Va junto con «hasta»; máximo 62 días.",
    ),
    hasta: str | None = Query(None, description="RFC3339 con offset, final exclusivo."),
    top: int = Query(10, ge=1, le=50, description="Cantidad máxima de eventos"),
    dias: int = Query(90, ge=1, le=365, description="Días hacia adelante a buscar"),
    incluir_pasadas: bool = Query(
        False,
        description="Si true, incluye ventana de eventos pasados recientes (útil para probar)",
    ),
    access_token: str | None = Query(
        None,
        description="Opcional: access token de Google Calendar (legado). Si se omite, Authorization es el JWT de la app.",
    ),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    """Lista eventos del calendario principal de Google: JWT de la app + tokens en BD.

    Con ``desde``/``hasta`` devuelve los eventos que se solapan con ese intervalo
    (recorriendo ``nextPageToken``); sin ellos conserva el comportamiento legado.
    """
    rango = _rango_de_la_consulta(request, desde, hasta)
    token = _google_token_for_calendar_route(db, authorization, access_token)
    if rango is not None:
        try:
            resultado = listar_reuniones_google_rango(token, rango)
        except ErrorProveedorCalendario as e:
            raise HTTPException(status_code=e.status_code, detail=e.detalle) from e
        reuniones = _filter_reuniones_for_app_user(
            db, authorization, access_token, "google", resultado.reuniones,
            skip_internal_meetings=False,
        )
        return _respuesta_por_intervalo(rango, resultado, reuniones)
    try:
        reuniones = listar_reuniones_google(
            token,
            top=top,
            dias_adelante=dias,
            incluir_pasadas=incluir_pasadas,
        )
        reuniones = _filter_reuniones_for_app_user(
            db,
            authorization,
            access_token,
            "google",
            reuniones,
            skip_internal_meetings=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except UnicodeError as e:
        raise HTTPException(status_code=422, detail="Parámetros con caracteres no válidos.") from e

    mensaje = None
    if not reuniones:
        mensaje = (
            "No hay eventos próximos en tu calendario. "
            "Crea un evento en Google Calendar con «Empresa:» y «Contacto:» en la descripción."
        )

    return {"total": len(reuniones), "reuniones": reuniones, "mensaje": mensaje}


@app.get("/calendario/diagnostico-microsoft", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
@app.get("/calendario/diagnostico-outlook", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
def api_diagnostico_microsoft_calendario(
    access_token: str | None = Query(
        None,
        description="Opcional: token de Graph (legado). Si se omite, Authorization es el JWT de la app.",
    ),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    """
    Quién es ``/me`` en Graph, cuántos calendarios hay y si existen eventos
    en el calendario predeterminado (si /calendario/eventos viene vacío).
    """
    token = _graph_token_for_calendar_route(db, authorization, access_token)
    try:
        return diagnostico_microsoft_calendar(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except UnicodeError as e:
        raise HTTPException(status_code=422, detail="Parámetros con caracteres no válidos.") from e


@app.get("/calendario/diagnostico-google", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
def api_diagnostico_google_calendario(
    access_token: str | None = Query(
        None,
        description="Opcional: access token de Google (legado). Si se omite, Authorization es el JWT de la app.",
    ),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    """
    Calendario principal de Google y eventos recientes
    (si /calendario/eventos-google viene vacío).
    """
    token = _google_token_for_calendar_route(db, authorization, access_token)
    try:
        return diagnostico_google_calendar(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except UnicodeError as e:
        raise HTTPException(status_code=422, detail="Parámetros con caracteres no válidos.") from e


def _calendar_output_language(user: User, explicit: str | None) -> str:
    return effective_output_language(user, explicit)


def _reunion_snapshot_with_output_language(
    reunion: dict,
    *,
    user: User,
    output_language: str | None,
) -> dict:
    snap = dict(reunion)
    snap["_output_language"] = _calendar_output_language(user, output_language)
    return snap


def _run_calendar_dossier_batch(
    db: Session,
    *,
    user: User,
    org: Organization,
    reuniones: list,
    calendar_provider: str,
    org_ctx: str,
    output_language: str | None = None,
    depth: DossierDepth | None = None,
) -> list:
    dossiers = []
    out_lang = _calendar_output_language(user, output_language)
    depth_key = depth or default_depth_for_plan(org.plan)
    assert_depth_allowed(org, depth_key)
    for reunion in reuniones:
        t0 = time.perf_counter()
        item = generate_dossiers_from_calendar_event(
            reunion,
            organization_context_block=org_ctx,
            organization_id=org.id,
            organization_plan=org.plan,
            depth=depth_key,
            output_language=out_lang,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        item = persist_calendar_dossiers(
            db,
            user_id=user.id,
            org_id=org.id,
            result=item,
            calendar_provider=calendar_provider,
            generation_duration_ms=elapsed_ms,
            depth=depth_key,
            generation_origin="manual",
        )
        dossiers.append(item)
    return dossiers


def _normalize_calendar_depth(org: Organization, raw: str | None) -> DossierDepth:
    return normalize_depth_for_plan(org.plan, raw)


def _assert_calendar_batch_credits(
    org: Organization,
    reuniones: list,
    depth: DossierDepth,
) -> None:
    charge = credit_charging_enabled()
    total = sum(estimate_reunion_credits(r, depth=depth, plan=org.plan) for r in reuniones)
    assert_sufficient_credits(org, total, charge=charge)


def _enqueue_calendar_dossier_jobs(
    db: Session,
    *,
    user: User,
    org: Organization,
    reuniones: list,
    calendar_provider: str,
    depth: DossierDepth,
    output_language: str | None = None,
) -> dict:
    jobs = []
    for reunion in reuniones:
        snap = _reunion_snapshot_with_output_language(
            reunion,
            user=user,
            output_language=output_language,
        )
        job = enqueue_calendar_dossier_job(
            db,
            user=user,
            org=org,
            reunion=snap,
            calendar_provider=calendar_provider,
            depth=depth,
        )
        jobs.append(job)
    first = jobs[0]
    return {
        "async": True,
        "job_id": str(first.id),
        "status": first.status,
        "meeting_label": first.meeting_label,
        "credits_estimated": first.credits_estimated,
        "jobs": [
            {
                "job_id": str(j.id),
                "status": j.status,
                "meeting_label": j.meeting_label,
                "credits_estimated": j.credits_estimated,
                "external_event_id": j.external_event_id,
            }
            for j in jobs
        ],
        "mensaje": "Generación en curso. Puedes navegar; te avisaremos cuando esté listo.",
    }


def _resolve_outlook_reuniones(
    token: str,
    *,
    event_id: str | None,
    reunion_payload: dict | None,
    top: int,
) -> list:
    from dossier.services.graph_calendar import merge_reunion_payload

    from_client = coerce_reunion_payload(reunion_payload)
    if event_id:
        fresh = obtener_reunion_por_id(token, event_id)
        if fresh:
            merged = merge_reunion_payload(from_client, fresh)
            if merged:
                return [merged]
        if from_client:
            return [from_client]
        raise HTTPException(
            status_code=404,
            detail="No se encontró la reunión con ese event_id en el calendario.",
        )
    if from_client:
        return [from_client]
    reuniones = listar_reuniones(token, top=top, dias_adelante=90)
    return reuniones


def _resolve_google_reuniones(
    token: str,
    *,
    event_id: str | None,
    reunion_payload: dict | None,
    top: int,
) -> list:
    from dossier.services.graph_calendar import merge_reunion_payload

    from_client = coerce_reunion_payload(reunion_payload)
    if event_id:
        fresh = obtener_reunion_google_por_id(token, event_id)
        if fresh:
            merged = merge_reunion_payload(from_client, fresh)
            if merged:
                return [merged]
        if from_client:
            return [from_client]
        raise HTTPException(
            status_code=404,
            detail="No se encontró el evento con ese id en Google Calendar.",
        )
    if from_client:
        return [from_client]
    return listar_reuniones_google(token, top=top, dias_adelante=90)


@app.get("/calendario/generar-dossiers", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
@app.get("/calendario/generar-dossiers-outlook", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
def api_generar_dossiers_desde_calendario(
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    top: int = Query(5, ge=1, le=10, description="Máximo de reuniones a procesar con IA"),
    event_id: str | None = Query(
        None, description="Si se indica, solo genera dossier para esa reunión"
    ),
    access_token: str | None = Query(
        None,
        description="Opcional: token de Graph (legado). Si se omite, Authorization es el JWT de la app.",
    ),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    """Empresa (asunto) → Companies House / SEC; persona (descripción) → PDL + DeepSeek."""
    user, org = ctx.user, ctx.org
    org_ctx = format_dossier_context_for_prompt(org)
    token = _graph_token_for_calendar_route(db, authorization, access_token)

    try:
        reuniones = _resolve_outlook_reuniones(
            token, event_id=event_id, reunion_payload=None, top=top
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not reuniones:
        return {
            "mensaje": "No hay reuniones próximas en el calendario.",
            "dossiers": [],
        }

    depth = default_depth_for_plan(org.plan)
    _assert_calendar_batch_credits(org, reuniones, depth)

    dossiers = _run_calendar_dossier_batch(
        db,
        user=user,
        org=org,
        reuniones=reuniones,
        calendar_provider="microsoft",
        org_ctx=org_ctx,
        depth=depth,
    )

    return {
        "total": len(dossiers),
        "dossiers": dossiers,
    }


@app.post("/calendario/generar-dossiers", tags=["Calendario"])
@app.post("/calendario/generar-dossiers-outlook", tags=["Calendario"])
def api_generar_dossiers_desde_calendario_post(
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    body: CalendarGenerarDossiersBody,
    access_token: str | None = Query(
        None,
        description="Opcional: token de Graph (legado).",
    ),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    """
    Igual que GET pero el ``event_id`` va en el cuerpo JSON (ids de Outlook son largos
    y pueden corromperse en query string). Si el cliente envía ``reunion`` del listado,
    no se vuelve a pedir el evento a Graph.
    """
    user, org = ctx.user, ctx.org
    org_ctx = format_dossier_context_for_prompt(org)
    token = _graph_token_for_calendar_route(db, authorization, access_token)
    top = body.top if body.top is not None else 5

    try:
        reuniones = _resolve_outlook_reuniones(
            token,
            event_id=body.event_id,
            reunion_payload=body.reunion,
            top=top,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not reuniones:
        return {
            "mensaje": "No hay reuniones próximas en el calendario.",
            "dossiers": [],
        }

    depth = _normalize_calendar_depth(org, body.depth)
    if body.async_mode:
        _assert_calendar_batch_credits(org, reuniones, depth)
        return _enqueue_calendar_dossier_jobs(
            db,
            user=user,
            org=org,
            reuniones=reuniones,
            calendar_provider="microsoft",
            depth=depth,
            output_language=body.output_language,
        )

    _assert_calendar_batch_credits(org, reuniones, depth)

    dossiers = _run_calendar_dossier_batch(
        db,
        user=user,
        org=org,
        reuniones=reuniones,
        calendar_provider="microsoft",
        org_ctx=org_ctx,
        output_language=body.output_language,
        depth=depth,
    )

    return {
        "total": len(dossiers),
        "dossiers": dossiers,
    }


@app.get("/calendario/generar-dossiers-google", tags=["Calendario"], responses=_CALENDAR_GET_RESPONSES)
def api_generar_dossiers_desde_google_calendar(
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    top: int = Query(5, ge=1, le=10, description="Máximo de eventos a procesar con IA"),
    event_id: str | None = Query(
        None, description="Si se indica, solo genera dossier para ese evento de Google Calendar"
    ),
    access_token: str | None = Query(
        None,
        description="Opcional: access token de Google (legado). Si se omite, Authorization es el JWT de la app.",
    ),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    """Empresa (asunto) → Companies House / SEC; persona (descripción) → PDL + DeepSeek."""
    user, org = ctx.user, ctx.org
    org_ctx = format_dossier_context_for_prompt(org)
    token = _google_token_for_calendar_route(db, authorization, access_token)

    try:
        reuniones = _resolve_google_reuniones(
            token, event_id=event_id, reunion_payload=None, top=top
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not reuniones:
        return {
            "mensaje": "No hay eventos próximos en Google Calendar.",
            "dossiers": [],
        }

    depth = default_depth_for_plan(org.plan)
    _assert_calendar_batch_credits(org, reuniones, depth)

    dossiers = _run_calendar_dossier_batch(
        db,
        user=user,
        org=org,
        reuniones=reuniones,
        calendar_provider="google",
        org_ctx=org_ctx,
        depth=depth,
    )

    return {
        "total": len(dossiers),
        "dossiers": dossiers,
    }


@app.post("/calendario/generar-dossiers-google", tags=["Calendario"])
def api_generar_dossiers_desde_google_calendar_post(
    ctx: Annotated[OrgAuthContext, Depends(require_mutator)],
    body: CalendarGenerarDossiersBody,
    access_token: str | None = Query(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db_if_configured),
):
    user, org = ctx.user, ctx.org
    org_ctx = format_dossier_context_for_prompt(org)
    token = _google_token_for_calendar_route(db, authorization, access_token)
    top = body.top if body.top is not None else 5

    try:
        reuniones = _resolve_google_reuniones(
            token,
            event_id=body.event_id,
            reunion_payload=body.reunion,
            top=top,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not reuniones:
        return {
            "mensaje": "No hay eventos próximos en Google Calendar.",
            "dossiers": [],
        }

    depth = _normalize_calendar_depth(org, body.depth)
    if body.async_mode:
        _assert_calendar_batch_credits(org, reuniones, depth)
        return _enqueue_calendar_dossier_jobs(
            db,
            user=user,
            org=org,
            reuniones=reuniones,
            calendar_provider="google",
            depth=depth,
            output_language=body.output_language,
        )

    _assert_calendar_batch_credits(org, reuniones, depth)

    dossiers = _run_calendar_dossier_batch(
        db,
        user=user,
        org=org,
        reuniones=reuniones,
        calendar_provider="google",
        org_ctx=org_ctx,
        output_language=body.output_language,
        depth=depth,
    )

    return {
        "total": len(dossiers),
        "dossiers": dossiers,
    }


@app.get("/db/health", tags=["Base de datos"])
def db_health():
    """
    Comprueba conexión a PostgreSQL. Las credenciales solo viven en .env local (no en git).
    """
    if not is_database_configured():
        return {
            "postgresql": "not_configured",
            "hint": (
                "Define DATABASE_URL o POSTGRES_HOST/USER/PASSWORD/DB en .env. "
                "Copia .env.example; cada quien usa su base local."
            ),
        }
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        url = engine.url
        # Sin credenciales: ayuda a comprobar que pgAdmin y la API apuntan al mismo servidor/BD.
        connection = {
            "host": url.host or "",
            "port": int(url.port or 5432),
            "database": url.database or "",
        }
        return {
            "postgresql": "ok",
            "mensaje": "Conexión exitosa con la base de datos PostgreSQL.",
            "connection": connection,
        }
    except Exception as e:  # noqa: BLE001 - healthcheck: reporta cualquier fallo de conexion como 503
        return JSONResponse(
            status_code=503,
            content={"postgresql": "error", "detail": str(e)},
        )


@app.get("/calendario/automation/status", tags=["Calendario"])
def calendar_automation_status(
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    db: Session = Depends(get_db_if_configured),
):
    """Estado de la automatización del usuario (integraciones, anticipación, cola)."""
    from dossier.db.models import CalendarEvent, CalendarIntegration
    from dossier.services.calendar_automation import (
        automation_enabled,
        default_advance_minutes,
        poll_interval_seconds,
        user_advance_minutes,
    )

    user, _org = user_org
    integrations = list(
        db.execute(
            select(CalendarIntegration).where(
                CalendarIntegration.user_id == user.id,
                CalendarIntegration.revoked_at.is_(None),
            )
        ).scalars().all()
    )

    effective = user_advance_minutes(integrations)
    stored_advances = [
        i.advance_minutes for i in integrations if i.advance_minutes in {15, 20, 30, 60, 1440}
    ]
    stored = stored_advances[0] if stored_advances else effective
    skip_internal_values = [bool(i.skip_internal_meetings) for i in integrations]
    skip_internal = skip_internal_values[0] if skip_internal_values else False

    pending = db.execute(
        select(CalendarEvent).where(
            CalendarEvent.user_id == user.id,
            CalendarEvent.processing_status == "scheduled",
        )
    ).scalars().all()
    due_times = [e.dossier_scheduled_at for e in pending if e.dossier_scheduled_at]

    return {
        "enabled": automation_enabled(),
        "poll_seconds": poll_interval_seconds(),
        "advance_minutes": effective,
        "advance_minutes_stored": stored,
        "advance_minutes_from_env": False,
        "server_default_minutes": default_advance_minutes(),
        "work_meetings_only": True,
        "skip_internal_meetings": skip_internal,
        "scheduled_events": len(pending),
        "next_due": min(due_times).isoformat() if due_times else None,
        "has_calendars": len(integrations) > 0,
        "integrations": [
            {
                "provider": row.provider,
                "email": row.provider_email,
                "is_enabled": row.is_enabled,
                "advance_minutes": row.advance_minutes,
                "skip_internal_meetings": row.skip_internal_meetings,
            }
            for row in integrations
        ],
    }


_ALLOWED_ADVANCE_MINUTES = {15, 20, 30, 60, 1440}


@app.patch("/calendario/automation/settings", tags=["Calendario"])
def update_calendar_automation_settings(
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    db: Session = Depends(get_db_if_configured),
    body: dict = Body(...),
):
    """Preferencias de automatización: anticipación y filtro de reuniones externas."""
    advance_minutes = body.get("advance_minutes")
    skip_internal_meetings = body.get("skip_internal_meetings")

    if advance_minutes is None and skip_internal_meetings is None:
        raise HTTPException(
            status_code=400,
            detail="Indica advance_minutes y/o skip_internal_meetings.",
        )

    if advance_minutes is not None and advance_minutes not in _ALLOWED_ADVANCE_MINUTES:
        raise HTTPException(
            status_code=400,
            detail="advance_minutes debe ser 15, 20, 30, 60 o 1440.",
        )

    if skip_internal_meetings is not None and not isinstance(skip_internal_meetings, bool):
        raise HTTPException(
            status_code=400,
            detail="skip_internal_meetings debe ser true o false.",
        )

    user, org = user_org
    assert_automation_allowed(org)
    from dossier.db.models import CalendarIntegration
    from dossier.services.calendar_automation import reschedule_user_calendar_events

    rows = db.execute(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user.id,
            CalendarIntegration.revoked_at.is_(None),
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No hay calendarios conectados. Conecta Google u Outlook primero.",
        )

    rescheduled = 0
    for row in rows:
        if advance_minutes is not None:
            row.advance_minutes = advance_minutes
        if skip_internal_meetings is not None:
            row.skip_internal_meetings = skip_internal_meetings
    db.commit()

    if advance_minutes is not None:
        rescheduled = reschedule_user_calendar_events(db, user.id, advance_minutes)

    if skip_internal_meetings is not None:
        for integration in rows:
            if integration.is_enabled:
                from dossier.services.calendar_automation import sync_calendar_events_for_integration

                sync_calendar_events_for_integration(db, integration)

    messages: list[str] = []
    if advance_minutes is not None:
        if rescheduled:
            messages.append(
                f"Anticipación actualizada a {advance_minutes} min ({rescheduled} reunión(es) reprogramada(s))."
            )
        else:
            messages.append(f"Anticipación actualizada a {advance_minutes} min.")
    if skip_internal_meetings is not None:
        label = "activado" if skip_internal_meetings else "desactivado"
        messages.append(f"Filtro de reuniones externas {label}.")

    effective_advance = advance_minutes if advance_minutes is not None else rows[0].advance_minutes

    return {
        "advance_minutes_stored": effective_advance,
        "advance_minutes_effective": effective_advance,
        "advance_minutes_from_env": False,
        "skip_internal_meetings": rows[0].skip_internal_meetings,
        "events_rescheduled": rescheduled,
        "message": " ".join(messages) if messages else "Preferencias actualizadas.",
    }


@app.post("/integrations/{provider}/disconnect", tags=["Integraciones"])
def disconnect_calendar_integration(
    provider: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db_if_configured),
):
    """Desconecta un calendario (Google u Outlook): marca ``revoked_at`` y borra tokens."""
    from dossier.services.calendar_integrations import revoke_calendar_integration_for_user

    try:
        row = revoke_calendar_integration_for_user(db, user_id=user.id, provider=provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {
        "provider": row.provider,
        "disconnected": True,
        "message": "Calendario desconectado.",
    }


@app.get("/health")
def health_check():
    """Incluye resumen CORS para comprobar en producción qué cargó el proceso (sin secretos)."""
    return {
        "status": "ok",
        "version": "0.2.0",
        "cors": {
            "vercel_origin_regex": bool(_cors_origin_regex),
            "allowed_origins": _cors_origins,
        },
        "dossier_redis": dossier_corporate_redis_health(),
    }


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """
    Errores de BD (p. ej. columna inexistente si no corriste la migración) devuelven JSON
    en lugar de ``text/plain`` de uvicorn, y el CORS del middleware aplica al JSON.
    """
    logger.exception("Error SQLAlchemy: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "Error al consultar la base de datos. Suele deberse a que el esquema PostgreSQL "
                "no coincide con el código (falta ejecutar Migracion.md y "
                "docs/sql/patch_after_migracion_v1.sql en Neon)."
            ),
            "error_type": type(exc).__name__,
        },
    )
