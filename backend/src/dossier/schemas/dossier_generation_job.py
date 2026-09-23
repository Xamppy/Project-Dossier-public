"""Esquemas para jobs de generación asíncrona de dossiers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
CalendarJobProvider = Literal["microsoft", "google"]


class DossierGenerationJobResponse(BaseModel):
    id: str
    status: JobStatus
    job_type: str
    calendar_provider: CalendarJobProvider | None = None
    external_event_id: str | None = None
    meeting_label: str | None = None
    credits_estimated: int = 0
    credits_consumed: int = 0
    error_message: str | None = None
    result: dict[str, Any] | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class EnqueueCalendarDossierResponse(BaseModel):
    async_mode: bool = True
    job_id: str
    status: JobStatus
    meeting_label: str | None = None
    credits_estimated: int = 0
    message: str | None = None
