"""Compartir dossiers con miembros de la misma organización."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dossier.db.models import Dossier, DossierShare, Organization, OrgMembership, User
from dossier.org_workspace import read_workspace_kind
from dossier.security.rbac import normalize_org_role


def user_can_share_dossier(
    *,
    dossier: Dossier,
    user_id: UUID,
    role: str | None,
    workspace_kind: Literal["personal", "work"] = "work",
) -> bool:
    """Dueño del dossier o admin de la org pueden compartir (solo cuentas empresa)."""
    if workspace_kind == "personal":
        return False
    norm = normalize_org_role(role)
    if norm == "admin":
        return True
    if norm == "user":
        return dossier.requested_by_user_id == user_id
    return False


def _org_member_user_ids(db: Session, organization_id: UUID) -> set[UUID]:
    rows = db.execute(
        select(OrgMembership.user_id).where(OrgMembership.organization_id == organization_id)
    ).scalars().all()
    return set(rows)


def list_org_members(
    db: Session,
    *,
    organization_id: UUID,
    exclude_user_id: UUID | None = None,
) -> list[dict]:
    """Miembros de la org para el selector de compartir."""
    stmt = (
        select(User, OrgMembership)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .where(OrgMembership.organization_id == organization_id)
        .order_by(User.full_name.asc(), User.email.asc())
    )
    rows = db.execute(stmt).all()
    out: list[dict] = []
    for user, membership in rows:
        if exclude_user_id and user.id == exclude_user_id:
            continue
        out.append(
            {
                "user_id": str(user.id),
                "email": user.email,
                "full_name": user.full_name or "",
                "role": normalize_org_role(membership.role),
            }
        )
    return out


def list_dossier_shares(db: Session, *, dossier_id: UUID) -> list[dict]:
    stmt = (
        select(DossierShare, User)
        .join(User, User.id == DossierShare.shared_with_user_id)
        .where(DossierShare.dossier_id == dossier_id)
        .order_by(DossierShare.created_at.asc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "user_id": str(user.id),
            "email": user.email,
            "full_name": user.full_name or "",
            "shared_at": share.created_at.isoformat() if share.created_at else None,
        }
        for share, user in rows
    ]


def share_dossier_with_user(
    db: Session,
    *,
    dossier: Dossier,
    shared_with_user_id: UUID,
    shared_by_user_id: UUID,
    organization_id: UUID,
) -> DossierShare:
    if shared_with_user_id == dossier.requested_by_user_id:
        raise HTTPException(status_code=400, detail="El dossier ya pertenece a ese usuario.")
    if shared_with_user_id == shared_by_user_id:
        raise HTTPException(status_code=400, detail="No puedes compartir un dossier contigo mismo.")

    members = _org_member_user_ids(db, organization_id)
    if shared_with_user_id not in members:
        raise HTTPException(status_code=400, detail="El usuario no pertenece a tu organización.")

    existing = db.execute(
        select(DossierShare).where(
            DossierShare.dossier_id == dossier.id,
            DossierShare.shared_with_user_id == shared_with_user_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    share = DossierShare(
        dossier_id=dossier.id,
        shared_with_user_id=shared_with_user_id,
        shared_by_user_id=shared_by_user_id,
    )
    db.add(share)
    db.flush()
    return share


def unshare_dossier_with_user(
    db: Session,
    *,
    dossier_id: UUID,
    shared_with_user_id: UUID,
) -> bool:
    row = db.execute(
        select(DossierShare).where(
            DossierShare.dossier_id == dossier_id,
            DossierShare.shared_with_user_id == shared_with_user_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def dossier_permissions_payload(
    db: Session,
    *,
    dossier: Dossier,
    user_id: UUID,
    organization_id: UUID,
    role: str | None,
) -> dict:
    from dossier.services.dossier_visibility import user_can_delete_dossier

    is_owner = dossier.requested_by_user_id == user_id
    org = db.get(Organization, organization_id)
    workspace_kind = read_workspace_kind(org) if org else "work"
    can_share = user_can_share_dossier(
        dossier=dossier,
        user_id=user_id,
        role=role,
        workspace_kind=workspace_kind,
    )
    can_delete = user_can_delete_dossier(
        db,
        dossier=dossier,
        user_id=user_id,
        organization_id=organization_id,
        role=role,
    )
    norm = normalize_org_role(role)
    can_mutate = norm in ("admin", "user")
    return {
        "is_owner": is_owner,
        "can_share": can_share,
        "can_delete": can_delete,
        "can_mutate": can_mutate,
    }
