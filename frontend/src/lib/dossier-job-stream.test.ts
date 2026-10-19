import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DossierJobStreamError,
  openDossierJobStream,
  type DossierJobStreamHandlers,
} from "@/lib/dossier-job-stream";

// Pruebas del transporte real: la librería @microsoft/fetch-event-source corre
// de verdad y solo `fetch` está simulado. Así se comprueba el cableado (parser,
// errores, reintentos) y no un mock de la librería.

const JOB_ID = "6f1c2a8e-0000-4000-8000-000000000001";

function snapshot(over: Record<string, unknown> = {}) {
  return {
    id: JOB_ID,
    status: "running",
    job_type: "calendar_manual",
    calendar_provider: "google",
    external_event_id: "evt-1",
    meeting_label: "Reunión con Acme",
    credits_estimated: 2,
    credits_consumed: 0,
    error_message: null,
    result: null,
    created_at: "2026-10-13T10:00:00+00:00",
    started_at: "2026-10-13T10:00:01+00:00",
    completed_at: null,
    ...over,
  };
}

function frame(event: string, data: unknown, id: number): string {
  return `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** Respuesta SSE cuyo cuerpo se alimenta a mano, trozo por trozo. */
function sseBody(contentType = "text/event-stream; charset=utf-8", status = 200) {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      ctrl = c;
    },
  });
  const enc = new TextEncoder();
  return {
    response: new Response(body, { status, headers: { "Content-Type": contentType } }),
    push: (text: string) => ctrl.enqueue(enc.encode(text)),
    end: () => ctrl.close(),
  };
}

function handlers() {
  const h = {
    onSnapshot: vi.fn<DossierJobStreamHandlers["onSnapshot"]>(),
    onError: vi.fn<DossierJobStreamHandlers["onError"]>(),
  };
  return h;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.setItem("dossier_access_token", "tok-123");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe("openDossierJobStream · conexión", () => {
  it("abre el stream con prefijo de API, Bearer y Accept SSE, sin token en la URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.dossier.test/api/");
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);

    const sub = openDossierJobStream(JOB_ID, handlers());

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`https://api.dossier.test/api/dossier-generation-jobs/${JOB_ID}/stream`);
    expect(url).not.toContain("tok-123");
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBe("Bearer tok-123");
    expect(headers.get("accept")).toBe("text/event-stream");
    expect(init.method ?? "GET").toBe("GET");
    sub.close();
  });

  it("sin sesión informa unauthorized sin llamar a la red", async () => {
    localStorage.clear();
    const h = handlers();

    openDossierJobStream(JOB_ID, h);

    await vi.waitFor(() => expect(h.onError).toHaveBeenCalledTimes(1));
    expect(h.onError.mock.calls[0][0].kind).toBe("unauthorized");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("openDossierJobStream · eventos", () => {
  it("entrega los snapshots de una respuesta fragmentada y cierra sin error al llegar a terminal", async () => {
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);
    const h = handlers();

    const sub = openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const running = frame("job_status", snapshot({ status: "running" }), 1);
    sse.push(running.slice(0, 7));
    sse.push(running.slice(7, 40));
    sse.push(running.slice(40));
    await vi.waitFor(() => expect(h.onSnapshot).toHaveBeenCalledTimes(1));
    expect(h.onSnapshot.mock.calls[0][0].status).toBe("running");
    expect(h.onSnapshot.mock.calls[0][1]).toEqual({ event: "job_status", eventId: "1" });
    expect(sub.lastEventId()).toBe("1");

    const done = frame(
      "job_completed",
      snapshot({ status: "completed", result: { saved_dossiers: { folder: { id: "f-1" } } } }),
      2,
    );
    sse.push(done.slice(0, 25));
    sse.push(done.slice(25));
    sse.end();

    await vi.waitFor(() => expect(h.onSnapshot).toHaveBeenCalledTimes(2));
    const [job, meta] = h.onSnapshot.mock.calls[1];
    expect(job.status).toBe("completed");
    expect(job.result).toEqual({ saved_dossiers: { folder: { id: "f-1" } } });
    expect(meta.event).toBe("job_completed");
    await new Promise((r) => setTimeout(r, 20));
    expect(h.onError).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("job_failed con status cancelled conserva la cancelación del payload", async () => {
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);
    const h = handlers();

    openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    sse.push(frame("job_failed", snapshot({ status: "cancelled" }), 3));
    sse.end();

    await vi.waitFor(() => expect(h.onSnapshot).toHaveBeenCalledTimes(1));
    expect(h.onSnapshot.mock.calls[0][0].status).toBe("cancelled");
    expect(h.onSnapshot.mock.calls[0][1].event).toBe("job_failed");
    await new Promise((r) => setTimeout(r, 20));
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("ignora heartbeat, agent_progress y eventos desconocidos", async () => {
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);
    const h = handlers();

    const sub = openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    sse.push(": ping\n\n");
    sse.push(frame("agent_progress", { dossier_id: JOB_ID, agent: "uk", status: "failed" }, 4));
    sse.push(frame("evento_nuevo", { cualquier: "cosa" }, 5));
    sse.push(frame("job_status", snapshot({ status: "running" }), 6));

    await vi.waitFor(() => expect(h.onSnapshot).toHaveBeenCalledTimes(1));
    expect(h.onSnapshot.mock.calls[0][0].status).toBe("running");
    expect(h.onError).not.toHaveBeenCalled();
    sub.close();
  });
});

describe("openDossierJobStream · errores y política de reintento", () => {
  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [404, "not_found"],
    [429, "http"],
    [503, "http"],
  ] as const)("HTTP %i se informa como %s una sola vez, sin reintentos", async (status, kind) => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "x" }), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const h = handlers();

    openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(h.onError).toHaveBeenCalledTimes(1));
    const err = h.onError.mock.calls[0][0];
    expect(err).toBeInstanceOf(DossierJobStreamError);
    expect(err.kind).toBe(kind);
    expect(err.status).toBe(status);

    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onSnapshot).not.toHaveBeenCalled();
  });

  it("200 con Content-Type distinto de text/event-stream es fallo de protocolo", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html></html>", { status: 200, headers: { "Content-Type": "text/html" } }),
    );
    const h = handlers();

    openDossierJobStream(JOB_ID, h);

    await vi.waitFor(() => expect(h.onError).toHaveBeenCalledTimes(1));
    expect(h.onError.mock.calls[0][0].kind).toBe("protocol");
  });

  it("fallo de red al conectar se informa como network sin reintentar", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const h = handlers();

    openDossierJobStream(JOB_ID, h);

    await vi.waitFor(() => expect(h.onError).toHaveBeenCalledTimes(1));
    expect(h.onError.mock.calls[0][0].kind).toBe("network");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("cierre del servidor sin estado terminal es unexpected_eof, no un job fallido", async () => {
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);
    const h = handlers();

    openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    sse.push(frame("job_status", snapshot({ status: "running" }), 1));
    sse.end();

    await vi.waitFor(() => expect(h.onError).toHaveBeenCalledTimes(1));
    expect(h.onError.mock.calls[0][0].kind).toBe("unexpected_eof");
    expect(h.onSnapshot).toHaveBeenCalledTimes(1);
    expect(h.onSnapshot.mock.calls[0][0].status).toBe("running");
  });

  it.each([
    ["JSON inválido", "id: 1\nevent: job_status\ndata: {no-es-json\n\n"],
    ["id ajeno", frame("job_status", snapshot({ id: "otro-job" }), 1)],
    ["estado desconocido", frame("job_status", snapshot({ status: "pausado" }), 1)],
    ["sin job_type", frame("job_completed", { id: JOB_ID, status: "completed" }, 1)],
  ])("%s en un evento conocido es fallo de protocolo, sin aplicar ni reintentar", async (_caso, raw) => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);
    const h = handlers();

    openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    sse.push(raw);

    await vi.waitFor(() => expect(h.onError).toHaveBeenCalledTimes(1));
    expect(h.onError.mock.calls[0][0].kind).toBe("protocol");
    expect(h.onSnapshot).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("openDossierJobStream · ciclo de vida", () => {
  it("close() aborta la petición y silencia eventos y errores posteriores", async () => {
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);
    const h = handlers();

    const sub = openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = fetchMock.mock.calls[0][1] as RequestInit;

    sub.close();
    expect(init.signal?.aborted).toBe(true);
    await new Promise((r) => setTimeout(r, 20));
    expect(h.onSnapshot).not.toHaveBeenCalled();
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("cambiar la visibilidad de la pestaña no cierra ni reabre la conexión", async () => {
    const sse = sseBody();
    fetchMock.mockResolvedValue(sse.response);
    const h = handlers();

    const sub = openDossierJobStream(JOB_ID, h);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = fetchMock.mock.calls[0][1] as RequestInit;

    document.dispatchEvent(new Event("visibilitychange"));
    await new Promise((r) => setTimeout(r, 20));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(init.signal?.aborted).toBe(false);
    sse.push(frame("job_status", snapshot({ status: "running" }), 1));
    await vi.waitFor(() => expect(h.onSnapshot).toHaveBeenCalledTimes(1));
    sub.close();
  });
});
