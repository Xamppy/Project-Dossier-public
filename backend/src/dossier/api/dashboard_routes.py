"""Resumen de indicadores de /dashboard (UX-KPI-01)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from dossier.api.auth_routes import get_current_user_and_org, get_db_if_configured
from dossier.db.models import Organization, User
from dossier.schemas.dashboard_summary import DashboardSummary
from dossier.services.dashboard_summary import build_dashboard_summary

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard/summary", response_model=DashboardSummary)
def api_dashboard_summary(
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    db: Session = Depends(get_db_if_configured),
) -> dict:
    """Cuatro indicadores de Resumen. Usuario y organización salen de la sesión, nunca del cliente.

    Solo lectura: no genera dossiers, no programa trabajos y no consume créditos. Los
    indicadores de preparación son personales (también para un administrador); el saldo es
    de la organización.
    """
    user, org = user_org
    return build_dashboard_summary(db, user=user, org=org)
