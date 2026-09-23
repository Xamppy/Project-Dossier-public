"""
Lectura de Google Calendar API v3 (calendario ``primary``), normalizado al mismo
shape que ``graph_calendar.normalizar_evento`` para reutilizar dossiers.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import requests

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
