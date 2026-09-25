"""Tests - S4.1: esquema JSON estricto del dossier ejecutivo (specs/proposals/S0.9).

Cubre las cuatro CA de la especificacion aprobada. No incluye el ajuste del
prompt de sintesis (S4.2) ni el cambio de columnas en Postgres (S4.5): solo el
contrato Pydantic y la lectura compatible con dossiers historicos en Markdown.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from dossier.schemas.corporate_registry import JurisdiccionRegistro, RegistroCorporativo
from dossier.schemas.dossier_executive_payload import (
    CareerPosition,
    ConversationStarter,
    CorporateRecordCitation,
    DossierExecutivePayload,
    LegacyMarkdownDossier,
    PressMention,
    RiskAlert,
    RiskSeverity,
    SourceCitation,
    SourceType,
    parse_dossier_payload,
)


def _cita(**overrides) -> SourceCitation:
    base = dict(
        source_type=SourceType.companies_house,
        source_name="Companies House",
        retrieved_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return SourceCitation(**base)


def _registro() -> RegistroCorporativo:
    return RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.uk,
        fuente="companies_house",
        identificador_registro="01234567",
        razon_social="Acme Ltd",
    )


def _payload_completo(**overrides) -> dict:
    base = dict(
        meeting_context={"tema": "Renovación de contrato"},
        executive_summary="Resumen ejecutivo con más de veinte caracteres.",
        participants=[{"nombre": "Jane Doe"}],
        corporate_records=[CorporateRecordCitation(record=_registro(), source=_cita())],
        career_trajectory=[
            CareerPosition(role_title="CFO", company_name="Acme Ltd", is_current=True)
        ],
        press_mentions=[
            PressMention(
                headline="Acme cierra ronda de inversión",
                publisher="Reuters",
                summary="Resumen de la noticia.",
                url="https://reuters.com/acme",
                source=_cita(source_type=SourceType.gdelt_news, source_name="GDELT"),
            )
        ],
        risk_alerts=[
            RiskAlert(
                title="Litigio pendiente",
                severity=RiskSeverity.medium,
                description="Descripción del riesgo.",
                sources=[_cita()],
            )
        ],
        conversation_starters=[
            ConversationStarter(
                topic="Expansión europea",
                rationale="Mencionada en la última memoria anual.",
                suggested_opener="¿Cómo va la apertura de la oficina en Berlín?",
            )
        ],
        data_sources_used=[_cita()],
    )
    base.update(overrides)
    return base


def test_ca1_payload_completo_valida_sin_errores():
    payload = DossierExecutivePayload(**_payload_completo())
    assert payload.schema_version == "2.0.0"
    assert payload.corporate_records[0].record.razon_social == "Acme Ltd"


def test_ca2_falta_executive_summary_lanza_validation_error():
    datos = _payload_completo()
    del datos["executive_summary"]
    with pytest.raises(ValidationError, match="executive_summary"):
        DossierExecutivePayload(**datos)


def test_ca2_falta_conversation_starters_lanza_validation_error():
    datos = _payload_completo()
    del datos["conversation_starters"]
    with pytest.raises(ValidationError, match="conversation_starters"):
        DossierExecutivePayload(**datos)


def test_conversation_starters_maximo_tres():
    datos = _payload_completo()
    uno = datos["conversation_starters"][0]
    datos["conversation_starters"] = [uno, uno, uno, uno]
    with pytest.raises(ValidationError):
        DossierExecutivePayload(**datos)


def test_cero_risk_alerts_es_valido():
    datos = _payload_completo(risk_alerts=[])
    payload = DossierExecutivePayload(**datos)
    assert payload.risk_alerts == []


def test_ca3_press_mention_sin_source_falla():
    with pytest.raises(ValidationError, match="source"):
        PressMention(
            headline="Titular",
            publisher="Reuters",
            summary="Resumen.",
            url="https://reuters.com/x",
        )


def test_ca3_corporate_record_sin_source_falla():
    with pytest.raises(ValidationError, match="source"):
        CorporateRecordCitation(record=_registro())


def test_ca4_dossier_historico_markdown_se_normaliza_sin_error():
    legado = {"format": "markdown", "body": "# Informe\n\nTexto.", "billing": "charged"}
    resultado = parse_dossier_payload(legado)
    assert isinstance(resultado, LegacyMarkdownDossier)
    assert resultado.body.startswith("# Informe")


def test_parse_dossier_payload_reconoce_esquema_nuevo():
    resultado = parse_dossier_payload(_payload_completo())
    assert isinstance(resultado, DossierExecutivePayload)
