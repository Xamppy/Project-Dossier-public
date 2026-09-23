"""
Rutas HTTP de registro e inicio de sesión alineadas con el schema PostgreSQL migrado.

Tablas: `organizations`, `users`, `org_memberships` (ver `docs/sql/schema_project_dossier.sql`).

Registro:
1. Crea una organización (tenant) con el nombre de empresa y un `slug` único.
2. Crea el usuario con hash de contraseña.
3. Crea membresía `admin` + `is_primary_org=True`.

El JWT incluye `org_id` para multi-tenant en rutas como `GET /dossiers`.
"""
from __future__ import annotations

import os
import re
import secrets
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from jwt.exceptions import PyJWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dossier.api_errors import INVITES_WORKSPACE_ONLY, OrgApiError, org_api_http_detail
from dossier.billing.plan_catalog import apply_plan_to_organization
from dossier.db import is_database_configured
from dossier.db.models import Organization, OrgMembership, User
from dossier.db.session import get_db
from dossier.org_dossier_context import apply_dossier_context_patch, read_dossier_context
from dossier.org_email_domain import ensure_org_email_domain
from dossier.org_workspace import ORG_NAME_PERSONAL_PLACEHOLDER, read_workspace_kind
from dossier.schemas.auth import (
    ChangeEmailRequest,
    ChangePasswordRequest,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    OrganizationDossierContextPatch,
    OrganizationPlanPatch,
    RegisterRequest,
    TokenResponse,
    UserPreferencesPatch,
    UserPublic,
)
from dossier.schemas.dossier_share import (
    OrgMemberItem,
    OrgMemberManageItem,
    OrgMemberRolePatch,
    OrgMembersManageResponse,
    OrgMembersResponse,
)
from dossier.schemas.org_invite import (
    OrgInviteAcceptRequest,
    OrgInviteCreate,
    OrgInviteItem,
    OrgInvitePreview,
    OrgInvitesResponse,
    OrgPendingInvitesResponse,
    SessionSwitchRequest,
    UserOrganizationItem,
    UserOrganizationsResponse,
)
from dossier.security import create_access_token, hash_password, verify_password
from dossier.security.jwt_tokens import decode_access_token
from dossier.security.rbac import can_manage_organization, can_mutate_dossiers, normalize_org_role
from dossier.services.account_service import (
    change_user_email,
    change_user_password,
    delete_user_account,
)
from dossier.services.dossier_retention import normalize_dossier_retention_days
from dossier.services.dossier_share_service import list_org_members
from dossier.services.org_invite_service import (
    accept_org_invite,
    accept_org_invite_for_register,
    create_org_invite,
    list_org_invites,
    list_pending_invites_for_email,
    preview_org_invite,
    revoke_org_invite,
)
from dossier.services.org_membership_service import (
    list_org_members_for_management,
    remove_org_member,
    update_org_member_role,
)

router = APIRouter(prefix="/auth", tags=["Autenticación app"])

_ALLOWED_DOSSIER_OUTPUT_PREFS = frozenset(
    {"match", "auto", "es", "en", "pt", "it", "fr", "de"}
)
_ALLOWED_UI_LOCALES = frozenset({"en", "en-gb", "es", "pt", "it", "fr", "de"})


def _normalize_register_locale(raw: str | None) -> str:
    loc = (raw or "es").strip().lower().replace("_", "-")
    if loc not in _ALLOWED_UI_LOCALES:
        return "es"
    return loc


def _signup_org_credits() -> tuple[int, int]:
    """
    Créditos iniciales de la organización al registrarse (`/auth/register`).

    Variables opcionales en `.env`:
    - `ORG_SIGNUP_CREDITS` — saldo inicial (≥ 0). Por defecto **10** (tier Free del informe).
    - `ORG_SIGNUP_CREDITS_MONTHLY_LIMIT` — tope mensual; si no se define, igual al saldo.
    """

    def _parse(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        try:
            v = int(str(raw).strip())
        except ValueError:
            return default
        return max(0, v)

    balance = _parse("ORG_SIGNUP_CREDITS", 10)
    lim_raw = os.getenv("ORG_SIGNUP_CREDITS_MONTHLY_LIMIT")
    if lim_raw is not None and str(lim_raw).strip():
        limit = _parse("ORG_SIGNUP_CREDITS_MONTHLY_LIMIT", balance)
    else:
        limit = balance
    return balance, limit


def get_db_if_configured() -> Generator[Session, None, None]:
    """Igual que `get_db`, pero responde 503 si no hay `DATABASE_URL` / `POSTGRES_*`."""
    if not is_database_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "PostgreSQL no está configurado. Define DATABASE_URL o POSTGRES_* en .env "
                "en backend/."
            ),
        )
    yield from get_db()


