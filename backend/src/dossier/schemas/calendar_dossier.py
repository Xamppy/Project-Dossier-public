"""Cuerpo para generar dossiers desde calendario (evita IDs largos en query GET)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CalendarGenerarDossiersBody(BaseModel):
    event_id: str | None = Field(None, description="Id del evento en el proveedor")
    reunion: dict[str, Any] | None = Field(
        None,
        description="Evento ya normalizado (desde listado); evita re-fetch por id en Outlook",
    )
    top: int | None = Field(None, ge=1, le=10, description="Máximo de eventos si no hay event_id")
    async_mode: bool = Field(
        True,
        description="Si true, encola la generación y responde de inmediato con job_id",
    )
    depth: str | None = Field(
        "standard",
        description="Profundidad corporativa (basic=1, standard=3, deep=5 créditos)",
    )
    output_language: str | None = Field(
        None,
        description="Código de idioma de salida (es, en, …). Si se omite, usa locale de cuenta.",
    )
