"""
Lectura del calendario de Outlook vía Microsoft Graph API.
Normalizado al mismo shape que ``google_calendar_api.normalizar_evento_google``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import requests

from dossier.utils.html_text import strip_html_to_plain_line, strip_html_to_text

GRAPH_EVENTS_URL = "https://graph.microsoft.com/v1.0/me/calendar/events"
GRAPH_CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendar/calendarView"
GRAPH_EVENT_BY_ID_URL = "https://graph.microsoft.com/v1.0/me/events/{event_id}"
GRAPH_CALENDAR_EVENT_BY_ID_URL = "https://graph.microsoft.com/v1.0/me/calendar/events/{event_id}"

_SELECT = "id,subject,body,bodyPreview,start,end,attendees,organizer,location,isAllDay"

_MAX_DESCRIPCION = 2000


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Prefer": 'outlook.timezone="UTC"',
    }


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _graph_datetime_to_utc_iso(dt_str: str) -> str:
    """
    Graph devuelve ``dateTime`` sin sufijo de zona aunque el header
    ``Prefer: outlook.timezone="UTC"`` indique que el valor está en UTC.
    """
    if not dt_str or not str(dt_str).strip():
        return ""
    s = str(dt_str).strip()
    if s.endswith(("Z", "z")):
        return s if s.endswith("Z") else s[:-1] + "Z"
    tz_pos = max(s.rfind("+"), s.rfind("-"))
    if tz_pos > 10:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    try:
        if "." in s:
            base, frac = s.split(".", 1)
            s = f"{base}.{frac[:6]}"
        dt = datetime.fromisoformat(s).replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return str(dt_str).strip()


def _get_graph(url: str, access_token: str, params: dict) -> dict:
    response = requests.get(
        url,
        headers=_headers(access_token),
        params=params,
        timeout=30,
    )

    if response.status_code == 401:
        raise ValueError(
            "Token inválido o expirado. Vuelve a conectar Outlook desde la app."
        )
    if not response.ok:
        raise ValueError(
            f"Error al consultar Microsoft Graph ({response.status_code}): {response.text}"
        )

    return response.json()


def _strip_html_to_text(raw: str) -> str:
    """Convierte cuerpo HTML de Outlook a texto plano conservando saltos de línea."""
    return strip_html_to_text(raw)


def _extract_descripcion(evento: dict) -> str:
    """Descripción completa del evento (como Google ``description``), truncada a 2000 chars."""
    body = evento.get("body")
    if isinstance(body, dict):
        content = body.get("content") or ""
        if content:
            ctype = (body.get("contentType") or "").lower()
            text = _strip_html_to_text(content) if ctype == "html" else str(content).strip()
            return text[:_MAX_DESCRIPCION]
    preview = evento.get("bodyPreview") or ""
    return str(preview)[:_MAX_DESCRIPCION]


def obtener_eventos_proximos(
    access_token: str,
    top: int = 10,
    dias_adelante: int = 90,
) -> dict:
    """
    Usa calendarView: forma recomendada por Microsoft para eventos en un rango de fechas.
    """
    inicio = datetime.now(UTC)
    return obtener_eventos_en_rango(
        access_token,
        top=top,
        inicio=inicio,
        fin=inicio + timedelta(days=dias_adelante),
    )


def obtener_eventos_en_rango(
    access_token: str,
    *,
    top: int = 10,
    inicio: datetime,
    fin: datetime,
) -> dict:
    """Eventos en ``[inicio, fin]`` vía calendarView (paridad con Google ``timeMin``/``timeMax``)."""
    params = {
        "startDateTime": _iso_utc(inicio),
        "endDateTime": _iso_utc(fin),
        "$top": top,
        "$orderby": "start/dateTime",
        "$select": _SELECT,
    }
    return _get_graph(GRAPH_CALENDAR_VIEW_URL, access_token, params)


def obtener_todos_los_eventos(access_token: str, top: int = 50) -> dict:
    """Lista eventos sin filtro de fecha (útil para depurar calendarios vacíos).

    Orden por ``createdDateTime`` para que reuniones recién creadas aparezcan
    primero (con ``start`` desc un evento futuro lejano podía quedar fuera del top).
    """
    params = {
        "$top": top,
        "$orderby": "createdDateTime desc",
        "$select": _SELECT,
    }
    return _get_graph(GRAPH_EVENTS_URL, access_token, params)


def merge_reunion_payload(client: dict | None, fresh: dict | None) -> dict | None:
    """
    Combina el evento del listado (cliente) con uno recién leído del proveedor.

    Prioriza la descripción más larga (suele traer «Contacto:» desde Graph).
    """
    if not client and not fresh:
        return None
    if not fresh:
        return client
    if not client:
        return fresh

    client_desc = str(client.get("descripcion") or "").strip()
    fresh_desc = str(fresh.get("descripcion") or "").strip()
    descripcion = fresh_desc if len(fresh_desc) >= len(client_desc) else client_desc
    if not descripcion:
        descripcion = fresh_desc or client_desc

    merged = {
        "id": client.get("id") or fresh.get("id"),
        "tema": fresh.get("tema") or client.get("tema") or "Sin asunto",
        "descripcion": descripcion[:_MAX_DESCRIPCION],
        "participantes": fresh.get("participantes") or client.get("participantes") or "No especificados",
        "inicio": fresh.get("inicio") or client.get("inicio") or "",
        "fin": fresh.get("fin") or client.get("fin") or "",
        "ubicacion": fresh.get("ubicacion") or client.get("ubicacion") or "",
        "todo_el_dia": bool(fresh.get("todo_el_dia") if "todo_el_dia" in fresh else client.get("todo_el_dia")),
    }
    snap_lang = client.get("_output_language")
    if snap_lang:
        merged["_output_language"] = snap_lang
    return merged


def coerce_reunion_payload(data: dict | None) -> dict | None:
    """Valida reunión enviada por el cliente (listado ya cargado)."""
    if not data or not isinstance(data, dict):
        return None
    event_id = data.get("id")
    tema = strip_html_to_plain_line(data.get("tema") or data.get("subject"))
    if not event_id and not tema:
        return None
    desc_raw = str(data.get("descripcion") or data.get("description") or "")
    return {
        "id": event_id,
        "tema": tema or "Sin asunto",
        "descripcion": strip_html_to_text(desc_raw)[:_MAX_DESCRIPCION],
        "participantes": data.get("participantes") or "No especificados",
        "inicio": data.get("inicio") or "",
        "fin": data.get("fin") or "",
        "ubicacion": data.get("ubicacion") or "",
        "todo_el_dia": bool(data.get("todo_el_dia")),
    }


def _normalize_graph_event_id(event_id: str) -> str:
    """Graph usa ids base64; en query strings el ``+`` a veces llega como espacio."""
    eid = (event_id or "").strip()
    if not eid:
        return eid
    if " " in eid and "+" not in eid:
        eid = eid.replace(" ", "+")
    return eid


def _fetch_graph_event(access_token: str, event_id: str) -> dict | None:
    encoded = quote(event_id, safe="")
    for template in (GRAPH_EVENT_BY_ID_URL, GRAPH_CALENDAR_EVENT_BY_ID_URL):
        url = template.format(event_id=encoded)
        response = requests.get(
            url,
            headers=_headers(access_token),
            params={"$select": _SELECT},
            timeout=30,
        )
        if response.status_code == 404:
            continue
        if response.status_code == 401:
            raise ValueError(
                "Token inválido o expirado. Vuelve a conectar Outlook desde la app."
            )
        if not response.ok:
            continue
        return response.json()
    return None


def _formatear_participantes(evento: dict) -> str:
    """Convierte asistentes y organizador en texto para el orquestador."""
    nombres: list[str] = []

    organizador = evento.get("organizer", {}).get("emailAddress", {})
    if organizador:
        nombre = organizador.get("name") or organizador.get("address", "")
        if nombre:
            nombres.append(f"{nombre} (organizador)")

    for asistente in evento.get("attendees") or []:
        correo = asistente.get("emailAddress", {})
        nombre = correo.get("name") or correo.get("address", "")
        if nombre and nombre not in nombres:
            nombres.append(nombre)

    return ", ".join(nombres) if nombres else "No especificados"


def normalizar_evento(evento: dict) -> dict:
    """Reduce un evento de Graph a los campos que usa el dossier."""
    inicio_raw = (evento.get("start") or {}).get("dateTime", "")
    fin_raw = (evento.get("end") or {}).get("dateTime", "")

    return {
        "id": evento.get("id"),
        "tema": strip_html_to_plain_line(evento.get("subject")) or "Sin asunto",
        "descripcion": _extract_descripcion(evento),
        "participantes": _formatear_participantes(evento),
        "inicio": _graph_datetime_to_utc_iso(inicio_raw),
        "fin": _graph_datetime_to_utc_iso(fin_raw),
        "ubicacion": (evento.get("location") or {}).get("displayName") or "",
        "todo_el_dia": evento.get("isAllDay", False),
    }


def diagnostico_microsoft_calendar(access_token: str) -> dict:
    """
    Resumen no sensible: qué usuario ve Graph y si hay eventos en el calendario
    predeterminado (útil si /calendario/eventos devuelve vacío).
    """
    resultado: dict = {
        "me": None,
        "calendars": None,
        "events_raw_count": None,
        "events_preview": None,
        "errors": [],
    }
    url_me = "https://graph.microsoft.com/v1.0/me"
    url_cals = "https://graph.microsoft.com/v1.0/me/calendars"

    try:
        r = requests.get(url_me, headers=_headers(access_token), timeout=30)
        if r.ok:
            j = r.json()
            resultado["me"] = {
                "displayName": j.get("displayName"),
                "mail": j.get("mail"),
                "userPrincipalName": j.get("userPrincipalName"),
                "id": j.get("id"),
            }
        else:
            resultado["errors"].append(f"GET /me → {r.status_code}: {r.text[:300]}")
    except requests.RequestException as e:
        resultado["errors"].append(f"GET /me → {e}")

    try:
        r = requests.get(url_cals, headers=_headers(access_token), timeout=30)
        if r.ok:
            j = r.json()
            vals = j.get("value", [])
            resultado["calendars"] = {
                "count": len(vals),
                "names": [c.get("name") for c in vals[:15]],
            }
        else:
            resultado["errors"].append(f"GET /me/calendars → {r.status_code}: {r.text[:300]}")
    except requests.RequestException as e:
        resultado["errors"].append(f"GET /me/calendars → {e}")

    try:
        r = requests.get(
            GRAPH_EVENTS_URL,
            headers=_headers(access_token),
            params={  # type: ignore[arg-type]  # valores str/int validos para requests; mypy infiere dict[str, object]
                "$top": 10,
                "$orderby": "createdDateTime desc",
                "$select": "id,subject,start,createdDateTime",
            },
            timeout=30,
        )
        if r.ok:
            j = r.json()
            vals = j.get("value", [])
            resultado["events_raw_count"] = len(vals)
            resultado["events_preview"] = [
                {
                    "subject": v.get("subject"),
                    "start": (v.get("start") or {}).get("dateTime"),
                    "createdDateTime": v.get("createdDateTime"),
                }
                for v in vals
            ]
        else:
            resultado["errors"].append(
                f"GET /me/calendar/events → {r.status_code}: {r.text[:300]}"
            )
    except requests.RequestException as e:
        resultado["errors"].append(f"GET /me/calendar/events → {e}")

    return resultado


def listar_reuniones(
    access_token: str,
    top: int = 10,
    dias_adelante: int = 90,
    incluir_pasadas: bool = False,
) -> list[dict]:
    """
    Devuelve reuniones normalizadas.
    Por defecto: próximos `dias_adelante` días vía calendarView.
    Con incluir_pasadas=True: cualquier evento reciente del calendario.
    """
    if incluir_pasadas:
        now = datetime.now(UTC)
        fetch_top = min(max(top * 4, top), 50)
        datos = obtener_eventos_en_rango(
            access_token,
            top=fetch_top,
            inicio=now - timedelta(days=min(90, dias_adelante)),
            fin=now + timedelta(days=dias_adelante),
        )
        reuniones = [normalizar_evento(e) for e in datos.get("value", [])]
        reuniones.sort(key=lambda r: r.get("inicio") or "", reverse=True)
        return reuniones[:top]
    else:
        datos = obtener_eventos_proximos(
            access_token, top=top, dias_adelante=dias_adelante
        )

    return [normalizar_evento(e) for e in datos.get("value", [])]


def obtener_reunion_por_id(
    access_token: str,
    event_id: str,
    dias_adelante: int = 90,
) -> dict | None:
    """GET directo por id en Graph (paridad con ``obtener_reunion_google_por_id``)."""
    eid = _normalize_graph_event_id(event_id)
    if not eid:
        return None

    raw = _fetch_graph_event(access_token, eid)
    if raw is not None:
        return normalizar_evento(raw)

    now = datetime.now(UTC)
    try:
        datos = obtener_eventos_en_rango(
            access_token,
            top=50,
            inicio=now - timedelta(days=30),
            fin=now + timedelta(days=dias_adelante),
        )
        for ev in datos.get("value", []):
            if ev.get("id") == eid:
                return normalizar_evento(ev)
    except ValueError:
        pass
    return None
