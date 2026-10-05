"""S4.3: el Markdown del dossier se genera por código desde el payload validado.

Así el dashboard (que lee ``dossier_data.body``) no cambia y no hace falta una
segunda llamada al LLM para producir el informe legible.
"""
from __future__ import annotations

from datetime import UTC, datetime

from dossier.schemas.dossier_executive_payload import (
    CareerPosition,
    ConfidenceAssessment,
    ConversationStarter,
    DossierExecutivePayload,
    FinalRecommendation,
    OverallRiskLevel,
    PressMention,
    RecommendationDecision,
    RiskAlert,
    RiskSeverity,
    SourceCitation,
    SourceType,
)
from dossier.services.executive_markdown import render_executive_markdown


def _cita(url: str | None = "https://example.test/fuente") -> SourceCitation:
    return SourceCitation(
        source_type=SourceType.pdl,
        source_name="People Data Labs",
        url=url,
        retrieved_at=datetime(2026, 9, 26, 12, 0, tzinfo=UTC),
    )


def _payload(**overrides) -> DossierExecutivePayload:
    base = {
        "meeting_context": {"title": "Revisión trimestral"},
        "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
        "participants": [{"name": "Ana Prueba"}],
        "career_trajectory": [
            CareerPosition(
                role_title="Gerente general",
                company_name="Empresa de Prueba SA",
                start_date="2019",
                is_current=True,
                source=_cita(),
            )
        ],
        "risk_alerts": [
            RiskAlert(
                title="Litigio abierto",
                severity=RiskSeverity.high,
                description="Demanda vigente.",
                sources=[_cita()],
            )
        ],
        "press_mentions": [
            PressMention(
                headline="La empresa anuncia fusión",
                publisher="Diario de Prueba",
                published_date="2026-09-01",
                summary="Resumen breve.",
                url="https://example.test/nota",
                source=_cita(),
            )
        ],
        "conversation_starters": [
            ConversationStarter(
                topic="Expansión",
                rationale="Mencionada en su perfil.",
                suggested_opener="¿Cómo va la expansión?",
            )
        ],
        "data_sources_used": [_cita()],
    }
    base.update(overrides)
    return DossierExecutivePayload(**base)


# Caso normal: cada sección con datos aparece con su contenido.
def test_renderiza_todas_las_secciones_con_datos():
    md = render_executive_markdown(_payload(), "es")

    for fragmento in (
        "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
        "Gerente general",
        "Empresa de Prueba SA",
        "2019",
        "Litigio abierto",
        "La empresa anuncia fusión",
        "[Diario de Prueba](https://example.test/nota)",
        "¿Cómo va la expansión?",
        "People Data Labs",
    ):
        assert fragmento in md, fragmento
    assert md.startswith("## ")


# Borde: secciones vacías no dejan títulos huérfanos.
def test_omite_las_secciones_sin_datos():
    md = render_executive_markdown(
        _payload(risk_alerts=[], press_mentions=[], career_trajectory=[], conversation_starters=[]),
        "es",
    )

    assert md.count("## ") == 2  # resumen y fuentes
    assert "None" not in md


def test_titulos_en_el_idioma_de_salida():
    es = render_executive_markdown(_payload(), "es")
    en = render_executive_markdown(_payload(), "en")

    assert "## Resumen ejecutivo" in es
    assert "## Executive summary" in en
    assert "Resumen ejecutivo" not in en


# Error típico: idioma no soportado o vacío no rompe el render.
def test_idioma_desconocido_usa_espanol():
    assert "## Resumen ejecutivo" in render_executive_markdown(_payload(), "xx")


def test_fuente_sin_url_se_muestra_sin_enlace_roto():
    md = render_executive_markdown(_payload(data_sources_used=[_cita(url=None)]), "es")

    assert "People Data Labs" in md
    assert "]()" not in md and "(None)" not in md


def _con_cierre(**overrides) -> DossierExecutivePayload:
    return _payload(
        final_recommendation=FinalRecommendation(
            key_findings=["Cargo actual confirmado por PDL."],
            overall_risk=OverallRiskLevel.medium,
            decision=RecommendationDecision.proceed_with_caution,
            next_steps=["Verificar el litigio en el registro judicial."],
        ),
        confidence_assessment=ConfidenceAssessment(
            high_confidence=["Cargo y empresa actuales (PDL)."],
            low_confidence=["Comentarios en redes sociales."],
            inferences=["Interés en proveedores locales."],
        ),
        **overrides,
    )


def test_renderiza_la_recomendacion_final_y_el_nivel_de_confianza():
    md = render_executive_markdown(_con_cierre(), "es")

    for fragmento in (
        "## Conclusión y recomendación",
        "Proceder con cautela",
        "Riesgo global: medio",
        "Cargo actual confirmado por PDL.",
        "Verificar el litigio en el registro judicial.",
        "## Nivel de confianza",
        "Cargo y empresa actuales (PDL).",
        "Comentarios en redes sociales.",
        "Interés en proveedores locales.",
    ):
        assert fragmento in md, fragmento
    assert md.index("## Conclusión y recomendación") < md.index("## Fuentes consultadas")
    assert "Confianza media" not in md  # niveles vacíos no se listan


def test_recomendacion_y_confianza_en_el_idioma_de_salida():
    md = render_executive_markdown(_con_cierre(), "en")

    assert "## Conclusion and recommendation" in md
    assert "Proceed with caution" in md
    assert "## Confidence level" in md
    assert "Proceder" not in md
