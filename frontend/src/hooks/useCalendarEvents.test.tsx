import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DossierApiError, persistAuthToken } from "@/lib/dossier-api";
import type { CalendarEventosRangoResponse } from "@/lib/dossier-api";
import { clearCalendarEventsCache } from "@/lib/calendar-events-cache";
import { useCalendarEvents } from "./useCalendarEvents";

const fetchMock = vi.fn();

vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return { ...actual, fetchCalendarEventosPorIntervalo: (...a: unknown[]) => fetchMock(...a) };
});

const W1 = { desde: "2026-10-05T00:00:00-03:00", hasta: "2026-10-12T00:00:00-03:00" };
const W2 = { desde: "2026-10-12T00:00:00-03:00", hasta: "2026-10-19T00:00:00-03:00" };
const TZ = "America/Santiago";

function ok(reuniones: { id: string; tema?: string }[], extra: Partial<CalendarEventosRangoResponse> = {}): CalendarEventosRangoResponse {
  return {
    total: reuniones.length,
    reuniones: reuniones.map((r) => ({ inicio: "2026-10-06T13:00:00Z", fin: "2026-10-06T14:00:00Z", tema: r.id, ...r })),
    mensaje: null,
    rango: null,
    completo: true,
    motivoIncompleto: null,
    ...extra,
  };
}

/** Promesa controlable desde la prueba. */
function diferida<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function porProveedor(g: () => Promise<CalendarEventosRangoResponse>, m: () => Promise<CalendarEventosRangoResponse>) {
  fetchMock.mockImplementation((provider: string) => (provider === "google" ? g() : m()));
}

function render(window: typeof W1 | null = W1, tz = TZ) {
  return renderHook(
    ({ w, z }: { w: typeof W1 | null; z: string }) => useCalendarEvents({ window: w, timezone: z, fallbackTitle: "Sin asunto" }),
    { initialProps: { w: window, z: tz } },
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  clearCalendarEventsCache();
  persistAuthToken("jwt-ana", true);
});
afterEach(() => clearCalendarEventsCache());

