"""
Indicadores de Resumen (UX-KPI-01): lógica pura de elegibilidad, preparación y puntualidad.

No toca la base de datos ni la red: recibe reuniones ya leídas del calendario y hechos ya
cargados, y devuelve conteos. Así se prueba sin infraestructura y el servicio de resumen
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

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from dossier.billing.entitlements import plan_allows_calendar_corporate_dossier
from dossier.services.calendar_event_dossiers import parse_calendar_event_for_dossiers
from dossier.services.calendar_event_filters import has_external_attendee, is_work_meeting
from dossier.services.meeting_identity import (
    ORIGEN_AUTOMATICO,
    ORIGEN_MANUAL,
    ROL_CORPORATIVO,
    Fact,
    expected_roles_from_parsed,
    meeting_key,
    parse_start,
    role_for_person,
)

__all__ = [
    "ORIGEN_AUTOMATICO",
    "ORIGEN_MANUAL",
    "ROL_CORPORATIVO",
    "CalendarEntry",
    "CalendarSnapshot",
    "Fact",
    "HistoryResult",
    "Meeting",
    "UpcomingResult",
    "collect_meetings",
    "expected_roles",
    "meeting_key",
    "parse_start",
    "role_for_person",
    "summarize_history",
    "summarize_upcoming",
]

PERIODO_FUTURO = timedelta(days=7)
PERIODO_HISTORIAL = timedelta(days=30)

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
    #: clave → inicio de TODO evento leído con inicio válido, sea elegible o no
    seen: dict[str, datetime] = field(default_factory=dict)


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
        snap.seen[clave] = inicio
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


@dataclass(frozen=True)
class HistoryResult:
    eligible: int
    on_time_meetings: int
    percent: float | None
    on_time_dossiers: int


def _was_available_at_start(fact: Fact, start: datetime) -> bool:
    """Terminó antes del inicio y su documento no se borró antes de la reunión."""
    if fact.completed_at >= start:
        return False
    return fact.deleted_at is None or fact.deleted_at >= start


def summarize_history(
    meetings: list[Meeting],
    seen: Mapping[str, datetime],
    facts: list[Fact],
    *,
    measured_from: datetime,
    as_of: datetime,
    fetched_from: datetime | None = None,
    fetched_to: datetime | None = None,
) -> HistoryResult:
    """Puntualidad manual de las reuniones con inicio en [measured_from, as_of).

    ``fetched_from``/``fetched_to`` es lo que el calendario leyó completo (por omisión
    30 días atrás y 7 adelante): sirve para decidir si un hecho cuyo inicio registrado cae
    ahí y cuya reunión no aparece corresponde a una reunión cancelada o movida.
    """
    leido_desde = fetched_from if fetched_from is not None else as_of - PERIODO_HISTORIAL
    leido_hasta = fetched_to if fetched_to is not None else as_of + PERIODO_FUTURO

    manuales: dict[str, Fact] = {}
    for f in facts:
        if f.origin == ORIGEN_MANUAL:
            manuales.setdefault(f.result_key, f)  # idempotente: un resultado, un hecho
    por_reunion: dict[str, list[Fact]] = {}
    for f in manuales.values():
        por_reunion.setdefault(f.meeting_key, []).append(f)

    pasadas = [m for m in meetings if measured_from <= m.starts_at < as_of]
    a_tiempo = 0
    for m in pasadas:
        candidatos = [f for k in m.keys for f in por_reunion.get(k, [])]
        validos = sorted(
            (f for f in candidatos if _was_available_at_start(f, m.starts_at)),
            key=lambda f: f.completed_at,
        )
        if not validos:
            continue
        esperado = validos[-1].expected_keys
        if esperado is None:
            esperado = m.expected
        cubiertos = {f.role_key for f in validos}
        if esperado and esperado <= cubiertos:
            a_tiempo += 1

    por_clave = {k: m for m in meetings for k in m.keys}
    dossiers = 0
    for f in manuales.values():
        if not (measured_from <= f.completed_at < as_of):
            continue
        reunion = por_clave.get(f.meeting_key)
        if reunion is not None:
            inicio: datetime | None = reunion.starts_at
        elif f.meeting_key in seen:
            inicio = None  # la reunión existe pero no es elegible
        elif f.meeting_starts_at is None or leido_desde <= f.meeting_starts_at < leido_hasta:
            inicio = None  # sin reunión asociada, o cancelada/movida dentro de lo leído
        else:
            inicio = f.meeting_starts_at
        if inicio is not None and _was_available_at_start(f, inicio):
            dossiers += 1

    return HistoryResult(len(pasadas), a_tiempo, _percent(a_tiempo, len(pasadas)), dossiers)
