import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DossierApiError, fetchDashboardSummary, persistAuthToken } from "./dossier-api";

const RESUMEN = {
  as_of: "2026-10-03T15:00:00Z",
  timezone: "UTC",
  upcoming: { state: "ok", reason: null, measured_from: null, measured_to: null, from: "a", to: "b",
    eligible_meetings: 5, prepared_meetings: 3, pending_meetings: 2, coverage_percent: 60 },
  history: { state: "ok", reason: null, measured_from: null, measured_to: null, from: "a", to: "b",
    eligible_meetings: 8, manually_prepared_on_time_meetings: 6, on_time_percent: 75, manual_on_time_dossiers: 11 },
  credits: { state: "ok", reason: null, measured_from: null, measured_to: null, balance: 42, monthly_limit: 500 },
};

function respuesta(cuerpo: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(cuerpo), { status, headers: { "Content-Type": "application/json" } }));
}

describe("fetchDashboardSummary", () => {
  beforeEach(() => persistAuthToken("jwt-de-prueba", true));
  afterEach(() => vi.unstubAllGlobals());

  it("pide /dashboard/summary con el JWT y sin parámetros de usuario ni organización", async () => {
    const fetchMock = vi.fn().mockImplementation(() => respuesta(RESUMEN));
    vi.stubGlobal("fetch", fetchMock);
    const r = await fetchDashboardSummary();
    const [url, init] = fetchMock.mock.calls[0];
    const u = new URL(url as string);
    expect(u.pathname).toBe("/dashboard/summary");
    expect([...u.searchParams.keys()]).toEqual([]);
    expect((init as RequestInit).headers).toMatchObject({ Authorization: "Bearer jwt-de-prueba" });
    expect((init as RequestInit).method ?? "GET").toBe("GET");
    expect(r.upcoming.pending_meetings).toBe(2);
    expect(r.history.manual_on_time_dossiers).toBe(11);
  });

  it("sin sesión falla sin llamar a la red", async () => {
    sessionStorage.clear();
    localStorage.clear();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchDashboardSummary()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("un error HTTP se propaga como DossierApiError y nunca como ceros", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => respuesta({ detail: "caído" }, 503)));
    await expect(fetchDashboardSummary()).rejects.toBeInstanceOf(DossierApiError);
  });

  it("una respuesta sin las tres secciones se rechaza", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => respuesta({ upcoming: {} })));
    await expect(fetchDashboardSummary()).rejects.toMatchObject({ status: 502 });
  });
});