def _require_jwt_secret() -> None:
    try:
        from dossier.security.jwt_tokens import assert_jwt_secret_configured

        assert_jwt_secret_configured()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _slug_base_from_company(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")[:80]
    return s or "org"


def allocate_org_slug(db: Session, company_name: str) -> str:
    """Genera un `slug` único para `organizations.slug` (máx. 100 caracteres)."""
    base = _slug_base_from_company(company_name)[:100]
    candidate = base
    for _ in range(64):
        exists = db.execute(
            select(Organization.id).where(Organization.slug == candidate)
        ).first()
        if not exists:
            return candidate
        suffix = secrets.token_hex(3)
        candidate = f"{base[:88]}-{suffix}"[:100]
    return f"org-{secrets.token_hex(8)}"[:100]


def load_primary_membership(
    db: Session, user_id: UUID
) -> tuple[Organization, OrgMembership] | None:
    """Organización primaria del usuario, o la primera membresía por fecha."""
    q = (
        select(Organization, OrgMembership)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user_id, OrgMembership.is_primary_org.is_(True))
        .limit(1)
    )
    row = db.execute(q).first()
    if row:
        return row[0], row[1]
    q2 = (
        select(Organization, OrgMembership)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user_id)
        .order_by(OrgMembership.joined_at)
        .limit(1)
    )
    row2 = db.execute(q2).first()
    if row2:
        return row2[0], row2[1]
    return None


def load_membership_for_org(
    db: Session, user_id: UUID, organization_id: UUID
) -> tuple[Organization, OrgMembership] | None:
    row = db.execute(
        select(Organization, OrgMembership)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.organization_id == organization_id,
        )
    ).first()
    if row:
        return row[0], row[1]
    return None


def load_session_membership(
    db: Session, user_id: UUID
) -> tuple[Organization, OrgMembership] | None:
    """
    Organización activa de la sesión: prioriza cuenta empresa (work) sobre personal.
    Todos los miembros de una org comparten el mismo plan y pool de créditos.
    """
    rows = db.execute(
        select(Organization, OrgMembership)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user_id)
        .order_by(OrgMembership.joined_at.asc())
    ).all()
    if not rows:
        return None

    work_rows = [(o, m) for o, m in rows if read_workspace_kind(o) == "work"]
    if work_rows:
        for org, membership in work_rows:
            if membership.is_primary_org:
                return org, membership
        return work_rows[0]

    for org, membership in rows:
        if membership.is_primary_org:
            return org, membership
    fallback_org, fallback_membership = rows[0]
    return fallback_org, fallback_membership


def build_user_public(
    db: Session, user: User, organization_id: UUID | None = None
) -> UserPublic:
    if organization_id is not None:
        pair = load_membership_for_org(db, user.id, organization_id)
        if pair is None:
            pair = load_session_membership(db, user.id)
    else:
        pair = load_session_membership(db, user.id)
    if not pair:
        raise HTTPException(
            status_code=500,
            detail="Usuario sin membresía de organización.",
        )
    org, m = pair
    org_summary, org_industry = read_dossier_context(org)
    wk = read_workspace_kind(org)
    company_public = "" if wk == "personal" else org.name
    return UserPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name or "",
        company_name=company_public,
        organization_id=org.id,
        role=m.role,
        is_platform_admin=bool(user.is_platform_admin),
        organization_plan=org.plan,
        credits_balance=org.credits_balance,
        credits_monthly_limit=org.credits_monthly_limit,
        workspace_kind=wk,
        organization_company_summary=org_summary,
        organization_industry_or_area=org_industry,
        locale=user.locale or "es",
        timezone=user.timezone or "UTC",
        dossier_output_language=getattr(user, "dossier_output_language", None) or "match",
        dossier_retention_days=getattr(user, "dossier_retention_days", None),
    )


