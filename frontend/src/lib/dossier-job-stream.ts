/**
 * Canal de estados de un job de generación de dossiers por SSE (S5.1).
 *
 * Consume `GET /dossier-generation-jobs/{job_id}/stream` (S4.8) con
 * `@microsoft/fetch-event-source`, elegido en el ADR 0006 porque permite
 * enviar el JWT en `Authorization` en vez de ponerlo en la URL.
 *
 * Política de esta entrega: una conexión por suscripción y ningún reintento
 * automático. Cualquier corte termina la suscripción con un
 * `DossierJobStreamError` y quien la abrió decide qué hacer. La reconexión
 * con retroceso progresivo es S5.3: debe partir de `onError` y de
 * `lastEventId()` (cursor de esta conexión, para `Last-Event-ID`).
 */
import { fetchEventSource, type EventSourceMessage } from "@microsoft/fetch-event-source";
import {
  getApiBaseUrl,
  getStoredAccessToken,
  type DossierGenerationJobApi,
  type DossierGenerationJobStatus,
} from "@/lib/dossier-api";

export type DossierJobStreamEventName = "job_status" | "job_completed" | "job_failed";

export type DossierJobStreamErrorKind =
  /** 401 o sin token guardado. */
  | "unauthorized"
  /** 403. */
  | "forbidden"
  /** 404: el job no existe o no es del usuario/organización. */
  | "not_found"
  /** Cualquier otro estado HTTP (5xx, 429…). */
  | "http"
  /** `fetch` falló o la lectura se cortó. */
  | "network"
  /** El servidor cerró el stream sin estado terminal (p. ej. su corte de 600 s). */
  | "unexpected_eof"
  /** Content-Type ajeno a SSE o un evento conocido con payload inválido. */
  | "protocol";

export class DossierJobStreamError extends Error {
  readonly kind: DossierJobStreamErrorKind;
  readonly status: number | null;

  constructor(kind: DossierJobStreamErrorKind, status: number | null = null) {
    super(kind);
    this.name = "DossierJobStreamError";
    this.kind = kind;
    this.status = status;
  }
}

export type DossierJobStreamHandlers = {
  /** Snapshot de `serialize_job()` ya validado y del job pedido. */
  onSnapshot: (
    job: DossierGenerationJobApi,
    meta: { event: DossierJobStreamEventName; eventId: string | null },
  ) => void;
  /** Se llama como mucho una vez; después la suscripción ya está cerrada. */
  onError: (error: DossierJobStreamError) => void;
};

export type DossierJobStreamSubscription = {
  /** Cierra la lectura. No cancela el job en el servidor. */
  close: () => void;
  /** Último `id:` recibido en esta conexión; punto de extensión para S5.3. */
  lastEventId: () => string | null;
};

const JOB_EVENTS: ReadonlySet<string> = new Set(["job_status", "job_completed", "job_failed"]);
const JOB_STATUSES: ReadonlySet<string> = new Set<DossierGenerationJobStatus>([
  "queued",
  "running",
  "completed",
  "failed",
  "cancelled",
]);
const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/** Valida en ejecución el payload de un evento de job; `null` si no sirve. */
export function parseJobSnapshot(data: unknown, expectedId: string): DossierGenerationJobApi | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const o = data as Record<string, unknown>;
  if (o.id !== expectedId) return null;
  if (typeof o.status !== "string" || !JOB_STATUSES.has(o.status)) return null;
  if (typeof o.job_type !== "string" || !o.job_type) return null;
  return o as unknown as DossierGenerationJobApi;
}

function errorForStatus(status: number): DossierJobStreamError {
  if (status === 401) return new DossierJobStreamError("unauthorized", status);
  if (status === 403) return new DossierJobStreamError("forbidden", status);
  if (status === 404) return new DossierJobStreamError("not_found", status);
  return new DossierJobStreamError("http", status);
}

export function openDossierJobStream(
  jobId: string,
  handlers: DossierJobStreamHandlers,
): DossierJobStreamSubscription {
  const controller = new AbortController();
  let finished = false;
  let cursor: string | null = null;

  function finish() {
    finished = true;
    controller.abort();
  }

  function fail(error: DossierJobStreamError) {
    if (finished) return;
    finish();
    handlers.onError(error);
  }

  const subscription: DossierJobStreamSubscription = {
    close: finish,
    lastEventId: () => cursor,
  };

  const token = getStoredAccessToken();
  if (!token) {
    // Asíncrono, como cualquier otro error: quien abre no recibe callbacks durante la llamada.
    queueMicrotask(() => fail(new DossierJobStreamError("unauthorized")));
    return subscription;
  }

  const url = `${getApiBaseUrl()}/dossier-generation-jobs/${encodeURIComponent(jobId)}/stream`;

  fetchEventSource(url, {
    method: "GET",
    // En minúsculas: la librería añade `accept` si no lo encuentra con ese nombre.
    headers: { accept: "text/event-stream", authorization: `Bearer ${token}` },
    signal: controller.signal,
    // Sin esto la librería corta y reabre la conexión cada vez que cambia la visibilidad.
    openWhenHidden: true,
    // `fetch` global resuelto en cada llamada (la librería usaría `window.fetch` fijo).
    fetch: (input, init) => fetch(input, init),
    async onopen(response) {
      if (!response.ok) throw errorForStatus(response.status);
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.startsWith("text/event-stream")) {
        throw new DossierJobStreamError("protocol", response.status);
      }
    },
    onmessage(message: EventSourceMessage) {
      if (finished) return;
      if (message.id) cursor = message.id;
      // Heartbeat (`: ping`) llega como mensaje vacío; agent_progress y eventos
      // desconocidos no son snapshots del job y no se aplican aquí.
      if (!message.data || !JOB_EVENTS.has(message.event)) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(message.data);
      } catch {
        throw new DossierJobStreamError("protocol");
      }
      const job = parseJobSnapshot(parsed, jobId);
      if (!job) throw new DossierJobStreamError("protocol");
      handlers.onSnapshot(job, {
        event: message.event as DossierJobStreamEventName,
        eventId: message.id || null,
      });
      // El servidor cierra tras un estado terminal; ese cierre ya no es un error.
      if (TERMINAL_STATUSES.has(job.status)) finish();
    },
    onclose() {
      if (!finished) throw new DossierJobStreamError("unexpected_eof");
    },
    onerror(err: unknown) {
      // Lanzar detiene la librería: sin esto reintenta cada segundo para siempre.
      throw err instanceof DossierJobStreamError ? err : new DossierJobStreamError("network");
    },
  }).catch((err: unknown) => {
    fail(err instanceof DossierJobStreamError ? err : new DossierJobStreamError("network"));
  });

  return subscription;
}
