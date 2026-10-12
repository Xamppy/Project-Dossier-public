"""Adaptador aditivo: submissions de SEC EDGAR al modelo comun (S1.9/S2.3).

Convierte el JSON crudo de ``submissions/CIK{n}.json`` (el mismo que consume
``services/corporate_registry_context.py`` y que ``sec_edgar/cli.py`` obtiene con
``fetch_json``) a ``RegistroCorporativo`` + ``CorporateRecordCitation``. No reemplaza
ninguna funcion existente: es una funcion pura nueva sobre el mismo JSON.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dossier.schemas.corporate_registry import JurisdiccionRegistro, Presentacion, RegistroCorporativo
from dossier.schemas.dossier_executive_payload import (
    CorporateRecordCitation,
    SourceCitation,
    SourceType,
)


def _cik_normalizado(cik: str | int | None) -> str:
    solo_digitos = "".join(c for c in str(cik or "") if c.isdigit())
    return solo_digitos.zfill(10) if solo_digitos else ""


def _url_publica_edgar(cik_normalizado: str) -> str | None:
    if not cik_normalizado:
        return None
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_normalizado}&type=10-K"


def _indice_filing_publico(cik_normalizado: str, accession: str) -> str | None:
    accession = str(accession or "").strip()
    if not cik_normalizado or not accession:
        return None
    accession_sin_guiones = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik_normalizado)}/"
        f"{accession_sin_guiones}/{accession}-index.htm"
    )


def _presentaciones_desde_submissions(
    data: dict[str, Any], cik_normalizado: str
) -> list[Presentacion]:
    recientes = ((data.get("filings") or {}).get("recent")) or {}
    formularios = recientes.get("form") or []
    fechas = recientes.get("filingDate") or []
    accesiones = recientes.get("accessionNumber") or []
    n = min(len(formularios), len(fechas), len(accesiones))
    return [
        Presentacion(
            fecha=fechas[i],
            tipo=formularios[i],
            url=_indice_filing_publico(cik_normalizado, accesiones[i]),
        )
        for i in range(n)
    ]


def submissions_a_registro_corporativo(
    data: dict[str, Any],
    cik: str,
    *,
    consultado_en: datetime | None = None,
) -> CorporateRecordCitation:
    """Convierte submissions (``CIK{n}.json``) de SEC EDGAR a ``RegistroCorporativo``.

    ``estado``, ``forma_juridica``, ``fecha_constitucion`` y ``domicilio`` quedan en
    ``None``: SEC EDGAR no entrega un equivalente directo (ver tabla de mapeo de S1.9).
    Datos incompletos (sin bloque ``filings``, submissions vacio) se aceptan sin lanzar
    excepcion.
    """
    momento = consultado_en or datetime.now(UTC)
    cik_normalizado = _cik_normalizado(data.get("cik") or cik)
    sic = data.get("sic")
    url_fuente = _url_publica_edgar(cik_normalizado)

    registro = RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.us,
        fuente="sec_edgar",
        identificador_registro=cik_normalizado,
        razon_social=str(data.get("name") or ""),
        codigos_actividad=[str(sic)] if sic else [],
        presentaciones=_presentaciones_desde_submissions(data, cik_normalizado),
        url_fuente=url_fuente,
        consultado_en=momento,
        datos_brutos=dict(data) if data else None,
    )
    return CorporateRecordCitation(
        record=registro,
        source=SourceCitation(
            source_type=SourceType.sec_edgar,
            source_name="SEC EDGAR",
            url=url_fuente,
            retrieved_at=momento,
            record_id=cik_normalizado or None,
        ),
    )