describe("useCalendarEvents", () => {
  it("consulta ambos proveedores en paralelo con la ventana visible (CA1)", async () => {
    const g = diferida<CalendarEventosRangoResponse>();
    const m = diferida<CalendarEventosRangoResponse>();
    porProveedor(() => g.promise, () => m.promise);
    const { result } = render();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2)); // ambos en vuelo antes de resolver ninguno
    expect(fetchMock.mock.calls.map((c) => c[0]).sort()).toEqual(["google", "microsoft"]);
    expect(fetchMock.mock.calls[0][1]).toEqual(W1);
    expect(result.current.loading).toBe(true);

    await act(async () => {
      g.resolve(ok([{ id: "g1" }]));
      m.resolve(ok([{ id: "m1" }]));
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.events.map((e) => e.key).sort()).toEqual(["google:g1", "microsoft:m1"]);
  });

  it("un período vacío es 'ready' con cero eventos, no 'desconectado' (CA5)", async () => {
    porProveedor(async () => ok([]), async () => ok([]));
    const { result } = render();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.google.status).toBe("ready");
    expect(result.current.microsoft.status).toBe("ready");
    expect(result.current.events).toEqual([]);
  });

  it("si Google falla y Outlook responde se ven los eventos de Outlook más el error de Google (CA5)", async () => {
    porProveedor(
      async () => {
        throw new DossierApiError(502, "Google no responde");
      },
      async () => ok([{ id: "m1" }]),
    );
    const { result } = render();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.google).toMatchObject({
      status: "error",
      error: { status: 502, message: "Google no responde" },
    });
    expect(result.current.microsoft.status).toBe("ready");
    expect(result.current.events.map((e) => e.key)).toEqual(["microsoft:m1"]);
  });

  it("404 y 403 significan desconectado; un 502 es un error distinto (CA5)", async () => {
    porProveedor(
      async () => {
        throw new DossierApiError(404, "No hay Google Calendar conectado");
      },
      async () => {
        throw new DossierApiError(403, "La integración está revocada");
      },
    );
    const { result } = render();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.google.status).toBe("disconnected");
    expect(result.current.microsoft.status).toBe("disconnected");
  });

  it("propaga la carga incompleta de cada proveedor con su motivo", async () => {
    porProveedor(
      async () => ok([{ id: "g1" }], { completo: false, motivoIncompleto: "limite_paginas" }),
      async () => ok([{ id: "m1" }]),
    );
    const { result } = render();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.google).toMatchObject({ status: "ready", incomplete: "limite_paginas" });
    expect(result.current.microsoft.incomplete).toBeNull();
    expect(result.current.events).toHaveLength(2); // conserva lo recuperado
  });

  it("cuenta los registros no representables y no rompe la vista", async () => {
    porProveedor(
      async () => ok([{ id: "bueno" }, { id: "malo", inicio: "???" } as never]),
      async () => ok([]),
    );
    const { result } = render();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.events.map((e) => e.eventId)).toEqual(["bueno"]);
    expect(result.current.discarded).toBe(1);
  });

  it("una respuesta lenta del período anterior no reemplaza la del actual (CA6)", async () => {
    const lentoG = diferida<CalendarEventosRangoResponse>();
    const lentoM = diferida<CalendarEventosRangoResponse>();
    let llamada = 0;
    fetchMock.mockImplementation((provider: string, w: typeof W1) => {
      if (w.desde === W1.desde) return provider === "google" ? lentoG.promise : lentoM.promise;
      llamada += 1;
      return Promise.resolve(ok([{ id: `nuevo-${provider}` }]));
    });
    const { result, rerender } = render(W1);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    rerender({ w: W2, z: TZ }); // el usuario navega antes de que respondan
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.events.map((e) => e.key).sort()).toEqual(["google:nuevo-google", "microsoft:nuevo-microsoft"]);

    await act(async () => {
      lentoG.resolve(ok([{ id: "viejo-g" }]));
      lentoM.resolve(ok([{ id: "viejo-m" }]));
    });
    expect(result.current.events.map((e) => e.key).sort()).toEqual(["google:nuevo-google", "microsoft:nuevo-microsoft"]);
    expect(llamada).toBe(2);
  });

  it("cancela con AbortSignal las peticiones reemplazadas y las pendientes al desmontar", async () => {
    const señales: AbortSignal[] = [];
    fetchMock.mockImplementation((_p: string, _w: unknown, opts?: { signal?: AbortSignal }) => {
      if (opts?.signal) señales.push(opts.signal);
      return new Promise(() => {});
    });
    const { rerender, unmount } = render(W1);
    await waitFor(() => expect(señales).toHaveLength(2));
    rerender({ w: W2, z: TZ });
    await waitFor(() => expect(señales).toHaveLength(4));
    expect(señales.slice(0, 2).every((s) => s.aborted)).toBe(true);
    expect(señales.slice(2).every((s) => !s.aborted)).toBe(true);
    unmount();
    expect(señales.every((s) => s.aborted)).toBe(true);
  });

  it("no refetch al volver a una ventana ya consultada; refresh() fuerza la consulta", async () => {
    porProveedor(async () => ok([{ id: "g" }]), async () => ok([]));
    const { result, rerender } = render(W1);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(2);

    rerender({ w: W2, z: TZ });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ w: W1, z: TZ });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(4); // W1 salió de la caché

    await act(async () => result.current.refresh());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
  });

  it("la zona horaria forma parte de la clave de caché", async () => {
    porProveedor(async () => ok([]), async () => ok([]));
    const { result, rerender } = render(W1, "America/Santiago");
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ w: W1, z: "Europe/London" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });

  it("otro usuario nunca recibe la caché del anterior (CA6)", async () => {
    porProveedor(async () => ok([{ id: "secreto-de-ana" }]), async () => ok([]));
    const a = render(W1);
    await waitFor(() => expect(a.result.current.loading).toBe(false));
    expect(a.result.current.events[0].eventId).toBe("secreto-de-ana");
    a.unmount();

    persistAuthToken("jwt-beto", true); // cambia la sesión sin cerrar sesión explícitamente
    porProveedor(async () => ok([{ id: "de-beto" }]), async () => ok([]));
    const b = render(W1);
    await waitFor(() => expect(b.result.current.loading).toBe(false));
    expect(b.result.current.events.map((e) => e.eventId)).toEqual(["de-beto"]);
    expect(fetchMock).toHaveBeenCalledTimes(4); // volvió a consultar: la caché de Ana no se reutilizó
  });

  it("cerrar sesión (clearCalendarEventsCache) vacía la caché", async () => {
    porProveedor(async () => ok([]), async () => ok([]));
    const { result, rerender } = render(W1);
    await waitFor(() => expect(result.current.loading).toBe(false));
    clearCalendarEventsCache();
    rerender({ w: null, z: TZ });
    rerender({ w: W1, z: TZ });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });

  it("no cachea cargas incompletas ni errores", async () => {
    porProveedor(
      async () => ok([{ id: "g" }], { completo: false, motivoIncompleto: "tiempo_agotado" }),
      async () => {
        throw new DossierApiError(502, "x");
      },
    );
    const { result } = render(W1);
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => result.current.refresh());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });

  it("sin ventana o sin sesión no consulta nada", async () => {
    const sinVentana = render(null);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(sinVentana.result.current.google.status).toBe("idle");
    sinVentana.unmount();

    localStorage.clear();
    sessionStorage.clear();
    const sinSesion = render(W1);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(sinSesion.result.current.loading).toBe(false);
  });
});
