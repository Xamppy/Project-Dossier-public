"""Normalización de la procedencia de fuentes en el payload ejecutivo (OE5, tarea S4.7).

El LLM de síntesis inventa citas cuando no tiene una real a mano: nombres
genéricos (``"Datos proporcionados"``), ``retrieved_at`` que nunca ocurrió, o
fuentes que el pipeline nunca consultó (p. ej. cita "GDELT" cuando no se llamó
a ningún proveedor de noticias). Esta función pura no confía en nada de eso:
sustituye cada :class:`SourceCitation` del payload por la versión real que el
código capturó al consultar cada proveedor.

Decisión de diseño (documentada para quien integre S4.2/S4.3): cuando una
afirmación cita un ``source_type`` que no está entre las fuentes realmente
consultadas, no se "arregla" la cita — se descarta la afirmación completa
(``risk_alerts``, ``press_mentions``, ``corporate_records``). Dejarla con una
cita corregida sería inventar una procedencia igual que hace el LLM; es
preferible perder la afirmación a mostrar una trazabilidad falsa. La única
excepción es ``career_trajectory``: en este pipeline la trayectoria siempre
proviene de PDL, así que a falta de una cita válida se completa con la cita
PDL real (tal como pide la tarea), en vez de descartar el puesto.
"""
from __future__ import annotations

from dossier.schemas.dossier_executive_payload import (
    CareerPosition,
    CorporateRecordCitation,
    DossierExecutivePayload,
    PressMention,
    RiskAlert,
    SourceCitation,
    SourceType,
)


def _citas_reales_por_tipo(
    fuentes_consultadas: list[SourceCitation],
) -> dict[SourceType, SourceCitation]:
    """Indexa las fuentes realmente consultadas por tipo (la primera de cada tipo gana)."""
    por_tipo: dict[SourceType, SourceCitation] = {}
    for cita in fuentes_consultadas:
        por_tipo.setdefault(cita.source_type, cita)
    return por_tipo


def _reconciliar(
    original: SourceCitation | None, por_tipo: dict[SourceType, SourceCitation]
) -> SourceCitation | None:
    """Devuelve la cita real para el tipo de ``original``, o ``None`` si esa fuente no se consultó.

    Cuando el tipo coincide con una fuente consultada se descarta todo lo que
    dijo el LLM salvo la URL (más específica que la cita genérica que arma el
    código): nombre de fuente y fecha de consulta siempre son los reales.
    """
    if original is None:
        return None
    real = por_tipo.get(original.source_type)
    if real is None:
        return None
    if original.url:
        return real.model_copy(update={"url": original.url})
    return real


def normalizar_procedencia_fuentes(
    payload: DossierExecutivePayload, fuentes_consultadas: list[SourceCitation]
) -> DossierExecutivePayload:
    """Reescribe el payload para que cada cita apunte a una fuente realmente consultada."""
    por_tipo = _citas_reales_por_tipo(fuentes_consultadas)
    cita_pdl = por_tipo.get(SourceType.pdl)

    trayectoria: list[CareerPosition] = []
    for puesto in payload.career_trajectory:
        fuente = _reconciliar(puesto.source, por_tipo) or cita_pdl
        trayectoria.append(puesto.model_copy(update={"source": fuente}))

    alertas: list[RiskAlert] = []
    for alerta in payload.risk_alerts:
        fuentes_validas = [
            f for f in (_reconciliar(s, por_tipo) for s in alerta.sources) if f is not None
        ]
        if fuentes_validas:
            alertas.append(alerta.model_copy(update={"sources": fuentes_validas}))

    menciones: list[PressMention] = []
    for mencion in payload.press_mentions:
        fuente = _reconciliar(mencion.source, por_tipo)
        if fuente is not None:
            menciones.append(mencion.model_copy(update={"source": fuente}))

    registros: list[CorporateRecordCitation] = []
    for registro in payload.corporate_records:
        fuente = _reconciliar(registro.source, por_tipo)
        if fuente is not None:
            registros.append(registro.model_copy(update={"source": fuente}))

    return payload.model_copy(
        update={
            "career_trajectory": trayectoria,
            "risk_alerts": alertas,
            "press_mentions": menciones,
            "corporate_records": registros,
            "data_sources_used": list(fuentes_consultadas),
        }
    )