def _org_id_from_authorization(authorization: str | None) -> UUID | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = decode_access_token(authorization[7:].strip())
        raw = payload.get("org_id")
        if raw:
            return UUID(str(raw))
    except (PyJWTError, ValueError):
        return None
    return None


def auth_payload_and_user(db: Session, authorization: str | None) -> tuple[dict, User]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Falta la cabecera Authorization: Bearer <token>.",
        )
    token = authorization[7:].strip()
    try:
        payload = decode_access_token(token)
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado.") from None

    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(status_code=401, detail="Token sin identificador de usuario.")

    try:
        user_uuid = UUID(sub)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Token corrupto.") from e

    user = db.get(User, user_uuid)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo.")
    return payload, user


@dataclass(frozen=True)
class OrgAuthContext:
    """Usuario autenticado con organización activa y rol RBAC."""

    user: User
    org: Organization
    membership: OrgMembership

    @property
    def role(self) -> str:
        return normalize_org_role(self.membership.role)


def _resolve_membership_role(payload: dict, membership: OrgMembership) -> str:
    """Usa ``role`` del JWT si existe; si no, la membresía en BD (tokens antiguos)."""
    claim = payload.get("role")
    if isinstance(claim, str) and claim.strip():
        return normalize_org_role(claim)
    return normalize_org_role(membership.role)


def get_org_auth_context(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db_if_configured),
) -> OrgAuthContext:
    """Dependencia: usuario + org + membresía + rol efectivo."""
    payload, user = auth_payload_and_user(db, authorization)
    org_id_raw = payload.get("org_id")
    if not org_id_raw or not isinstance(org_id_raw, str):
        raise HTTPException(
            status_code=401,
            detail="Token sin organización (sesión antigua). Vuelve a iniciar sesión.",
        )
    try:
        org_uuid = UUID(org_id_raw)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Token corrupto (organización).") from e

    org = db.get(Organization, org_uuid)
    if org is None or not org.is_active:
        raise HTTPException(status_code=401, detail="Organización no encontrada o inactiva.")

    m = db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == org.id,
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=403, detail="No perteneces a esta organización.")

    effective_role = _resolve_membership_role(payload, m)
    if effective_role != normalize_org_role(m.role):
        # El claim puede estar desactualizado; la BD manda para permisos.
        pass

    # Exponer rol efectivo desde membresía (fuente de verdad).
    return OrgAuthContext(user=user, org=org, membership=m)


def require_mutator(
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
) -> OrgAuthContext:
    """Bloquea viewers (solo lectura) en acciones de generación/eliminación."""
    if not can_mutate_dossiers(ctx.role):
        raise HTTPException(
            status_code=403,
            detail="Permiso denegado: tu rol es de solo lectura.",
        )
    return ctx


def require_org_admin(
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
) -> OrgAuthContext:
    """Solo administradores de la organización."""
    if not can_manage_organization(ctx.role):
        raise HTTPException(
            status_code=403,
            detail="Solo un administrador de la organización puede realizar esta acción.",
        )
    return ctx


def get_current_user_and_org(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db_if_configured),
) -> tuple[User, Organization]:
    """
    Dependencia: usuario + organización del claim `org_id` del JWT.

    Usar en rutas multi-tenant (listados de dossiers, contactos, etc.).
    """
    payload, user = auth_payload_and_user(db, authorization)
    org_id_raw = payload.get("org_id")
    if not org_id_raw or not isinstance(org_id_raw, str):
        raise HTTPException(
            status_code=401,
            detail="Token sin organización (sesión antigua). Vuelve a iniciar sesión.",
        )
    try:
        org_uuid = UUID(org_id_raw)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Token corrupto (organización).") from e

    org = db.get(Organization, org_uuid)
    if org is None or not org.is_active:
        raise HTTPException(status_code=401, detail="Organización no encontrada o inactiva.")

    m = db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == org.id,
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=403, detail="No perteneces a esta organización.")
    return user, org


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db_if_configured),
) -> User:
    """Dependencia: usuario autenticado por JWT (sin comprobar org explícitamente)."""
    _, user = auth_payload_and_user(db, authorization)
    return user


