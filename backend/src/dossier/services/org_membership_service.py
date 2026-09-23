"""Gestión de membresías de organización (roles RBAC)."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dossier.db.models import Organization, OrgMembership, User
from dossier.security.rbac import normalize_org_role

ASSIGNABLE_ORG_ROLES: frozenset[str] = frozenset({"admin", "user", "viewer"})


def active_organization_id_for_user(
    db: Session,
    user_id: UUID,
    *,
    fallback: UUID | None = None,
) -> UUID | None:
    """
    Organización activa del usuario (``is_primary_org``), la misma que usa el JWT tras
    cambiar de org en la app. Si no hay primaria, devuelve ``fallback``.
    """
    row = db.execute(
        select(Organization.id)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.is_primary_org.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return row
    first = db.execute(
        select(Organization.id)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user_id)
        .order_by(OrgMembership.joined_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    return first if first is not None else fallback


def sync_calendar_integrations_org(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> int:
    """Alinea ``calendar_integrations.organization_id`` con la org activa del usuario."""
    from dossier.db.models import CalendarIntegration

    rows = db.execute(
        select(CalendarIntegration).where(CalendarIntegration.user_id == user_id)
    ).scalars().all()
    touched = 0
    for row in rows:
        if row.organization_id != organization_id:
            row.organization_id = organization_id
            touched += 1
    return touched


def _count_org_admins(db: Session, organization_id: UUID) -> int:
    count = db.execute(
        select(func.count())
        .select_from(OrgMembership)
        .where(
            OrgMembership.organization_id == organization_id,
            OrgMembership.role == "admin",
        )
    ).scalar_one()
    return int(count or 0)


def delete_organization_if_empty(db: Session, organization_id: UUID) -> bool:
    """Elimina la organización si ya no queda ningún miembro."""
    members = db.execute(
        select(func.count())
        .select_from(OrgMembership)
        .where(OrgMembership.organization_id == organization_id)
    ).scalar_one()
    if int(members or 0) > 0:
        return False
    org = db.get(Organization, organization_id)
    if org is None:
        return False
    db.delete(org)
    return True


def list_org_members_for_management(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
) -> list[dict]:
    """Todos los miembros de la org (incluye al usuario actual)."""
    stmt = (
        select(User, OrgMembership)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .where(OrgMembership.organization_id == organization_id)
        .order_by(User.full_name.asc(), User.email.asc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "user_id": str(user.id),
            "email": user.email,
            "full_name": user.full_name or "",
            "role": normalize_org_role(membership.role),
            "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
            "is_self": user.id == current_user_id,
        }
        for user, membership in rows
    ]


def update_org_member_role(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    target_user_id: UUID,
    new_role: str,
) -> dict:
    role = normalize_org_role(new_role)
    if role not in ASSIGNABLE_ORG_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Rol no válido. Usa admin, user o viewer.",
        )

    membership = db.execute(
        select(OrgMembership).where(
            OrgMembership.organization_id == organization_id,
            OrgMembership.user_id == target_user_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="El usuario no pertenece a tu organización.")

    current_role = normalize_org_role(membership.role)
    if current_role == role:
        user = db.execute(select(User).where(User.id == target_user_id)).scalar_one()
        return {
            "user_id": str(user.id),
            "email": user.email,
            "full_name": user.full_name or "",
            "role": role,
            "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
            "is_self": target_user_id == actor_user_id,
        }

    if current_role == "admin" and role != "admin":
        if _count_org_admins(db, organization_id) <= 1:
            raise HTTPException(
                status_code=400,
                detail="No puedes quitar el último administrador de la organización.",
            )
        if target_user_id == actor_user_id:
            raise HTTPException(
                status_code=400,
                detail="No puedes dejar de ser administrador si eres el único admin.",
            )

    membership.role = role
    db.add(membership)
    db.flush()

    user = db.execute(select(User).where(User.id == target_user_id)).scalar_one()
    return {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name or "",
        "role": role,
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        "is_self": target_user_id == actor_user_id,
    }


def remove_org_member(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    target_user_id: UUID,
) -> None:
    if target_user_id == actor_user_id:
        raise HTTPException(status_code=400, detail="No puedes eliminarte de la organización.")

    membership = db.execute(
        select(OrgMembership).where(
            OrgMembership.organization_id == organization_id,
            OrgMembership.user_id == target_user_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="El usuario no pertenece a tu organización.")

    if normalize_org_role(membership.role) == "admin" and _count_org_admins(db, organization_id) <= 1:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar al último administrador de la organización.",
        )

    db.delete(membership)
    db.flush()
    delete_organization_if_empty(db, organization_id)
