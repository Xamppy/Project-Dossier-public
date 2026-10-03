import { Temporal } from "temporal-polyfill";
import type { CalendarProvider, OutlookReunionApi } from "@/lib/dossier-api";
import { parseMeetingInstant } from "@/lib/format";
import { stripHtmlToPlainLine } from "@/lib/strip-html";

/** Evento de calendario ya validado, listo para pintarse y para generar un dossier. */
export type CalendarEventModel = {
  /** Identidad visual única: proveedor + id de ocurrencia (nunca solo el id). */
  key: string;
  provider: CalendarProvider;
  /** Id original del proveedor, tal cual lo espera la API de dossiers. `null` = no se puede generar. */
  eventId: string | null;
  title: string;
  /** Instante ISO (UTC) o fecha civil `YYYY-MM-DD` si es de día completo. */
  start: string;
  /** `null` cuando el proveedor no entregó un fin válido: no se inventa una hora de fin. */
  end: string | null;
  allDay: boolean;
  description: string;
  participants: string;
  location: string;
  /** Fila original de la API, para enviarla sin alteraciones al generar el dossier. */
  raw: OutlookReunionApi;
};

export type AdaptedMeetings = {
  events: CalendarEventModel[];
  /** Registros sin inicio válido: no se pueden situar en el calendario. */
  discarded: number;
};

export type CalendarWindow = { desde: string; hasta: string };

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

export function calendarEventKey(provider: CalendarProvider, eventId: string): string {
  return `${provider}:${eventId}`;
}

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

/**
 * Convierte HTML en texto plano conservando los saltos de línea. Nunca devuelve
 * marcado: se pinta siempre como texto, de modo que nada se interpreta ni ejecuta.
 */
export function descriptionToPlainText(raw: string | null | undefined): string {
  if (!raw?.trim()) return "";
  const sinCodigo = raw
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|tr|h[1-6]|pre)\s*>/gi, "\n")
    .replace(/<[^>]*>/g, " ");
  // Una sola pasada: `&amp;lt;` queda como `&lt;`, no como `<`.
  const decodificado = sinCodigo.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, ent: string) => {
    if (ent[0] === "#") {
      const code = ent[1].toLowerCase() === "x" ? parseInt(ent.slice(2), 16) : parseInt(ent.slice(1), 10);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : m;
    }
    return NAMED_ENTITIES[ent.toLowerCase()] ?? m;
  });
  return decodificado
    .split("\n")
    .map((l) => l.replace(/[ \t ]+/g, " ").trim())
    .filter((l, i, arr) => l !== "" || (i > 0 && arr[i - 1] !== ""))
    .join("\n")
    .trim();
}

function civilDateInZone(iso: string, timezone: string): string | null {
  const d = parseMeetingInstant(iso);
  if (!d) return null;
  try {
    return Temporal.Instant.fromEpochMilliseconds(d.getTime())
      .toZonedDateTimeISO(timezone)
      .toPlainDate()
      .toString();
  } catch {
    return null;
  }
}

function adaptTimes(
  r: OutlookReunionApi,
  timezone: string,
): { start: string; end: string | null; allDay: boolean } | null {
  const inicio = r.inicio?.trim() ?? "";
  const fin = r.fin?.trim() ?? "";

  if (r.todo_el_dia) {
    const start = DATE_ONLY.test(inicio) ? inicio : civilDateInZone(inicio, timezone);
    if (!start) return null;
    const end = DATE_ONLY.test(fin) ? fin : civilDateInZone(fin, timezone);
    return { start, end: end && end > start ? end : null, allDay: true };
  }

  const s = parseMeetingInstant(inicio);
  if (!s) return null;
  const e = parseMeetingInstant(fin);
  return {
    start: s.toISOString(),
    end: e && e.getTime() > s.getTime() ? e.toISOString() : null,
    allDay: false,
  };
}

export function adaptMeetings(
  provider: CalendarProvider,
  reuniones: OutlookReunionApi[],
  timezone: string,
  fallbackTitle: string,
): AdaptedMeetings {
  const events: CalendarEventModel[] = [];
  const seen = new Map<string, number>();
  let discarded = 0;

  reuniones.forEach((r, index) => {
    const times = adaptTimes(r, timezone);
    if (!times) {
      discarded += 1;
      return;
    }
    const eventId = r.id?.trim() || null;
    const base = eventId
      ? calendarEventKey(provider, eventId)
      : `${provider}:sin-id:${index}:${times.start}`;
    const repeats = seen.get(base) ?? 0;
    seen.set(base, repeats + 1);
    events.push({
      key: repeats === 0 ? base : `${base}#${repeats}`,
      provider,
      eventId,
      title: stripHtmlToPlainLine(r.tema) || fallbackTitle,
      ...times,
      description: descriptionToPlainText(r.descripcion),
      participants: stripHtmlToPlainLine(r.participantes),
      location: stripHtmlToPlainLine(r.ubicacion),
      raw: r,
    });
  });

  return { events, discarded };
}

export function toFullCalendarEvent(e: CalendarEventModel) {
  return {
    id: e.key,
    title: e.title,
    start: e.start,
    ...(e.end ? { end: e.end } : {}),
    allDay: e.allDay,
    className: `dossier-ev dossier-ev--${e.provider}`,
    extendedProps: { provider: e.provider },
  };
}

function civilPart(value: string): string {
  return value.slice(0, 10);
}

/**
 * Intervalo de consulta para la API a partir de las fechas civiles visibles (fin exclusivo).
 * Se calcula en la zona del usuario: el día empieza a su medianoche, no a la de UTC.
 */
export function windowFromCivilDates(startDate: string, endDate: string, timezone: string): CalendarWindow {
  const zone = isValidTimeZone(timezone) ? timezone : "UTC";
  const at = (d: string) =>
    Temporal.PlainDate.from(civilPart(d))
      .toZonedDateTime(zone)
      .toString({ timeZoneName: "never", smallestUnit: "second" });
  return { desde: at(startDate), hasta: at(endDate) };
}

function isValidTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** Ancho mínimo del calendario para que siete columnas de la semana sigan siendo legibles. */
export const WEEK_MIN_WIDTH_PX = 640;

export type CalendarViewType = "timeGridDay" | "timeGridWeek" | "dayGridMonth";

/**
 * Vista inicial según el ancho **del calendario**, no del viewport: con el menú lateral una tableta de
 * 768 px deja ~414 px útiles, donde la semana no se lee. Escritorio: Semana; móvil o estrecho: Día.
 */
export function initialViewForWidth(width: number): CalendarViewType {
  return width < WEEK_MIN_WIDTH_PX ? "timeGridDay" : "timeGridWeek";
}
