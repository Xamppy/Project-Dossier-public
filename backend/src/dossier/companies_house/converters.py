"""Adaptador aditivo: perfil y filing history de Companies House al modelo comun (S1.9/S2.3).

Convierte el JSON crudo que ya devuelven ``get_company_profile``/``get_filing_history``
(``companies_house/cli.py``) a ``RegistroCorporativo`` + ``CorporateRecordCitation``. No
reemplaza esas funciones ni cambia lo que ya consume ``services/corporate_registry_context.py``:
es una funcion pura nueva sobre el mismo JSON, para quien quiera el modelo comun ademas
del Markdown/JSON crudo actual.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dossier.schemas.corporate_registry import (
    DomicilioRegistrado,
    JurisdiccionRegistro,
    Presentacion,
    RegistroCorporativo,
)
from dossier.schemas.dossier_executive_payload import (
    CorporateRecordCitation,
    SourceCitation,
    SourceType,
)

_WEB_PERFIL_BASE = "https://find-and-update.company-information.service.gov.uk"


def _domicilio_desde_perfil(direccion: dict[str, Any] | None) -> DomicilioRegistrado | None:
    if not direccion:
        return None
    calle = ", ".join(
        p
        for p in (
            direccion.get("premises"),
            direccion.get("address_line_1"),
            direccion.get("address_line_2"),
        )
        if p
    ) or None
    return DomicilioRegistrado(
        calle=calle,
        localidad=direccion.get("locality"),
        region=direccion.get("region"),
        codigo_postal=direccion.get("postal_code"),
        pais=direccion.get("country"),
    )


def _presentaciones_desde_filing_history(filing_history: dict[str, Any] | None) -> list[Presentacion]:
    items = (filing_history or {}).get("items") or []
    return [
        Presentacion(fecha=item.get("date"), tipo=item.get("type"), descripcion=item.get("description"))
        for item in items
        if isinstance(item, dict)
    ]


def _url_publica_perfil(perfil: dict[str, Any], numero: str) -> str | None:
    self_link = (perfil.get("links") or {}).get("self")
    if self_link:
        return f"{_WEB_PERFIL_BASE}{self_link}"
    if numero:
        return f"{_WEB_PERFIL_BASE}/company/{numero}"
    return None


def perfil_a_registro_corporativo(
    profile: dict[str, Any],
    filing_history: dict[str, Any] | None = None,
    *,
    company_number: str | None = None,
    consultado_en: datetime | None = None,
) -> CorporateRecordCitation:
    """Convierte perfil (+ filing history) de Companies House a ``RegistroCorporativo``.

    ``directivos`` queda vacio: Companies House requiere el endpoint ``/officers`` aparte
    y hoy no se consulta (ver tabla de mapeo de S1.9). Datos incompletos (sin domicilio,
    sin fecha de constitucion, perfil vacio) se aceptan sin lanzar excepcion, porque todos
    los campos salvo los cuatro obligatorios de ``RegistroCorporativo`` tienen default.
    """
    numero = str(company_number or profile.get("company_number") or "").strip()
    momento = consultado_en or datetime.now(UTC)
    url_fuente = _url_publica_perfil(profile, numero)

    registro = RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.uk,
        fuente="companies_house",
        identificador_registro=numero,
        razon_social=str(profile.get("company_name") or ""),
        estado=profile.get("company_status"),
        forma_juridica=profile.get("type"),
        fecha_constitucion=profile.get("date_of_creation"),
        domicilio=_domicilio_desde_perfil(profile.get("registered_office_address")),
        codigos_actividad=list(profile.get("sic_codes") or []),
        directivos=[],
        presentaciones=_presentaciones_desde_filing_history(filing_history),
        url_fuente=url_fuente,
        consultado_en=momento,
        datos_brutos={"profile": profile, "filing_history": filing_history},
    )
    return CorporateRecordCitation(
        record=registro,
        source=SourceCitation(
            source_type=SourceType.companies_house,
            source_name="Companies House",
            url=url_fuente,
            retrieved_at=momento,
            record_id=numero or None,
        ),
    )
