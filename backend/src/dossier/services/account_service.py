"""Cambio de credenciales y eliminación de cuenta del usuario autenticado."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from dossier.db.models import (
    Contact,
    Dossier,
    DossierGenerationJob,
    DossierShare,
    OrgInvite,
    OrgMembership,
    User,
)
from dossier.security import hash_password, verify_password
from dossier.security.rbac import normalize_org_role
from dossier.services.dossier_deletion_service import delete_dossier_record, finalize_dossier_deletions
from dossier.services.org_membership_service import delete_organization_if_empty


def _require_password(user: User, password: str) -> None:
    if not user.password_hash:
        raise HTTPException(
            status_code=400,
            detail="Esta cuenta no tiene contraseña configurada.",
        )
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta.")


def change_user_password(
    db: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    _require_password(user, current_password)
    user.password_hash = hash_password(new_password)
    db.add(user)
    db.commit()


def change_user_email(
    db: Session,
    *,
    user: User,
    new_email: str,
    current_password: str,
) -> User:
    _require_password(user, current_password)
    email_norm = new_email.lower().strip()
    if email_norm == user.email.lower():
        raise HTTPException(status_code=400, detail="El correo es el mismo que el actual.")
    taken = db.execute(select(User.id).where(User.email == email_norm)).scalar_one_or_none()
    if taken is not None:
        raise HTTPException(
            status_code=409,
            detail="Ya existe una cuenta con este email.",
        )
    user.email = email_norm
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _count_org_members(db: Session, organization_id: UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(OrgMembership)
            .where(OrgMembership.organization_id == organization_id)
        ).scalar_one()
        or 0
    )


def _count_org_admins(db: Session, organization_id: UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(OrgMembership)
            .where(
                OrgMembership.organization_id == organization_id,
                OrgMembership.role == "admin",
            )
        ).scalar_one()
        or 0
    )


def _assert_can_delete_account(
    db: Session,
    user: User,
    *,
    skip_platform_admin_check: bool = False,
    skip_sole_admin_check: bool = False,
) -> list[OrgMembership]:
    if not skip_platform_admin_check and user.is_platform_admin:
        raise HTTPException(
            status_code=400,
            detail=(
                "No puedes eliminar una cuenta con rol de administrador de plataforma. "
                "Quita ese rol antes de continuar."
            ),
        )

    memberships = list(
        db.execute(select(OrgMembership).where(OrgMembership.user_id == user.id)).scalars().all()
    )
    if skip_sole_admin_check:
        return memberships
    for membership in memberships:
        members = _count_org_members(db, membership.organization_id)
        if members <= 1:
            continue
        if normalize_org_role(membership.role) == "admin" and _count_org_admins(db, membership.organization_id) <= 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Eres el único administrador de una organización con más miembros. "
                    "Asigna otro administrador antes de eliminar tu cuenta."
                ),
            )
    return memberships


def _pick_replacement_member(
    db: Session, organization_id: UUID, exclude_user_id: UUID
) -> UUID | None:
    return db.execute(
        select(OrgMembership.user_id)
        .where(
            OrgMembership.organization_id == organization_id,
            OrgMembership.user_id != exclude_user_id,
        )
        .limit(1)
    ).scalar_one_or_none()


def _detach_user_references(db: Session, user: User) -> None:
    """Quita referencias al usuario en filas que no se borran con él (FK sin CASCADE)."""
    db.execute(
        update(OrgMembership)
        .where(OrgMembership.invited_by_user_id == user.id)
        .values(invited_by_user_id=None)
    )

    contacts = db.execute(
        select(Contact).where(Contact.created_by_user_id == user.id)
    ).scalars().all()
    for contact in contacts:
        replacement = _pick_replacement_member(db, contact.organization_id, user.id)
        if replacement is not None:
            contact.created_by_user_id = replacement
            db.add(contact)
        else:
            db.delete(contact)

    ledger_rows = db.execute(
        text("SELECT id, organization_id FROM credit_ledger WHERE user_id = :uid"),
        {"uid": user.id},
    ).fetchall()
    for row in ledger_rows:
        replacement = _pick_replacement_member(db, row.organization_id, user.id)
        if replacement is not None:
            db.execute(
                text("UPDATE credit_ledger SET user_id = :rid WHERE id = :lid"),
                {"rid": replacement, "lid": row.id},
            )
        else:
            db.execute(
                text("DELETE FROM credit_ledger WHERE id = :lid"),
                {"lid": row.id},
            )

    db.execute(
        text(
            "UPDATE dossier_alerts SET acknowledged_by_user_id = NULL "
            "WHERE acknowledged_by_user_id = :uid"
        ),
        {"uid": user.id},
    )


def _purge_user_account(db: Session, user: User, memberships: list[OrgMembership]) -> None:
    dossiers = db.execute(
        select(Dossier).where(Dossier.requested_by_user_id == user.id)
    ).scalars().all()
    calendar_event_ids: set[UUID | None] = set()
    for dossier in dossiers:
        calendar_event_ids.add(delete_dossier_record(db, dossier))

    db.execute(
        delete(DossierGenerationJob).where(DossierGenerationJob.requested_by_user_id == user.id)
    )
    db.execute(
        delete(DossierShare).where(DossierShare.shared_by_user_id == user.id)
    )
    db.execute(
        delete(OrgInvite).where(OrgInvite.invited_by_user_id == user.id)
    )

    affected_org_ids = {membership.organization_id for membership in memberships}
    _detach_user_references(db, user)

    for membership in memberships:
        db.delete(membership)

    db.flush()

    for org_id in affected_org_ids:
        delete_organization_if_empty(db, org_id)

    finalize_dossier_deletions(db, calendar_event_ids)

    db.delete(user)
    db.commit()


def delete_user_account(db: Session, *, user: User, current_password: str) -> None:
    _require_password(user, current_password)
    memberships = _assert_can_delete_account(db, user)
    _purge_user_account(db, user, memberships)


def admin_delete_user_account(db: Session, *, actor: User, target: User) -> None:
    if actor.id == target.id:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar tu propia cuenta desde el panel de administración.",
        )
    memberships = _assert_can_delete_account(
        db,
        target,
        skip_platform_admin_check=True,
        skip_sole_admin_check=True,
    )
    _purge_user_account(db, target, memberships)
