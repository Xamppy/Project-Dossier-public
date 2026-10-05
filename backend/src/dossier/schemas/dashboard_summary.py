"""Contrato de ``GET /dashboard/summary`` (UX-KPI-01). Sin datos personales ni listas de detalle."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetricState = Literal["ok", "empty", "partial", "unavailable", "not_connected"]


class MetricContext(BaseModel):
    state: MetricState
    #: código estable que el frontend traduce; ``None`` cuando todo está bien
    reason: str | None = None
    #: la evidencia es fiable desde aquí (ISO 8601 UTC)
    measured_from: str | None = None
    measured_to: str | None = None


class UpcomingMetrics(MetricContext):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    eligible_meetings: int | None = None
    prepared_meetings: int | None = None
    pending_meetings: int | None = None
    coverage_percent: float | None = None


class PreparationCostMetrics(MetricContext):
    """Créditos estimados para generar lo que falta en las reuniones de los próximos 7 días."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    estimated_credits: int | None = None
    meetings_to_generate: int | None = None
    #: charged = se cobra; unlimited = Enterprise sin bloqueo; disabled = cobro desactivado
    billing: Literal["charged", "unlimited", "disabled"]
    exceeds_balance: bool | None = None


class CreditsMetrics(MetricContext):
    balance: int | None = None
    monthly_limit: int | None = None


class DashboardSummary(BaseModel):
    as_of: str
    timezone: str
    upcoming: UpcomingMetrics
    preparation_cost: PreparationCostMetrics
    credits: CreditsMetrics
