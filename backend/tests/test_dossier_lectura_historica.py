"""Tests - S4.4: compatibilidad de lectura para dossiers historicos en Markdown.

Cubre la lectura de ``dossier_data`` en sus tres formas reales (decision de S4.3,
docs/architecture/estrategia-migracion-modelo-datos.md §3):

1. Nuevo: ``{"format": "markdown", "body": "...", "executive_payload": {...}}``.
2. Historico: ``{"format": "markdown", "body": "..."}`` (sin ``executive_payload``).
3. Cualquier variante corrupta o ausente: nunca debe lanzar error de lectura (CA4).

No repite las pruebas de S4.1 (contrato Pydantic estricto); solo la funcion de lectura
y el resumen aditivo que consume la API (``resumen_contenido_dossier``).
"""
from __future__ import annotations

from datetime import UTC, datetime

from dossier.schemas.dossier_executive_payload import (
    ConversationStarter,
    DossierExecutivePayload,
    LegacyMarkdownDossier,
    SourceCitation,
    SourceType,
    parse_dossier_payload,
    resumen_contenido_dossier,
)


def _payload_minimo() -> dict:
    return {
        "meeting_context": {"tema": "Seguimiento trimestral"},
        "executive_summary": "Resumen ejecutivo con más de veinte caracteres.",
        "participants": [{"nombre": "Jane Doe"}],
        "conversation_starters": [
            ConversationStarter(
                topic="Expansión europea",
                rationale="Mencionada en la última memoria anual.",
                suggested_opener="¿Cómo va Berlín?",
            ).model_dump(mode="json")
        ],
        "data_sources_used": [
            SourceCitation(
                source_type=SourceType.companies_house,
                source_name="Companies House",
                retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
            ).model_dump(mode="json")
        ],
    }


def test_nuevo_formato_con_executive_payload_valido_se_reconoce_estructurado():
    dossier_data = {
        "format": "markdown",
        "body": "# Informe\n\nTexto derivado del payload.",
        "executive_payload": _payload_minimo(),
    }
    resultado = parse_dossier_payload(dossier_data)
    assert isinstance(resultado, DossierExecutivePayload)
    assert resultado.executive_summary.startswith("Resumen ejecutivo")


def test_historico_sin_executive_payload_se_normaliza_como_legado():
    dossier_data = {"format": "markdown", "body": "# Informe histórico\n\nSin JSON."}
    resultado = parse_dossier_payload(dossier_data)
    assert isinstance(resultado, LegacyMarkdownDossier)
    assert resultado.body.startswith("# Informe histórico")


def test_executive_payload_corrupto_cae_a_legado_sin_lanzar_error():
    dossier_data = {
        "format": "markdown",
        "body": "# Informe\n\nTexto de respaldo.",
        "executive_payload": {"esto": "no es un DossierExecutivePayload"},
    }
    resultado = parse_dossier_payload(dossier_data)
    assert isinstance(resultado, LegacyMarkdownDossier)
    assert resultado.body.startswith("# Informe")


def test_dossier_data_none_no_lanza_error():
    resultado = parse_dossier_payload(None)
    assert isinstance(resultado, LegacyMarkdownDossier)
    assert resultado.body == ""


def test_dossier_data_sin_format_ni_body_no_lanza_error():
    resultado = parse_dossier_payload({"algo": "irrelevante"})
    assert isinstance(resultado, LegacyMarkdownDossier)


def test_resumen_contenido_dossier_estructurado():
    dossier_data = {
        "format": "markdown",
        "body": "# Informe",
        "executive_payload": _payload_minimo(),
    }
    resumen = resumen_contenido_dossier(dossier_data)
    assert resumen["content_kind"] == "structured"
    assert resumen["executive_payload"]["executive_summary"].startswith("Resumen ejecutivo")


def test_resumen_contenido_dossier_legado():
    resumen = resumen_contenido_dossier({"format": "markdown", "body": "# Informe"})
    assert resumen["content_kind"] == "legacy_markdown"
    assert resumen["executive_payload"] is None


def test_resumen_contenido_dossier_data_none():
    resumen = resumen_contenido_dossier(None)
    assert resumen["content_kind"] == "legacy_markdown"
    assert resumen["executive_payload"] is None
