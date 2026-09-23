"""Reglas de plan (Free / Pro / Enterprise) y profundidad de dossier."""
from __future__ import annotations

from fastapi import HTTPException

from dossier.billing.plan_catalog import PlanId, normalize_plan
from dossier.db.models import Organization
from dossier.schemas.dossier_generation import DEPTH_CREDITS, DossierDepth

_ALLOWED_DEPTHS: dict[PlanId, frozenset[DossierDepth]] = {
    "free": frozenset({"basic"}),
    "pro": frozenset({"basic", "standard", "deep"}),
    "enterprise": frozenset({"basic", "standard", "deep"}),
}


def allowed_depths_for_plan(plan: str | None) -> frozenset[DossierDepth]:
    return _ALLOWED_DEPTHS.get(normalize_plan(plan), frozenset({"basic"}))


def plan_allows_depth(plan: str | None, depth: DossierDepth) -> bool:
    return depth in allowed_depths_for_plan(plan)


def plan_allows_automation(plan: str | None) -> bool:
    return normalize_plan(plan) in ("pro", "enterprise")


def plan_allows_corporate_dossier(plan: str | None) -> bool:
    """Plan Free: sin módulo B (empresa) — ni manual ni desde calendario."""
    return normalize_plan(plan) != "free"


def plan_allows_calendar_corporate_dossier(plan: str | None) -> bool:
    """Alias histórico: misma regla que ``plan_allows_corporate_dossier``."""
    return plan_allows_corporate_dossier(plan)


def default_depth_for_plan(plan: str | None) -> DossierDepth:
    """Profundidad por defecto si el cliente no envía una."""
    if normalize_plan(plan) == "free":
        return "basic"
    return "standard"


def normalize_depth_for_plan(plan: str | None, raw: str | None) -> DossierDepth:
    depth = (raw or default_depth_for_plan(plan)).strip().lower()
    candidate = depth if depth in DEPTH_CREDITS else default_depth_for_plan(plan)
    if plan_allows_depth(plan, candidate):
        return candidate
    return "basic"


def assert_depth_allowed(org: Organization, depth: DossierDepth) -> None:
    if plan_allows_depth(org.plan, depth):
        return
    labels = {
        "standard": "Estándar",
        "deep": "Deep",
    }
    label = labels.get(depth, depth)
    raise HTTPException(
        status_code=403,
        detail=(
            f"Tu plan {normalize_plan(org.plan).upper()} no permite profundidad {label}. "
            "Actualiza a Pro o Enterprise para usar Estándar o Deep."
        ),
    )


def assert_automation_allowed(org: Organization) -> None:
    if plan_allows_automation(org.plan):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "La automatización de calendario requiere plan Pro o Enterprise. "
            "Puedes generar dossiers manualmente desde el calendario."
        ),
    )


def assert_corporate_dossier_allowed(org: Organization) -> None:
    if plan_allows_corporate_dossier(org.plan):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Los dossiers de empresa requieren plan Pro o Enterprise. "
            "En el plan Free solo puedes generar dossiers de persona."
        ),
    )


def corporate_dossier_module_flags(depth: DossierDepth) -> dict[str, bool]:
    """
    Flags en ``dossiers`` para informes corporativos.

    ``module_corporate`` identifica el tipo «empresa»; ``module_media`` indica módulo C (Deep).
    """
    return {
        "module_identity": False,
        "module_corporate": True,
        "module_media": depth == "deep",
    }
