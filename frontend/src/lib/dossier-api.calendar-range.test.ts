import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DossierApiError, fetchCalendarEventosPorIntervalo, persistAuthToken } from "./dossier-api";

const RANGO = { desde: "2026-10-05T00:00:00-03:00", hasta: "2026-10-12T00:00:00-03:00" };

function respuesta(cuerpo: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(cuerpo), { status, headers: { "Content-Type": "application/json" } }),
  );
}

describe("fetchCalendarEventosPorIntervalo", () => {
  beforeEach(() => persistAuthToken("jwt-de-prueba", true));
  afterEach(() => vi.unstubAllGlobals());

  it("llama a la ruta del proveedor solo con desde/hasta (nunca top, dias ni incluir_pasadas)", async () => {
    const fetchMock = vi.fn().mockImplementation(() => respuesta({ total: 0, reuniones: [], mensaje: null, rango: RANGO, completo: true, motivo_incompleto: null }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchCalendarEventosPorIntervalo("google", RANGO);
    await fetchCalendarEventosPorIntervalo("microsoft", RANGO);

    const [urlG] = fetchMock.mock.calls[0];
    const [urlM, initM] = fetchMock.mock.calls[1];
    const g = new URL(urlG as string);
    const m = new URL(urlM as string);
    expect(g.pathname).toBe("/calendario/eventos-google");
    expect(m.pathname).toBe("/calendario/eventos-outlook");
    for (const u of [g, m]) {
      expect(u.searchParams.get("desde")).toBe(RANGO.desde);
      expect(u.searchParams.get("hasta")).toBe(RANGO.hasta);
      expect([...u.searchParams.keys()].sort()).toEqual(["desde", "hasta"]);
    }
    expect((initM as RequestInit).headers).toMatchObject({ Authorization: "Bearer jwt-de-prueba" });
  });

  it("devuelve reuniones, rango, completo y motivo", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        respuesta({
          total: 1,
          reuniones: [{ id: "a", tema: "x" }],
          mensaje: "Hay más reuniones de las que se pueden cargar",
          rango: RANGO,
          completo: false,
          motivo_incompleto: "limite_paginas",
        }),
      ),
    );
    const r = await fetchCalendarEventosPorIntervalo("google", RANGO);
    expect(r.reuniones).toHaveLength(1);
    expect(r.completo).toBe(false);
    expect(r.motivoIncompleto).toBe("limite_paginas");
    expect(r.rango).toEqual(RANGO);
  });

  it("un servidor antiguo sin los campos nuevos se considera completo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => respuesta({ total: 0, reuniones: [], mensaje: null })));
    const r = await fetchCalendarEventosPorIntervalo("google", RANGO);
    expect(r.completo).toBe(true);
    expect(r.motivoIncompleto).toBeNull();
  });

  it.each([404, 422, 502, 504])("propaga el estado %s como DossierApiError", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => respuesta({ detail: "motivo" }, status)));
    await expect(fetchCalendarEventosPorIntervalo("google", RANGO)).rejects.toMatchObject({
      name: "DossierApiError",
      status,
      message: "motivo",
    });
  });

  it("sin sesión falla con 401 sin llamar a la red", async () => {
    localStorage.clear();
    sessionStorage.clear();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchCalendarEventosPorIntervalo("google", RANGO)).rejects.toBeInstanceOf(DossierApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("pasa la señal de cancelación y deja pasar el AbortError tal cual", async () => {
    const ctrl = new AbortController();
    const fetchMock = vi.fn().mockImplementation((_u: string, init: RequestInit) => {
      expect(init.signal).toBe(ctrl.signal);
      return new Promise((_res, rej) => {
        init.signal?.addEventListener("abort", () => rej(new DOMException("abortado", "AbortError")));
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const p = fetchCalendarEventosPorIntervalo("google", RANGO, { signal: ctrl.signal });
    ctrl.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });

  it("un fallo de red sin cancelación es un DossierApiError de red", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(fetchCalendarEventosPorIntervalo("google", RANGO)).rejects.toMatchObject({ status: 0 });
  });
});
