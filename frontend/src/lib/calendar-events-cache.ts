import type { CalendarEventosRangoResponse, CalendarProvider } from "@/lib/dossier-api";

/**
 * Caché en memoria de las consultas por intervalo. Vive solo en la pestaña y se
 * identifica por la sesión (el JWT vigente): nada se comparte entre usuarios, y
 * cualquier entrada de otra sesión se descarta al primer acceso.
 */
const TTL_MS = 5 * 60_000;
const MAX_ENTRIES = 40;

type Entry = { session: string; at: number; value: CalendarEventosRangoResponse };

const store = new Map<string, Entry>();

export function calendarCacheKey(
  provider: CalendarProvider,
  range: { desde: string; hasta: string },
  timezone: string,
): string {
  return `${provider}|${range.desde}|${range.hasta}|${timezone}`;
}

function purge(session: string, now: number) {
  for (const [key, entry] of store) {
    if (entry.session !== session || now - entry.at > TTL_MS) store.delete(key);
  }
}

export function readCalendarCache(session: string, key: string): CalendarEventosRangoResponse | null {
  purge(session, Date.now());
  return store.get(key)?.value ?? null;
}

/** Solo se guardan respuestas completas: una carga parcial se reintenta en la siguiente consulta. */
export function writeCalendarCache(session: string, key: string, value: CalendarEventosRangoResponse) {
  if (!value.completo) return;
  const now = Date.now();
  purge(session, now);
  store.delete(key);
  store.set(key, { session, at: now, value });
  while (store.size > MAX_ENTRIES) {
    const oldest = store.keys().next().value;
    if (oldest === undefined) break;
    store.delete(oldest);
  }
}

export function clearCalendarEventsCache() {
  store.clear();
}
