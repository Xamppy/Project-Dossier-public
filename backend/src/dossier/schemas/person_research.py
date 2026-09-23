"""Solicitud para informe de persona (PDL + IA o solo búsqueda web)."""
from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PersonResearchSource(StrEnum):
    """Origen de la investigación (elige uno en cada petición)."""

    gemini_web = "gemini_web"
    pdl = "pdl"


class PersonResearchRequest(BaseModel):
    """Filtros para investigación de persona."""

    full_name: str = Field(..., min_length=2, max_length=200, description="Nombre completo")
    job_area: str | None = Field(
        None,
        max_length=200,
        description="Área o cargo (contexto para PDL y el informe)",
    )
    company: str | None = Field(None, max_length=200)
    country: str | None = Field(None, max_length=120, description="País / región")
    city: str | None = Field(None, max_length=120, description="Opcional; se usa como contexto geo")
    extra_keywords: str | None = Field(
        None,
        max_length=400,
        description="Palabras clave adicionales (escuela, sector, etc.)",
    )
    email: str | None = Field(
        None,
        max_length=255,
        description="Email del contacto (PDL person/enrich)",
    )
    linkedin_url: str | None = Field(
        None,
        max_length=500,
        description="URL LinkedIn (PDL profile)",
    )
    start: int = Field(0, ge=0, le=10_000)
    max_profiles: int = Field(1, ge=1, le=5, description="Cuántos perfiles PDL usar en el análisis")
    reveal_contact_details: bool = Field(
        False,
        description="Reservado (PDL incluye contacto en el match). Ignorado.",
    )
    output_language: str | None = Field(
        default=None,
        max_length=16,
        description="Idioma del informe (es, en, pt, …). Desde Configuración → Idioma de salida.",
    )
    include_posts: bool = Field(
        False,
        description="Reservado; PDL no expone publicaciones en este flujo.",
    )
    research_source: PersonResearchSource = Field(
        default=PersonResearchSource.pdl,
        description="pdl (por defecto) | gemini_web (solo IA)",
    )
    async_mode: bool = Field(
        False,
        description="Si true, encola la generación y responde con job_id (no bloquea la petición).",
    )
    force_refresh: bool = Field(
        False,
        description="Si true, ejecuta una investigación nueva sin reutilizar un informe previo en caché.",
    )
    replace_dossier_id: UUID | None = Field(
        None,
        description="Si se indica, actualiza este dossier existente (misma carpeta de reunión).",
    )

    @field_validator("replace_dossier_id", mode="before")
    @classmethod
    def _coerce_replace_id(cls, v: object) -> UUID | None:
        if v is None or v == "":
            return None
        if isinstance(v, UUID):
            return v
        return UUID(str(v).strip())

    @field_validator("email", "linkedin_url", mode="before")
    @classmethod
    def _strip_optional_contact_ids(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        return str(v).strip() or None

    @field_validator("research_source", mode="before")
    @classmethod
    def _coerce_legacy_sources(cls, v: object) -> object:
        if v in ("netrows", "apollo", "lusha"):
            return "pdl"
        return v
