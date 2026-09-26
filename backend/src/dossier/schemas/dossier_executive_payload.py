"""Esquema JSON estricto del dossier ejecutivo (ver specs/proposals/S0.9, tarea S4.1).

No ajusta el prompt de sintesis (S4.2) ni cambia columnas de Postgres (S4.5):
solo el contrato Pydantic y la lectura compatible con dossiers historicos
guardados como ``{"format": "markdown", "body": "..."}``.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from dossier.schemas.corporate_registry import RegistroCorporativo


class SourceType(StrEnum):
    companies_house = "companies_house"
    sec_edgar = "sec_edgar"
    eu_registry = "eu_registry"
    pdl = "pdl"
    gdelt_news = "gdelt_news"
    news_api = "news_api"
    calendar = "calendar"


class SourceCitation(BaseModel):
    """Trazabilidad obligatoria por afirmación estructurada (objetivo OE5)."""

    source_type: SourceType
    source_name: str = Field(description="Nombre del proveedor o registro oficial")
    url: str | None = Field(None, description="URL pública verificable del dato")
    retrieved_at: datetime = Field(description="Marca temporal UTC de la consulta")
    record_id: str | None = Field(None, description="Company Number, CIK, SIREN, etc.")


class RiskSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class RiskAlert(BaseModel):
    title: str
    severity: RiskSeverity
    description: str
    sources: list[SourceCitation]


class ConversationStarter(BaseModel):
    topic: str
    rationale: str
    suggested_opener: str


class CareerPosition(BaseModel):
    role_title: str
    company_name: str
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    source: SourceCitation | None = None


class PressMention(BaseModel):
    headline: str
    publisher: str
    published_date: str | None = None
    summary: str
    url: str
    source: SourceCitation


class OverallRiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RecommendationDecision(StrEnum):
    proceed = "proceed"
    proceed_with_caution = "proceed_with_caution"
    escalate_legal_review = "escalate_legal_review"
    do_not_proceed = "do_not_proceed"


class FinalRecommendation(BaseModel):
    """Sección 7 del informe Markdown anterior (ampliación de S0.9, 2026-09-26)."""

    key_findings: list[str] = Field(default_factory=list, max_length=5)
    overall_risk: OverallRiskLevel
    decision: RecommendationDecision
    next_steps: list[str] = Field(default_factory=list)


class ConfidenceAssessment(BaseModel):
    """Sección 8 del informe Markdown anterior: qué tan confiable es cada dato."""

    high_confidence: list[str] = Field(default_factory=list)
    medium_confidence: list[str] = Field(default_factory=list)
    low_confidence: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)


class CorporateRecordCitation(BaseModel):
    """Un RegistroCorporativo (S1.9) con su cita de origen obligatoria (CA3)."""

    record: RegistroCorporativo
    source: SourceCitation


class DossierExecutivePayload(BaseModel):
    schema_version: str = Field("2.0.0", pattern=r"^\d+\.\d+\.\d+$")
    meeting_context: dict[str, Any]
    executive_summary: str = Field(min_length=20)
    participants: list[dict[str, Any]]
    corporate_records: list[CorporateRecordCitation] = Field(default_factory=list)
    career_trajectory: list[CareerPosition] = Field(default_factory=list)
    press_mentions: list[PressMention] = Field(default_factory=list)
    risk_alerts: list[RiskAlert] = Field(default_factory=list)
    conversation_starters: list[ConversationStarter] = Field(max_length=3)
    data_sources_used: list[SourceCitation] = Field(default_factory=list)
    # Opcionales para no invalidar payloads ya guardados (CA5); la síntesis los exige (CA6).
    final_recommendation: FinalRecommendation | None = None
    confidence_assessment: ConfidenceAssessment | None = None


class LegacyMarkdownDossier(BaseModel):
    """Envoltorio histórico previo a S4.1 (``{"format": "markdown", "body": ...}``)."""

    format: str = "markdown"
    body: str


def parse_dossier_payload(data: dict[str, Any]) -> DossierExecutivePayload | LegacyMarkdownDossier:
    """Normaliza ``dossier_data`` (nuevo esquema o envoltorio histórico) sin lanzar error de formato.

    CA4: un dossier histórico en Markdown se reconoce por ``format == "markdown"``
    y se devuelve como ``LegacyMarkdownDossier`` en vez de fallar la validación.
    """
    if isinstance(data, dict) and data.get("format") == "markdown":
        return LegacyMarkdownDossier(format="markdown", body=data.get("body", ""))
    return DossierExecutivePayload(**data)
