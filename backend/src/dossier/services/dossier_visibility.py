"""Visibilidad de dossiers por rol (propios, compartidos o toda la org)."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.orm import Session

from dossier.db.models import Dossier, DossierShare
from dossier.security.rbac import normalize_org_role


def dossier_visibility_filter(
    *,
    user_id: UUID,
    organization_id: UUID,
    role: str | None,
) -> ColumnElement[bool]:
    """
    Condición SQLAlchemy para filas de ``dossiers`` visibles al usuario.

    - admin: toda la organización
    - user: propios + compartidos
    - viewer: solo compartidos
    """
    org_clause = Dossier.organization_id == organization_id
    norm = normalize_org_role(role)
    if norm == "admin":
        return org_clause

    shared_ids = (
        select(DossierShare.dossier_id).where(DossierShare.shared_with_user_id == user_id)
    )
    if norm == "viewer":
        return and_(org_clause, Dossier.id.in_(shared_ids))
    return and_(
        org_clause,
        or_(
            Dossier.requested_by_user_id == user_id,
            Dossier.id.in_(shared_ids),
        ),
    )


def apply_dossier_visibility(
    stmt: Select,
    *,
    user_id: UUID,
    organization_id: UUID,
    role: str | None,
) -> Select:
    return stmt.where(
        dossier_visibility_filter(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
        )
    )


def _is_shared_with(db: Session, *, dossier_id: UUID, user_id: UUID) -> bool:
    row = db.execute(
        select(DossierShare.id).where(
            DossierShare.dossier_id == dossier_id,
            DossierShare.shared_with_user_id == user_id,
        )
    ).first()
    return row is not None


def user_can_view_dossier(
    db: Session,
    *,
    dossier: Dossier,
    user_id: UUID,
    organization_id: UUID,
    role: str | None,
) -> bool:
    if dossier.organization_id != organization_id:
        return False
    norm = normalize_org_role(role)
    if norm == "admin":
        return True
    if _is_shared_with(db, dossier_id=dossier.id, user_id=user_id):
        return True
    if norm == "viewer":
        return False
    return dossier.requested_by_user_id == user_id


def user_can_delete_dossier(
    db: Session,
    *,
    dossier: Dossier,
    user_id: UUID,
    organization_id: UUID,
    role: str | None,
) -> bool:
    if not user_can_view_dossier(
        db,
        dossier=dossier,
        user_id=user_id,
        organization_id=organization_id,
        role=role,
    ):
        return False
    norm = normalize_org_role(role)
    if norm == "admin":
        return True
    if norm == "user":
        return dossier.requested_by_user_id == user_id
    return False


def get_visible_dossier_or_404(
    db: Session,
    *,
    dossier_id: UUID,
    user_id: UUID,
    organization_id: UUID,
    role: str | None,
) -> Dossier:
    dossier = db.get(Dossier, dossier_id)
    if dossier is None or not user_can_view_dossier(
        db,
        dossier=dossier,
        user_id=user_id,
        organization_id=organization_id,
        role=role,
    ):
        raise HTTPException(status_code=404, detail="Dossier no encontrado.")
    return dossier
