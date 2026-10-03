"""
Identidad de reuniones y hechos de generación (UX-KPI-01). Módulo hoja, sin dependencias del
resto de servicios, para que lo compartan la persistencia de dossiers, la evidencia y el
cálculo de indicadores sin importaciones circulares.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

ORIGEN_MANUAL = "manual"
ORIGEN_AUTOMATICO = "automatic"

ROL_CORPORATIVO = "corporate"


def role_for_person(index: int | None) -> str:
    return f"person:{index if index else 1}"


def meeting_key(provider: str, external_event_id: str, calendar_key: str = "primary") -> str:
    """Identidad de una ocurrencia: el mismo id en otro proveedor o calendario no se mezcla."""
    return f"{provider}|{calendar_key}|{external_event_id}"


def parse_start(valor: Any) -> datetime | None:
    """Instante UTC de un inicio RFC3339 con offset; ``None`` si falta hora u offset."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    s = valor.strip()
    if "T" not in s:
        return None
    if s[-1] in "zZ":
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(UTC)


def expected_roles_from_parsed(parsed: dict[str, Any], *, include_corporate: bool) -> frozenset[str]:
    """Roles que produce la solicitud ya analizada: empresa (si el plan la incluye) y contactos."""
    roles: set[str] = set()
    if include_corporate and parsed.get("company_corporate"):
        roles.add(ROL_CORPORATIVO)
    for posicion, persona in enumerate(parsed.get("persons") or [], start=1):
        if len((persona.get("full_name") or "").strip()) >= 2:
            roles.add(role_for_person(persona.get("index") or posicion))
    return frozenset(roles)


def resolve_generation_origin(
    explicit: str | None,
    *,
    trigger_source: str | None,
    calendar_event_id: object | None,
) -> str | None:
    """Origen demostrable de una generación; ``None`` si no se puede afirmar quién la inició."""
    if explicit in (ORIGEN_MANUAL, ORIGEN_AUTOMATICO):
        return explicit
    if trigger_source == "manual":
        return ORIGEN_MANUAL
    if trigger_source == "calendar" and calendar_event_id is not None:
        return ORIGEN_AUTOMATICO
    return None


@dataclass(frozen=True)
class Fact:
    """Un resultado exitoso de generación. Sin cuerpos, nombres ni correos."""

    result_key: str
    meeting_key: str
    role_key: str
    origin: str
    completed_at: datetime
    meeting_starts_at: datetime | None
    expected_keys: frozenset[str] | None
    deleted_at: datetime | None
