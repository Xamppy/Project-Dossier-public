import type { CalendarProvider } from "@/lib/dossier-api";

/** Lo mínimo que se necesita de un job para asociarlo a un evento de calendario. */
type EventJob = {
  status: string;
  external_event_id?: string | null;
  calendar_provider?: string | null;
};

const ACTIVE = new Set(["queued", "running"]);

function matches(job: EventJob, eventId: string, provider?: CalendarProvider): boolean {
  if (job.external_event_id !== eventId) return false;
  // Con proveedor indicado, un job sin proveedor conocido no se atribuye a ninguno:
  // dos calendarios pueden repetir el mismo id y no deben compartir estado.
  return provider === undefined || job.calendar_provider === provider;
}

/** Job de un evento: el activo si lo hay; si no, el más reciente (los jobs se añaden al final). */
export function findJobForEvent<T extends EventJob>(
  jobs: T[],
  eventId: string | null | undefined,
  provider?: CalendarProvider,
): T | undefined {
  if (!eventId) return undefined;
  const found = jobs.filter((j) => matches(j, eventId, provider));
  return found.find((j) => ACTIVE.has(j.status)) ?? found[found.length - 1];
}

export function isEventJobActive(
  jobs: EventJob[],
  eventId: string | null | undefined,
  provider?: CalendarProvider,
): boolean {
  if (!eventId) return false;
  return jobs.some((j) => matches(j, eventId, provider) && ACTIVE.has(j.status));
}