@router.post("/register", response_model=TokenResponse)
def register_user(
    body: RegisterRequest, db: Session = Depends(get_db_if_configured)
) -> TokenResponse:
    _require_jwt_secret()
    email_norm = body.email.lower().strip()

    existing = db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Ya existe una cuenta con este email. Prueba a iniciar sesión.",
        )

    invite_token = (body.invite_token or "").strip() or None
    if invite_token:
        preview = preview_org_invite(db, invite_token)
        if not preview.get("valid"):
            raise HTTPException(status_code=400, detail="La invitación ya no es válida.")
        if email_norm != preview["email"]:
            raise HTTPException(
                status_code=400,
                detail="Debes registrarte con el correo al que se envió la invitación.",
            )
        user = User(
            email=email_norm,
            email_verified=False,
            password_hash=hash_password(body.password),
            full_name=body.full_name.strip()[:255],
            locale=_normalize_register_locale(body.locale),
        )
        db.add(user)
        db.flush()
        org, membership = accept_org_invite_for_register(db, token=invite_token, user=user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="No se pudo completar el registro.") from None
        db.refresh(user)
        token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            organization_id=str(org.id),
            role=membership.role,
        )
        return TokenResponse(access_token=token, user=build_user_public(db, user, org.id))

    if body.workspace_kind == "personal":
        slug = allocate_org_slug(db, email_norm)
        org_settings: dict = {"workspace_kind": "personal"}
        org_name = ORG_NAME_PERSONAL_PLACEHOLDER
    else:
        slug = allocate_org_slug(db, body.company_name or "")
        org_settings = {"workspace_kind": "work"}
        org_name = (body.company_name or "").strip()[:255]

    credits_balance, credits_monthly_limit = _signup_org_credits()
    org = Organization(
        name=org_name,
        slug=slug,
        credits_balance=credits_balance,
        credits_monthly_limit=credits_monthly_limit,
        settings=org_settings,
    )
    if body.workspace_kind == "work":
        try:
            ensure_org_email_domain(org, email=email_norm)
        except OrgApiError as e:
            raise HTTPException(status_code=400, detail=org_api_http_detail(e)) from e

    user = User(
        email=email_norm,
        email_verified=False,
        password_hash=hash_password(body.password),
        full_name=body.full_name.strip()[:255],
        locale=_normalize_register_locale(body.locale),
    )
    db.add(org)
    db.flush()
    db.add(user)
    db.flush()
    membership = OrgMembership(
        organization_id=org.id,
        user_id=user.id,
        role="admin",
        is_primary_org=True,
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="No se pudo completar el registro (dato duplicado). Reintenta con otro nombre de empresa.",
        ) from None

    db.refresh(user)
    db.refresh(org)

    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        organization_id=str(org.id),
        role=membership.role,
    )
    return TokenResponse(
        access_token=token,
        user=build_user_public(db, user, org.id),
    )


@router.post("/login", response_model=TokenResponse)
def login_user(body: LoginRequest, db: Session = Depends(get_db_if_configured)) -> TokenResponse:
    _require_jwt_secret()
    email_norm = body.email.lower().strip()
    user = db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()

    generic = "Email o contraseña incorrectos."
    if user is None or not user.password_hash:
        raise HTTPException(status_code=401, detail=generic)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail=generic)

    pair = load_session_membership(db, user.id)
    if not pair:
        raise HTTPException(
            status_code=500,
            detail="Cuenta sin organización asociada. Contacta soporte.",
        )
    org, membership = pair

    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        organization_id=str(org.id),
        role=membership.role,
    )
    return TokenResponse(
        access_token=token,
        user=build_user_public(db, user, org.id),
    )


@router.post("/session/refresh", response_model=TokenResponse)
def refresh_auth_session(
    authorization: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> TokenResponse:
    """Re-emite JWT con rol y org actuales desde la BD (p. ej. tras cambio de rol)."""
    _require_jwt_secret()
    org_id = _org_id_from_authorization(authorization)
    if org_id is not None:
        pair = load_membership_for_org(db, user.id, org_id)
        if pair is None:
            raise HTTPException(status_code=403, detail="Ya no perteneces a esa organización.")
        org, membership = pair
    else:
        pair = load_session_membership(db, user.id)
        if pair is None:
            raise HTTPException(
                status_code=500,
                detail="Cuenta sin organización asociada. Contacta soporte.",
            )
        org, membership = pair

    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        organization_id=str(org.id),
        role=membership.role,
    )
    return TokenResponse(
        access_token=token,
        user=build_user_public(db, user, org.id),
    )


