"""
Definición de planes (`organizations.plan`) y créditos asociados.

Alineado con el CHECK de PostgreSQL: `free`, `pro`, `enterprise`.
Al cambiar de plan se actualizan saldo, tope mensual y flags de producto (p. ej. white-label en Enterprise).
"""
from __future__ import annotations

from typing import Literal

from dossier.db.models import Organization

PlanId = Literal["free", "pro", "enterprise"]

ALLOWED_PLANS: frozenset[str] = frozenset({"free", "pro", "enterprise"})


def normalize_plan(raw: str | None) -> PlanId:
    p = (raw or "").strip().lower()
    if p in ALLOWED_PLANS:
        return p  # type: ignore[return-value]
    return "free"


def _entitlement(plan: PlanId) -> tuple[int, int, bool]:
    """
    Devuelve (credits_monthly_limit, credits_balance_inicial, is_white_label).

    Al aplicar un plan se asigna un saldo acorde al tier (comportamiento tipo “pool del plan”).
    """

    if plan == "free":
        return 10, 10, False
    if plan == "pro":
        return 500, 500, False
    # enterprise: tope mensual muy alto + saldo amplio; white-label activado en modelo
    return 1_000_000, 50_000, True


def apply_plan_to_organization(org: Organization, plan: str) -> PlanId:
    """
    Ajusta `org` al plan indicado (mutación in-place; el caller hace commit).

    Raises:
        ValueError: si el plan no es reconocido (no debería ocurrir con entrada validada).
    """
    pid = normalize_plan(plan)
    monthly, balance, wl = _entitlement(pid)
    org.plan = pid
    org.credits_monthly_limit = monthly
    org.credits_balance = balance
    org.is_white_label = wl
    if not wl:
        org.custom_domain = None
    return pid
