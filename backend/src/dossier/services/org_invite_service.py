"""Invitaciones a organizaciones con restricción de dominio de correo."""
from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.api_errors import (
    INVITE_WRONG_DOMAIN,
    INVITES_WORKSPACE_ONLY,
    OrgApiError,
    org_api_http_detail,
)
from dossier.db.models import Organization, OrgInvite, OrgMembership, User
from dossier.org_email_domain import email_matches_org_domain, ensure_org_email_domain, read_org_email_domain
from dossier.org_workspace import read_workspace_kind
from dossier.security.rbac import normalize_org_role
from dossier.services.org_membership_service import ASSIGNABLE_ORG_ROLES

INVITE_TTL_DAYS = 7


def _frontend_base_url() -> str:
    return (os.getenv("DOSSIER_FRONTEND_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")


def _invite_url(token: str) -> str:
    return f"{_frontend_base_url()}/register?invite={token}"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _invite_is_expired(invite: OrgInvite, now: datetime | None = None) -> bool:
    ts = now or datetime.now(UTC)
    exp = invite.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    return ts > exp


def _serialize_invite(invite: OrgInvite, *, joined_immediately: bool = False) -> dict:
    return {
        "id": str(invite.id),
        "email": invite.email,
        "role": normalize_org_role(invite.role),
        "status": invite.status,
        "invite_url": _invite_url(invite.token) if invite.status == "pending" else None,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "joined_immediately": joined_immediately,
    }


def _clear_primary_org_flags(db: Session, user_id: UUID) -> None:
    rows = db.execute(select(OrgMembership).where(OrgMembership.user_id == user_id)).scalars().all()
    for row in rows:
        if row.is_primary_org:
            row.is_primary_org = False
            db.add(row)


def add_user_to_organization(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str,
    invited_by_user_id: UUID | None,
    make_primary: bool,
) -> OrgMembership:
    existing = db.execute(
        select(OrgMembership).where(
            OrgMembership.organization_id == organization_id,
            OrgMembership.user_id == user_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="El usuario ya pertenece a esta organización.")

    norm_role = normalize_org_role(role)
    if norm_role not in ASSIGNABLE_ORG_ROLES:
        raise HTTPException(status_code=400, detail="Rol no válido.")

    if make_primary:
        _clear_primary_org_flags(db, user_id)

    membership = OrgMembership(
        organization_id=organization_id,
        user_id=user_id,
        role=norm_role,
        is_primary_org=make_primary,
        invited_by_user_id=invited_by_user_id,
    )
    db.add(membership)
    db.flush()
    return membership


def list_org_invites(db: Session, *, organization_id: UUID) -> list[dict]:
    now = datetime.now(UTC)
    rows = db.execute(
        select(OrgInvite)
        .where(
            OrgInvite.organization_id == organization_id,
            OrgInvite.status.in_(("pending", "accepted")),
        )
        .order_by(OrgInvite.created_at.desc())
    ).scalars().all()
    out: list[dict] = []
    for invite in rows:
        if invite.status == "pending" and _invite_is_expired(invite, now):
            invite.status = "expired"
            db.add(invite)
            continue
        out.append(_serialize_invite(invite))
    return out


def create_org_invite(
    db: Session,
    *,
    org: Organization,
    inviter: User,
    email: str,
    role: str,
) -> dict:
    if read_workspace_kind(org) != "work":
        raise HTTPException(
            status_code=400,
            detail={"code": INVITES_WORKSPACE_ONLY},
        )

    try:
        org_domain = ensure_org_email_domain(org, email=inviter.email)
    except OrgApiError as e:
        raise HTTPException(status_code=400, detail=org_api_http_detail(e)) from e

    email_norm = _normalize_email(email)
    if not email_matches_org_domain(org, email_norm, fallback_admin_email=inviter.email):
        raise HTTPException(
            status_code=400,
            detail={"code": INVITE_WRONG_DOMAIN, "domain": org_domain},
        )

    norm_role = normalize_org_role(role)
    if norm_role not in ASSIGNABLE_ORG_ROLES:
        raise HTTPException(status_code=400, detail="Rol no válido.")

    existing_member = db.execute(
        select(OrgMembership)
        .join(User, User.id == OrgMembership.user_id)
        .where(
            OrgMembership.organization_id == org.id,
            User.email == email_norm,
        )
    ).scalar_one_or_none()
    if existing_member is not None:
        raise HTTPException(status_code=409, detail="Ese usuario ya es miembro de la organización.")

    target_user = db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
    if target_user is not None:
        add_user_to_organization(
            db,
            organization_id=org.id,
            user_id=target_user.id,
            role=norm_role,
            invited_by_user_id=inviter.id,
            make_primary=read_workspace_kind(org) == "work",
        )
        # Marca invitación aceptada de forma inmediata (auditoría).
        now = datetime.now(UTC)
        invite = OrgInvite(
            organization_id=org.id,
            email=email_norm,
            role=norm_role,
            token=secrets.token_urlsafe(32),
            status="accepted",
            invited_by_user_id=inviter.id,
            expires_at=now + timedelta(days=INVITE_TTL_DAYS),
            accepted_at=now,
        )
        db.add(invite)
        db.flush()
        return _serialize_invite(invite, joined_immediately=True)

    pending = db.execute(
        select(OrgInvite).where(
            OrgInvite.organization_id == org.id,
            OrgInvite.email == email_norm,
            OrgInvite.status == "pending",
        )
    ).scalar_one_or_none()
    if pending is not None:
        if _invite_is_expired(pending):
            pending.status = "expired"
            db.add(pending)
        else:
            raise HTTPException(
                status_code=409,
                detail="Ya existe una invitación pendiente para ese correo.",
            )

    now = datetime.now(UTC)
    invite = OrgInvite(
        organization_id=org.id,
        email=email_norm,
        role=norm_role,
        token=secrets.token_urlsafe(32),
        status="pending",
        invited_by_user_id=inviter.id,
        expires_at=now + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.flush()
    return _serialize_invite(invite)


def revoke_org_invite(
    db: Session,
    *,
    organization_id: UUID,
    invite_id: UUID,
) -> None:
    invite = db.execute(
        select(OrgInvite).where(
            OrgInvite.id == invite_id,
            OrgInvite.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitación no encontrada.")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Solo se pueden revocar invitaciones pendientes.")
    invite.status = "revoked"
    db.add(invite)


def get_invite_by_token(db: Session, token: str) -> OrgInvite | None:
    invite = db.execute(select(OrgInvite).where(OrgInvite.token == token.strip())).scalar_one_or_none()
    if invite is None:
        return None
    if invite.status != "pending":
        return invite
    if _invite_is_expired(invite):
        invite.status = "expired"
        db.add(invite)
        db.flush()
    return invite


def preview_org_invite(db: Session, token: str) -> dict:
    invite = get_invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitación no encontrada.")
    org = db.get(Organization, invite.organization_id)
    if org is None or not org.is_active:
        raise HTTPException(status_code=404, detail="Organización no disponible.")
    domain = read_org_email_domain(org) or invite.email.split("@", 1)[-1]
    valid = invite.status == "pending" and not _invite_is_expired(invite)
    return {
        "organization_id": str(org.id),
        "organization_name": org.name,
        "email": invite.email,
        "role": normalize_org_role(invite.role),
        "email_domain": domain,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "valid": valid,
    }


def accept_org_invite(
    db: Session,
    *,
    token: str,
    user: User,
    make_primary: bool = True,
) -> tuple[Organization, OrgMembership]:
    invite = get_invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitación no encontrada.")
    if invite.status != "pending" or _invite_is_expired(invite):
        raise HTTPException(status_code=400, detail="La invitación ya no es válida.")

    if _normalize_email(user.email) != invite.email:
        raise HTTPException(
            status_code=403,
            detail="Debes iniciar sesión con el correo al que se envió la invitación.",
        )

    org = db.get(Organization, invite.organization_id)
    if org is None or not org.is_active:
        raise HTTPException(status_code=404, detail="Organización no disponible.")

    membership = add_user_to_organization(
        db,
        organization_id=org.id,
        user_id=user.id,
        role=invite.role,
        invited_by_user_id=invite.invited_by_user_id,
        make_primary=make_primary,
    )
    invite.status = "accepted"
    invite.accepted_at = datetime.now(UTC)
    db.add(invite)
    return org, membership


def accept_org_invite_for_register(
    db: Session,
    *,
    token: str,
    user: User,
) -> tuple[Organization, OrgMembership]:
    """Tras crear usuario nuevo vía enlace de invitación."""
    return accept_org_invite(db, token=token, user=user, make_primary=True)


def list_pending_invites_for_email(db: Session, *, email: str) -> list[dict]:
    email_norm = _normalize_email(email)
    now = datetime.now(UTC)
    rows = db.execute(
        select(OrgInvite, Organization)
        .join(Organization, Organization.id == OrgInvite.organization_id)
        .where(
            OrgInvite.email == email_norm,
            OrgInvite.status == "pending",
        )
        .order_by(OrgInvite.created_at.desc())
    ).all()
    out: list[dict] = []
    for invite, org in rows:
        if _invite_is_expired(invite, now):
            invite.status = "expired"
            db.add(invite)
            continue
        domain = read_org_email_domain(org) or email_norm.split("@", 1)[-1]
        out.append(
            {
                "token": invite.token,
                "organization_id": str(org.id),
                "organization_name": org.name,
                "email": invite.email,
                "role": normalize_org_role(invite.role),
                "email_domain": domain,
                "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
                "valid": True,
            }
        )
    return out
