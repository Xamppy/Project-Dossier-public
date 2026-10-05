"""Tests — S4.7: exigir origen y fecha de consulta real en toda afirmación estructurada.

Cubre la función pura ``normalizar_procedencia_fuentes``: sustituye citas
inventadas por el LLM por las fuentes que el pipeline consultó de verdad, y
descarta afirmaciones cuya única cita no corresponde a ninguna fuente
consultada.
"""
from __future__ import annotations

from datetime import UTC, datetime

from dossier.schemas.corporate_registry import JurisdiccionRegistro, RegistroCorporativo
from dossier.schemas.dossier_executive_payload import (
    CareerPosition,
    CorporateRecordCitation,
    DossierExecutivePayload,
    PressMention,
    RiskAlert,
    RiskSeverity,
    SourceCitation,
    SourceType,
)
from dossier.services.source_provenance import normalizar_procedencia_fuentes

RETRIEVED_REAL = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
RETRIEVED_INVENTADO = datetime(2019, 1, 1, tzinfo=UTC)


def _cita_pdl_real() -> SourceCitation:
    return SourceCitation(
        source_type=SourceType.pdl,
        source_name="People Data Labs",
        retrieved_at=RETRIEVED_REAL,
    )


def _cita_inventada(**overrides) -> SourceCitation:
    base = {
        "source_type": SourceType.gdelt_news,
        "source_name": "Datos proporcionados",
        "url": None,
        "retrieved_at": RETRIEVED_INVENTADO,
    }
    base.update(overrides)
    return SourceCitation(**base)


def _registro() -> RegistroCorporativo:
    return RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.uk,
        fuente="companies_house",
        identificador_registro="01234567",
        razon_social="Acme Ltd",
    )


def _payload_minimo(**overrides) -> DossierExecutivePayload:
    base = {
        "meeting_context": {"tema": "Renovación de contrato"},
        "executive_summary": "Resumen ejecutivo con más de veinte caracteres.",
        "participants": [{"nombre": "Jane Doe"}],
        "conversation_starters": [],
    }
    base.update(overrides)
    return DossierExecutivePayload(**base)


def test_normal_reemplaza_cita_generica_por_la_fuente_realmente_consultada():
    """Caso normal: la cita del LLM apunta al tipo correcto pero con nombre/fecha inventados."""
    payload = _payload_minimo(
        risk_alerts=[
            RiskAlert(
                title="Litigio pendiente",
                severity=RiskSeverity.medium,
                description="Descripción del riesgo.",
                sources=[_cita_inventada(source_type=SourceType.pdl, url="https://pdl.example/1")],
            )
        ],
    )
    fuentes_reales = [_cita_pdl_real()]

    resultado = normalizar_procedencia_fuentes(payload, fuentes_reales)

    cita = resultado.risk_alerts[0].sources[0]
    assert cita.source_name == "People Data Labs"
    assert cita.retrieved_at == RETRIEVED_REAL
    # La URL específica que aportó el LLM se conserva porque el tipo sí se consultó.
    assert cita.url == "https://pdl.example/1"


def test_normal_descarta_alerta_cuya_fuente_no_fue_consultada():
    """Una alerta que cita prensa cuando no se consultó ningún proveedor de noticias se descarta."""
    payload = _payload_minimo(
        risk_alerts=[
            RiskAlert(
                title="Litigio pendiente",
                severity=RiskSeverity.medium,
                description="Descripción del riesgo.",
                sources=[_cita_inventada()],  # gdelt_news, no consultado
            )
        ],
    )
    fuentes_reales = [_cita_pdl_real()]

    resultado = normalizar_procedencia_fuentes(payload, fuentes_reales)

    assert resultado.risk_alerts == []


def test_normal_completa_career_trajectory_sin_source_con_la_cita_pdl():
    payload = _payload_minimo(
        career_trajectory=[
            CareerPosition(role_title="CFO", company_name="Acme Ltd", is_current=True, source=None)
        ],
    )
    fuentes_reales = [_cita_pdl_real()]

    resultado = normalizar_procedencia_fuentes(payload, fuentes_reales)

    assert resultado.career_trajectory[0].source == _cita_pdl_real()


def test_normal_data_sources_used_queda_fijo_a_las_fuentes_reales():
    payload = _payload_minimo(
        data_sources_used=[_cita_inventada()],
    )
    fuentes_reales = [_cita_pdl_real()]

    resultado = normalizar_procedencia_fuentes(payload, fuentes_reales)

    assert resultado.data_sources_used == fuentes_reales


def test_borde_sin_fuentes_consultadas_descarta_todas_las_afirmaciones_con_cita_unica():
    payload = _payload_minimo(
        press_mentions=[
            PressMention(
                headline="Titular",
                publisher="Reuters",
                summary="Resumen.",
                url="https://reuters.com/x",
                source=_cita_inventada(),
            )
        ],
        corporate_records=[CorporateRecordCitation(record=_registro(), source=_cita_inventada())],
        career_trajectory=[CareerPosition(role_title="CFO", company_name="Acme Ltd", source=None)],
        data_sources_used=[_cita_inventada()],
    )

    resultado = normalizar_procedencia_fuentes(payload, [])

    assert resultado.press_mentions == []
    assert resultado.corporate_records == []
    assert resultado.career_trajectory[0].source is None
    assert resultado.data_sources_used == []


def test_borde_alerta_con_una_fuente_valida_y_una_invalida_conserva_solo_la_valida():
    payload = _payload_minimo(
        risk_alerts=[
            RiskAlert(
                title="Litigio pendiente",
                severity=RiskSeverity.high,
                description="Descripción del riesgo.",
                sources=[
                    _cita_inventada(source_type=SourceType.pdl),  # tipo consultado
                    _cita_inventada(source_type=SourceType.sec_edgar),  # no consultado
                ],
            )
        ],
    )
    fuentes_reales = [_cita_pdl_real()]

    resultado = normalizar_procedencia_fuentes(payload, fuentes_reales)

    assert len(resultado.risk_alerts) == 1
    assert len(resultado.risk_alerts[0].sources) == 1
    assert resultado.risk_alerts[0].sources[0].source_type == SourceType.pdl


def test_error_fuentes_consultadas_con_tipo_duplicado_usa_la_primera_sin_lanzar():
    """Dos citas reales del mismo tipo (posible bug de quien las construye): gana la primera."""
    payload = _payload_minimo(
        career_trajectory=[CareerPosition(role_title="CFO", company_name="Acme Ltd", source=None)],
    )
    primera = _cita_pdl_real()
    segunda = SourceCitation(
        source_type=SourceType.pdl,
        source_name="People Data Labs (duplicado)",
        retrieved_at=RETRIEVED_INVENTADO,
    )

    resultado = normalizar_procedencia_fuentes(payload, [primera, segunda])

    assert resultado.career_trajectory[0].source == primera
