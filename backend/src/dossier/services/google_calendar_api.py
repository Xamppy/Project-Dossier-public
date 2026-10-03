"""
Lectura de Google Calendar API v3 (calendario ``primary``), normalizado al mismo
shape que ``graph_calendar.normalizar_evento`` para reutilizar dossiers.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import requests

from dossier.services.calendar_range import (
    MAX_PAGINAS,
    MOTIVO_ERROR_PROVEEDOR,
    MOTIVO_LIMITE_PAGINAS,
    MOTIVO_TIEMPO_AGOTADO,
    POR_PAGINA,
    ErrorProveedorCalendario,
    Presupuesto,
    RangoConsulta,
    Reloj,
    ResultadoRango,
)
from dossier.utils.html_text import strip_html_to_plain_line, strip_html_to_text

_EVENTS_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(access_token: str, params: dict) -> dict:
    r = requests.get(_EVENTS_BASE, headers=_headers(access_token), params=params, timeout=30)
    if r.status_code == 401:
        raise ValueError("Token de Google inválido o expirado. Vuelve a conectar Google Calendar.")
    if not r.ok:
        raise ValueError(f"Google Calendar API ({r.status_code}): {r.text[:500]}")
    return r.json()


def _formatear_participantes(evento: dict) -> str:
    emails: list[str] = []
    org = evento.get("organizer", {})
    if isinstance(org, dict):
        em = org.get("email")
        if em:
            emails.append(f"{em} (organizador)")
    for a in evento.get("attendees") or []:
        if not isinstance(a, dict):
            continue
        em = a.get("email")
        if em and em not in emails:
            emails.append(em)
    return ", ".join(emails) if emails else "No especificados"


def normalizar_evento_google(evento: dict) -> dict:
    start = evento.get("start") or {}
    end = evento.get("end") or {}
    inicio = start.get("dateTime") or start.get("date") or ""
    fin = end.get("dateTime") or end.get("date") or ""
    loc = evento.get("location")
    if not isinstance(loc, str):
        loc = ""
    all_day = bool(start.get("date") and not start.get("dateTime"))
    desc = strip_html_to_text(evento.get("description") or "")[:2000]
    return {
        "id": evento.get("id"),
        "tema": strip_html_to_plain_line(evento.get("summary")) or "Sin asunto",
        "descripcion": desc,
        "participantes": _formatear_participantes(evento),
        "inicio": inicio,
        "fin": fin,
        "ubicacion": loc,
        "todo_el_dia": all_day,
    }


def _correos_google(evento: dict) -> list[str]:
    """Direcciones reales del evento (organizador y asistentes), en minúsculas y sin repetir."""
    vistos: list[str] = []
    org = evento.get("organizer")
    candidatos = [org.get("email")] if isinstance(org, dict) else []
    candidatos += [a.get("email") for a in evento.get("attendees") or [] if isinstance(a, dict)]
    for c in candidatos:
        if isinstance(c, str) and "@" in c and c.strip().lower() not in vistos:
            vistos.append(c.strip().lower())
    return vistos


def _respuesta_usuario_google(evento: dict) -> str | None:
    for a in evento.get("attendees") or []:
        if isinstance(a, dict) and a.get("self") is True:
            r = a.get("responseStatus")
            return r if r == "declined" else None
    return None


def normalizar_evento_google_rango(evento: dict) -> dict:
    """Como ``normalizar_evento_google`` más lo que necesitan los indicadores (solo ruta por intervalo)."""
    out = normalizar_evento_google(evento)
    uid = evento.get("iCalUID")
    if isinstance(uid, str) and uid.strip():
        out["ical_uid"] = uid.strip()
    out["correos"] = _correos_google(evento)
    if _respuesta_usuario_google(evento) == "declined":
        out["respuesta_usuario"] = "declined"
    return out


def listar_reuniones_google(
    access_token: str,
    top: int = 10,
    dias_adelante: int = 90,
    incluir_pasadas: bool = False,
) -> list[dict]:
    """Lista eventos del calendario principal, normalizados."""
    now = datetime.now(UTC)
    if incluir_pasadas:
        time_min = now - timedelta(days=min(90, dias_adelante))
        time_max = now + timedelta(days=dias_adelante)
        fetch_top = min(max(top * 4, top), 50)
    else:
        time_min = now
        time_max = now + timedelta(days=dias_adelante)
        fetch_top = max(top, 1)

    params: dict[str, str | int | bool] = {
        "timeMin": _iso_z(time_min),
        "timeMax": _iso_z(time_max),
        "maxResults": fetch_top,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    datos = _get(access_token, params)
    items = datos.get("items") or []
    reuniones = [normalizar_evento_google(e) for e in items]
    if incluir_pasadas:
        reuniones.sort(key=lambda r: r.get("inicio") or "", reverse=True)
    return reuniones[:top]


def listar_reuniones_google_rango(
    access_token: str,
    rango: RangoConsulta,
    *,
    reloj: Reloj = time.monotonic,
    por_pagina: int = POR_PAGINA,
    max_paginas: int = MAX_PAGINAS,
) -> ResultadoRango:
    """Eventos del calendario principal que se solapan con ``[desde, hasta)``.

    Recorre ``nextPageToken`` con límite de páginas y presupuesto de tiempo. Si un
    límite se agota o falla una página posterior devuelve lo recuperado con
    ``completo=False``; si falla la primera, lanza ``ErrorProveedorCalendario``.
    ``singleEvents`` expande las recurrencias; las ocurrencias canceladas se excluyen.
    """
    presupuesto = Presupuesto(reloj)
    base: dict[str, str | int | bool] = {
        "timeMin": _iso_z(rango.desde),
        "timeMax": _iso_z(rango.hasta),
        "maxResults": por_pagina,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    resultado = ResultadoRango()
    page_token: str | None = None
    paginas = 0
    while True:
        if paginas >= max_paginas:
            resultado.completo, resultado.motivo_incompleto = False, MOTIVO_LIMITE_PAGINAS
            break
        if paginas > 0 and presupuesto.agotado():
            resultado.completo, resultado.motivo_incompleto = False, MOTIVO_TIEMPO_AGOTADO
            break
        params = dict(base)
        if page_token:
            params["pageToken"] = page_token
        try:
            r = requests.get(
                _EVENTS_BASE,
                headers=_headers(access_token),
                params=params,
                timeout=presupuesto.timeout_peticion(),
            )
            ok = r.ok
            datos = r.json() if ok else None
            estado = r.status_code
        except requests.Timeout as e:
            if paginas == 0:
                raise ErrorProveedorCalendario(504, "Google Calendar tardó demasiado en responder.") from e
            resultado.completo, resultado.motivo_incompleto = False, MOTIVO_TIEMPO_AGOTADO
            break
        except (requests.RequestException, ValueError) as e:
            if paginas == 0:
                raise ErrorProveedorCalendario(502, "No se pudo consultar Google Calendar.") from e
            resultado.completo, resultado.motivo_incompleto = False, MOTIVO_ERROR_PROVEEDOR
            break
        if not ok or not isinstance(datos, dict):
            if paginas == 0:
                detalle = (
                    "Token de Google inválido o expirado. Vuelve a conectar Google Calendar."
                    if estado == 401
                    else f"Google Calendar respondió con error ({estado})."
                )
                raise ErrorProveedorCalendario(502, detalle)
            resultado.completo, resultado.motivo_incompleto = False, MOTIVO_ERROR_PROVEEDOR
            break
        paginas += 1
        for evento in datos.get("items") or []:
            if isinstance(evento, dict) and evento.get("status") != "cancelled":
                resultado.reuniones.append(normalizar_evento_google_rango(evento))
        page_token = datos.get("nextPageToken") or None
        if not page_token:
            break
    return resultado


def diagnostico_google_calendar(access_token: str) -> dict:
    """
    Resumen no sensible: calendario principal y eventos recientes
    (útil si /calendario/eventos-google devuelve vacío).
    """
    resultado: dict = {
        "calendar": None,
        "events_raw_count": None,
        "events_preview": None,
        "errors": [],
    }
    try:
        r = requests.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary",
            headers=_headers(access_token),
            timeout=30,
        )
        if r.ok:
            j = r.json()
            resultado["calendar"] = {
                "id": j.get("id"),
                "summary": j.get("summary"),
                "timeZone": j.get("timeZone"),
            }
        else:
            resultado["errors"].append(f"GET calendars/primary → {r.status_code}: {r.text[:300]}")
    except requests.RequestException as e:
        resultado["errors"].append(f"GET calendars/primary → {e}")

    now = datetime.now(UTC)
    try:
        params = {
            "timeMin": _iso_z(now - timedelta(days=7)),
            "timeMax": _iso_z(now + timedelta(days=7)),
            "maxResults": 10,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        datos = _get(access_token, params)
        items = datos.get("items") or []
        resultado["events_raw_count"] = len(items)
        resultado["events_preview"] = [
            {
                "summary": e.get("summary"),
                "start": (e.get("start") or {}).get("dateTime")
                or (e.get("start") or {}).get("date"),
            }
            for e in items
        ]
    except ValueError as e:
        resultado["errors"].append(str(e))
    except requests.RequestException as e:
        resultado["errors"].append(f"GET events → {e}")

    return resultado


def obtener_reunion_google_por_id(access_token: str, event_id: str) -> dict | None:
    """GET un evento por id en ``primary``."""
    eid = quote(event_id, safe="")
    url = f"{_EVENTS_BASE}/{eid}"
    r = requests.get(url, headers=_headers(access_token), timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code == 401:
        raise ValueError("Token de Google inválido o expirado. Vuelve a conectar Google Calendar.")
    if not r.ok:
        raise ValueError(f"Google Calendar API ({r.status_code}): {r.text[:500]}")
    return normalizar_evento_google(r.json())
