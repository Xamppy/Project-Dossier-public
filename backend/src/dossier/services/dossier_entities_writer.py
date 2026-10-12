"""Persiste en tablas relacionales las alertas de riesgo e ideas de conversación
del ``DossierExecutivePayload`` (S4.6).

``dossier_alerts`` tiene modelo ORM (S4.5); ``dossier_ice_breakers`` no, así que
se escribe con SQL directo. El payload completo ya vive en
``dossiers.dossier_data["executive_payload"]`` (S4.3): estas filas son un
índice relacional para consultas puntuales, no la fuente de verdad, así que
``ConversationStarter.topic`` y ``.rationale`` no se duplican aquí, solo
``suggested_opener`` (única columna de texto libre que ofrece la tabla,
``content``).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from dossier.db.models import DossierAlert


def _filas_de_alertas(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Mapea cada ``RiskAlert`` a las columnas de ``dossier_alerts``."""
    return [
        {
            "level": alerta["severity"],
            "title": alerta.get("title"),
            "message": alerta["description"],
            "sources": alerta.get("sources") or [],
        }
        for alerta in payload.get("risk_alerts") or []
    ]


def _filas_de_ice_breakers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Mapea cada ``ConversationStarter`` a las columnas de ``dossier_ice_breakers``."""
    return [
        {"content": starter["suggested_opener"], "sort_order": orden}
        for orden, starter in enumerate(payload.get("conversation_starters") or [])
    ]


def escribir_entidades_ejecutivas(
    db: Session,
    *,
    dossier_id: uuid.UUID,
    payload: dict[str, Any] | None,
    reemplazo: bool,
) -> None:
    """Sincroniza ``dossier_alerts`` y ``dossier_ice_breakers`` con el payload ejecutivo.

    Se llama antes del ``commit`` del dossier, para quedar en la misma
    transacción. Si ``reemplazo`` es True (se está sustituyendo un dossier
    previo) borra antes las filas existentes de ese dossier, así no se
    duplican al regenerar. Si ``payload`` no trae datos (respaldo Markdown sin
    contrato estructurado) no inserta filas nuevas.
    """
    if reemplazo:
        db.query(DossierAlert).filter(DossierAlert.dossier_id == dossier_id).delete()
        db.execute(
            text("DELETE FROM dossier_ice_breakers WHERE dossier_id = :id"),
            {"id": dossier_id},
        )
    if not payload:
        return

    for fila in _filas_de_alertas(payload):
        db.add(DossierAlert(dossier_id=dossier_id, **fila))

    # ``dossier_ice_breakers`` no tiene modelo ORM: el INSERT es SQL directo, así
    # que necesita el dossier (y las alertas) ya volcados con flush explícito;
    # el autoflush de la sesión no cubre statements de texto plano.
    db.flush()
    for fila in _filas_de_ice_breakers(payload):
        db.execute(
            text(
                "INSERT INTO dossier_ice_breakers (dossier_id, content, sort_order) "
                "VALUES (:dossier_id, :content, :sort_order)"
            ),
            {"dossier_id": dossier_id, **fila},
        )