@router.get("/me/organizations", response_model=UserOrganizationsResponse)
def list_my_organizations(
    authorization: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> UserOrganizationsResponse:
    """Organizaciones a las que pertenece el usuario (para el selector)."""
    active_org_id = _org_id_from_authorization(authorization)
    rows = db.execute(
        select(Organization, OrgMembership)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user.id, Organization.is_active.is_(True))
        .order_by(OrgMembership.joined_at.asc())
    ).all()
    items: list[UserOrganizationItem] = []
    for org, membership in rows:
        wk = read_workspace_kind(org)
        items.append(
            UserOrganizationItem(
                organization_id=org.id,
                organization_name="" if wk == "personal" else org.name,
                role=normalize_org_role(membership.role),
                workspace_kind=wk,
                is_primary=bool(membership.is_primary_org),
                is_active=(active_org_id is not None and org.id == active_org_id),
            )
        )
    return UserOrganizationsResponse(items=items)


@router.post("/session/switch", response_model=TokenResponse)
def switch_active_organization(
    body: SessionSwitchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> TokenResponse:
    """Cambia la organización activa de la sesión y emite un JWT nuevo con ese `org_id`/rol."""
    _require_jwt_secret()
    pair = load_membership_for_org(db, user.id, body.organization_id)
    if pair is None:
        raise HTTPException(status_code=403, detail="No perteneces a esa organización.")
    org, membership = pair
    if not org.is_active:
        raise HTTPException(status_code=404, detail="Organización no disponible.")

    _clear_and_set_primary_org(db, user.id, org.id)
    from dossier.services.org_membership_service import sync_calendar_integrations_org

    sync_calendar_integrations_org(db, user_id=user.id, organization_id=org.id)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        organization_id=str(org.id),
        role=membership.role,
    )
    return TokenResponse(
        access_token=token,
        user=build_user_public(db, user, org.id),
    )


def _clear_and_set_primary_org(db: Session, user_id: UUID, organization_id: UUID) -> None:
    rows = db.execute(
        select(OrgMembership).where(OrgMembership.user_id == user_id)
    ).scalars().all()
    for row in rows:
        should_be_primary = row.organization_id == organization_id
        if row.is_primary_org != should_be_primary:
            row.is_primary_org = should_be_primary
            db.add(row)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db_if_configured),
) -> ForgotPasswordResponse:
    """
    Solicitud de recuperación de contraseña.

    Siempre devuelve 200 con el mismo cuerpo para no filtrar si el correo existe en la BD.
    Cuando haya proveedor de correo, aquí se encolará el envío del enlace con token de un solo uso.
    """
    email_norm = body.email.lower().strip()
    user = db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
    if user is not None and user.password_hash:
        # Reservado: generar token, guardar expiración y enviar email.
        pass
    return ForgotPasswordResponse()


