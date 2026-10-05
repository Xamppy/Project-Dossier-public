"""
Indicadores de Resumen (UX-KPI-01): lógica pura de elegibilidad, preparación y costo estimado.

No toca la base de datos ni la red: recibe reuniones ya leídas del calendario y los dossiers
disponibles, y devuelve conteos. Así se prueba sin infraestructura y el servicio de resumen
(`dashboard_summary.py`) solo se ocupa de reunir los datos.

Reglas (spec UX-KPI-01):
- Una reunión es una *ocurrencia* identificada por proveedor + calendario + id del evento.
  Dos ocurrencias se unifican solo con el mismo iCalUID **y** el mismo instante de inicio.
- Elegible: inicio válido con offset, no de día completo, no rechazada por el usuario,
  reunión de trabajo y con algún asistente externo. Los ajustes de automatización de la
  integración no excluyen una reunión que se puede preparar a mano.
- Conjunto esperado: el que deduce el parser de generación (empresa si el plan la incluye,
  más un dossier por contacto). Vacío significa «no preparable»: nunca cuenta como preparada.
- Todos los instantes son UTC; los periodos son [inicio, fin).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from dossier.billing.credit_policy import PERSON_IDENTITY_CREDITS
from dossier.billing.entitlements import default_depth_for_plan, plan_allows_calendar_corporate_dossier
from dossier.schemas.dossier_generation import DEPTH_CREDITS
from dossier.services.calendar_event_dossiers import parse_calendar_event_for_dossiers
from dossier.services.calendar_event_filters import has_external_attendee, is_work_meeting
from dossier.services.meeting_identity import (
    ROL_CORPORATIVO,
    expected_roles_from_parsed,
    meeting_key,
    parse_start,
    role_for_person,
)

__all__ = [
    "ROL_CORPORATIVO",
    "CalendarEntry",
    "CalendarSnapshot",
    "Meeting",
    "PreparationCostResult",
    "UpcomingResult",
    "collect_meetings",
    "expected_roles",
    "meeting_key",
    "parse_start",
    "preparation_role_cost",
    "role_for_person",
    "summarize_preparation_cost",
    "summarize_upcoming",
]

PERIODO_FUTURO = timedelta(days=7)

def expected_roles(reunion: dict[str, Any], plan: str | None) -> frozenset[str]:
    """Dossiers que la solicitud de la reunión produce con el parser actual y el plan dado."""
    return expected_roles_from_parsed(
        parse_calendar_event_for_dossiers(reunion),
        include_corporate=plan_allows_calendar_corporate_dossier(plan),
    )


@dataclass(frozen=True)
class CalendarEntry:
    """Un evento leído de un calendario conectado, con lo necesario para evaluarlo."""

    provider: str
    calendar_key: str
    owner_domain: str | None
    reunion: dict[str, Any]


@dataclass(frozen=True)
class Meeting:
    """Reunión elegible. ``keys`` reúne los alias verificables (un calendario por proveedor)."""

    keys: tuple[str, ...]
    starts_at: datetime
    expected: frozenset[str]


@dataclass
class CalendarSnapshot:
    meetings: list[Meeting] = field(default_factory=list)


def _is_eligible(reunion: dict[str, Any], owner_domain: str | None) -> bool:
    if reunion.get("todo_el_dia") is True:
        return False
    if reunion.get("respuesta_usuario") == "declined":
        return False
    correos = reunion.get("correos")
    vista = dict(reunion)
    if isinstance(correos, list) and correos:
        # Graph entrega nombres en `participantes`; los dominios se juzgan con los correos reales.
        vista["participantes"] = ", ".join(str(c) for c in correos)
    if not is_work_meeting(vista)[0]:
        return False
    return has_external_attendee(vista, owner_domain)[0]


def collect_meetings(entries: list[CalendarEntry], *, plan: str | None) -> CalendarSnapshot:
    """Filtra lo elegible, calcula el conjunto esperado y unifica duplicados verificables."""
    snap = CalendarSnapshot()
    grupos: dict[tuple[str, datetime], int] = {}
    for e in entries:
        ext_id = str(e.reunion.get("id") or "").strip()
        inicio = parse_start(e.reunion.get("inicio"))
        if not ext_id or inicio is None:
            continue
        clave = meeting_key(e.provider, ext_id, e.calendar_key)
        if not _is_eligible(e.reunion, e.owner_domain):
            continue
        uid = str(e.reunion.get("ical_uid") or "").strip()
        destino = grupos.get((uid, inicio)) if uid else None
        if destino is not None:
            previo = snap.meetings[destino]
            if clave not in previo.keys:
                snap.meetings[destino] = Meeting(
                    keys=(*previo.keys, clave), starts_at=previo.starts_at, expected=previo.expected
                )
            continue
        snap.meetings.append(
            Meeting(keys=(clave,), starts_at=inicio, expected=expected_roles(e.reunion, plan))
        )
        if uid:
            grupos[(uid, inicio)] = len(snap.meetings) - 1
    return snap


def _percent(parte: int, total: int) -> float | None:
    return 100 * parte / total if total > 0 else None


@dataclass(frozen=True)
class UpcomingResult:
    eligible: int
    prepared: int
    pending: int
    percent: float | None


def summarize_upcoming(
    meetings: list[Meeting],
    available: Mapping[str, frozenset[str]],
    *,
    as_of: datetime,
) -> UpcomingResult:
    """Reuniones de [as_of, as_of+7d): preparada = todo el conjunto esperado disponible."""
    fin = as_of + PERIODO_FUTURO
    elegibles = [m for m in meetings if as_of <= m.starts_at < fin]
    preparadas = 0
    for m in elegibles:
        disponible: set[str] = set()
        for k in m.keys:
            disponible |= available.get(k, frozenset())
        if m.expected and m.expected <= disponible:
            preparadas += 1
    total = len(elegibles)
    return UpcomingResult(total, preparadas, total - preparadas, _percent(preparadas, total))


def preparation_role_cost(plan: str | None) -> Callable[[str], int]:
    """Créditos que cuesta generar cada rol con las reglas actuales de cobro.

    Empresa: la profundidad por defecto del plan (la que usa la generación desde calendario).
    Persona: créditos del módulo de identidad.
    """
    corporativo = DEPTH_CREDITS[default_depth_for_plan(plan)]

    def _costo(rol: str) -> int:
        return corporativo if rol == ROL_CORPORATIVO else PERSON_IDENTITY_CREDITS

    return _costo


@dataclass(frozen=True)
class PreparationCostResult:
    meetings_to_generate: int
    estimated_credits: int


def summarize_preparation_cost(
    meetings: list[Meeting],
    available: Mapping[str, frozenset[str]],
    *,
    as_of: datetime,
    role_cost: Callable[[str], int],
) -> PreparationCostResult:
    """Costo estimado de completar las reuniones de [as_of, as_of+7d) que no están preparadas.

    Solo suma los dossiers esperados que faltan: lo ya generado no se cobra de nuevo. Una
    reunión con conjunto esperado vacío no tiene nada que generar y no suma. Es un máximo:
    un resultado recuperado de caché puede costar menos.
    """
    fin = as_of + PERIODO_FUTURO
    reuniones = 0
    total = 0
    for m in meetings:
        if not (as_of <= m.starts_at < fin):
            continue
        disponible: set[str] = set()
        for k in m.keys:
            disponible |= available.get(k, frozenset())
        faltan = m.expected - disponible
        if faltan:
            reuniones += 1
            total += sum(role_cost(r) for r in faltan)
    return PreparationCostResult(reuniones, total)