@router.get("/me", response_model=UserPublic)
def read_current_user(
    authorization: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> UserPublic:
    org_id = _org_id_from_authorization(authorization)
    return build_user_public(db, user, organization_id=org_id)


@router.patch("/me/password", status_code=204)
def patch_my_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> None:
    change_user_password(
        db,
        user=user,
        current_password=body.current_password,
        new_password=body.new_password,
    )


@router.patch("/me/email", response_model=TokenResponse)
def patch_my_email(
    body: ChangeEmailRequest,
    authorization: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> TokenResponse:
    updated = change_user_email(
        db,
        user=user,
        new_email=str(body.new_email),
        current_password=body.current_password,
    )
    org_id = _org_id_from_authorization(authorization)
    pair = (
        load_membership_for_org(db, updated.id, org_id)
        if org_id is not None
        else None
    ) or load_session_membership(db, updated.id)
    if pair is None:
        raise HTTPException(status_code=500, detail="Usuario sin membresía de organización.")
    org, membership = pair
    token = create_access_token(
        user_id=str(updated.id),
        email=updated.email,
        organization_id=str(org.id),
        role=membership.role,
    )
    return TokenResponse(
        access_token=token,
        user=build_user_public(db, updated, org.id),
    )


@router.delete("/me", status_code=204)
def delete_my_account(
    body: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> None:
    delete_user_account(db, user=user, current_password=body.current_password)


@router.get("/me/pending-invites", response_model=OrgPendingInvitesResponse)
def read_my_pending_invites(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> OrgPendingInvitesResponse:
    rows = list_pending_invites_for_email(db, email=user.email)
    db.commit()
    return OrgPendingInvitesResponse(items=[OrgInvitePreview(**row) for row in rows])


@router.patch("/me/preferences", response_model=UserPublic)
def patch_user_preferences(
    body: UserPreferencesPatch,
    authorization: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_if_configured),
) -> UserPublic:
    """Sincroniza idioma de interfaz, zona horaria e idioma de salida de dossiers."""
    if (
        body.locale is None
        and body.timezone is None
        and body.dossier_output_language is None
        and "dossier_retention_days" not in body.model_fields_set
    ):
        raise HTTPException(status_code=400, detail="No hay campos para actualizar.")

    if body.locale is not None:
        loc = body.locale.strip().lower().replace("_", "-")
        if loc not in ("en", "en-gb", "es", "pt", "it", "fr", "de"):
            raise HTTPException(status_code=400, detail="Locale no soportado.")
        user.locale = loc

    if body.timezone is not None:
        tz = body.timezone.strip()
        if not tz or len(tz) > 100:
            raise HTTPException(status_code=400, detail="Zona horaria inválida.")
        user.timezone = tz

    if body.dossier_output_language is not None:
        pref = body.dossier_output_language.strip().lower()
        if pref not in _ALLOWED_DOSSIER_OUTPUT_PREFS:
            raise HTTPException(
                status_code=400,
                detail="dossier_output_language no soportado.",
            )
        user.dossier_output_language = pref

    if "dossier_retention_days" in body.model_fields_set:
        try:
            user.dossier_retention_days = normalize_dossier_retention_days(
                body.dossier_retention_days
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    db.add(user)
    db.commit()
    db.refresh(user)
    org_id = _org_id_from_authorization(authorization)
    return build_user_public(db, user, organization_id=org_id)


@router.get("/organization/members", response_model=OrgMembersResponse)
def list_organization_members(
    ctx: Annotated[OrgAuthContext, Depends(get_org_auth_context)],
    db: Session = Depends(get_db_if_configured),
) -> OrgMembersResponse:
    """Lista miembros de la organización activa (p. ej. selector al compartir dossiers)."""
    raw = list_org_members(
        db,
        organization_id=ctx.org.id,
        exclude_user_id=ctx.user.id,
    )
    return OrgMembersResponse(items=[OrgMemberItem(**row) for row in raw])


@router.get("/organization/members/manage", response_model=OrgMembersManageResponse)
def list_organization_members_for_management(
    ctx: Annotated[OrgAuthContext, Depends(require_org_admin)],
    db: Session = Depends(get_db_if_configured),
) -> OrgMembersManageResponse:
    """Lista completa de miembros para el panel de administración (solo admin org)."""
    raw = list_org_members_for_management(
        db,
        organization_id=ctx.org.id,
        current_user_id=ctx.user.id,
    )
    return OrgMembersManageResponse(items=[OrgMemberManageItem(**row) for row in raw])


@router.patch("/organization/members/{target_user_id}", response_model=OrgMemberManageItem)
def patch_organization_member_role(
    target_user_id: UUID,
    body: OrgMemberRolePatch,
    ctx: Annotated[OrgAuthContext, Depends(require_org_admin)],
    db: Session = Depends(get_db_if_configured),
) -> OrgMemberManageItem:
    row = update_org_member_role(
        db,
        organization_id=ctx.org.id,
        actor_user_id=ctx.user.id,
        target_user_id=target_user_id,
        new_role=body.role,
    )
    db.commit()
    return OrgMemberManageItem(**row)


@router.delete("/organization/members/{target_user_id}", status_code=204)
def delete_organization_member(
    target_user_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(require_org_admin)],
    db: Session = Depends(get_db_if_configured),
) -> None:
    remove_org_member(
        db,
        organization_id=ctx.org.id,
        actor_user_id=ctx.user.id,
        target_user_id=target_user_id,
    )
    db.commit()


@router.get("/organization/invites/preview", response_model=OrgInvitePreview)
def get_organization_invite_preview(
    token: str,
    db: Session = Depends(get_db_if_configured),
) -> OrgInvitePreview:
    """Vista previa pública de una invitación (para registro o aceptación)."""
    row = preview_org_invite(db, token)
    db.commit()
    return OrgInvitePreview(**row)


@router.get("/organization/invites", response_model=OrgInvitesResponse)
def list_organization_invites(
    ctx: Annotated[OrgAuthContext, Depends(require_org_admin)],
    db: Session = Depends(get_db_if_configured),
) -> OrgInvitesResponse:
    if read_workspace_kind(ctx.org) != "work":
        raise HTTPException(
            status_code=400,
            detail={"code": INVITES_WORKSPACE_ONLY},
        )
    try:
        domain = ensure_org_email_domain(ctx.org, email=ctx.user.email)
    except OrgApiError as e:
        raise HTTPException(status_code=400, detail=org_api_http_detail(e)) from e
    db.add(ctx.org)
    items = list_org_invites(db, organization_id=ctx.org.id)
    db.commit()
    return OrgInvitesResponse(
        organization_domain=domain,
        items=[OrgInviteItem(**row) for row in items],
    )


@router.post("/organization/invites", response_model=OrgInviteItem, status_code=201)
def post_organization_invite(
    body: OrgInviteCreate,
    ctx: Annotated[OrgAuthContext, Depends(require_org_admin)],
    db: Session = Depends(get_db_if_configured),
) -> OrgInviteItem:
    row = create_org_invite(
        db,
        org=ctx.org,
        inviter=ctx.user,
        email=str(body.email),
        role=body.role,
    )
    db.add(ctx.org)
    db.commit()
    return OrgInviteItem(**row)


@router.delete("/organization/invites/{invite_id}", status_code=204)
def delete_organization_invite(
    invite_id: UUID,
    ctx: Annotated[OrgAuthContext, Depends(require_org_admin)],
    db: Session = Depends(get_db_if_configured),
) -> None:
    revoke_org_invite(db, organization_id=ctx.org.id, invite_id=invite_id)
    db.commit()


@router.post("/organization/invites/accept", response_model=TokenResponse)
def post_accept_organization_invite(
    body: OrgInviteAcceptRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db_if_configured),
) -> TokenResponse:
    """Usuario autenticado acepta invitación y cambia a esa organización."""
    org, membership = accept_org_invite(db, token=body.token.strip(), user=user, make_primary=True)
    db.commit()
    db.refresh(user)
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        organization_id=str(org.id),
        role=membership.role,
    )
    return TokenResponse(access_token=token, user=build_user_public(db, user, org.id))


@router.patch("/organization/plan", response_model=UserPublic)
def patch_organization_plan(
    body: OrganizationPlanPatch,
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    db: Session = Depends(get_db_if_configured),
) -> UserPublic:
    user, org = user_org
    m = db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == org.id,
        )
    ).scalar_one_or_none()
    if m is None or not can_manage_organization(m.role):
        raise HTTPException(
            status_code=403,
            detail="Solo un administrador de la organización puede cambiar el plan.",
        )
    try:
        apply_plan_to_organization(org, body.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.add(org)
    db.commit()
    db.refresh(org)
    db.refresh(user)
    return build_user_public(db, user, org.id)


@router.patch("/organization/dossier-context", response_model=UserPublic)
def patch_organization_dossier_context(
    body: OrganizationDossierContextPatch,
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    db: Session = Depends(get_db_if_configured),
) -> UserPublic:
    """Guarda texto libre sobre la empresa del tenant (para prompts de dossiers)."""
    user, org = user_org
    m = db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == org.id,
        )
    ).scalar_one_or_none()
    if m is None or not can_manage_organization(m.role):
        raise HTTPException(
            status_code=403,
            detail="Solo un administrador de la organización puede editar el contexto de empresa.",
        )
    apply_dossier_context_patch(
        org,
        company_summary=body.company_summary,
        industry_or_area=body.industry_or_area,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    db.refresh(user)
    return build_user_public(db, user, org.id)
