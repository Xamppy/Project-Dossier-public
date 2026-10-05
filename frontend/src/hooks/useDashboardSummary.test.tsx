import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DossierApiError, persistAuthToken } from "@/lib/dossier-api";
import type { DashboardSummary } from "@/lib/dossier-api";
import { useDashboardSummary } from "./useDashboardSummary";

const fetchMock = vi.fn();

vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return { ...actual, fetchDashboardSummary: (...a: unknown[]) => fetchMock(...a) };
});

function resumen(pendientes: number): DashboardSummary {
  const ctx = { state: "ok" as const, reason: null, measured_from: null, measured_to: null };
  return {
    as_of: "2026-10-03T15:00:00Z", timezone: "UTC",
    upcoming: { ...ctx, from: "a", to: "b", eligible_meetings: 5, prepared_meetings: 5 - pendientes,
      pending_meetings: pendientes, coverage_percent: 60 },
    preparation_cost: { ...ctx, from: "a", to: "b", estimated_credits: 5, meetings_to_generate: 2,
    billing: "charged" as const, exceeds_balance: false },
    credits: { ...ctx, balance: 1, monthly_limit: 2 },
  };
}

function diferida<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const render = (refreshKey = "") =>
  renderHook(({ k }: { k: string }) => useDashboardSummary({ enabled: true, refreshKey: k }), {
    initialProps: { k: refreshKey },
  });

beforeEach(() => {
  fetchMock.mockReset();
  persistAuthToken("jwt-ana", true);
});

describe("useDashboardSummary", () => {
  it("carga al montar: loading → ready con el resumen", async () => {
    fetchMock.mockResolvedValue(resumen(2));
    const { result } = render();
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.summary?.upcoming.pending_meetings).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("un fallo de consulta es error y no deja datos viejos como si fueran actuales", async () => {
    fetchMock.mockRejectedValue(new DossierApiError(503, "caído"));
    const { result } = render();
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.summary).toBeNull();
  });

  it("deshabilitado (sin sesión) no consulta", () => {
    const { result } = renderHook(() => useDashboardSummary({ enabled: false, refreshKey: "" }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.status).toBe("idle");
  });

  it("deduplica refrescos simultáneos: una sola petición en vuelo", async () => {
    const d = diferida<DashboardSummary>();
    fetchMock.mockReturnValue(d.promise);
    const { result } = render();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => {
      void result.current.refresh();
      void result.current.refresh();
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => d.resolve(resumen(1)));
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  it("al volver a la pestaña refresca", async () => {
    fetchMock.mockResolvedValue(resumen(2));
    const { result } = render();
    await waitFor(() => expect(result.current.status).toBe("ready"));
    fetchMock.mockResolvedValue(resumen(1));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(result.current.summary?.upcoming.pending_meetings).toBe(1));
  });

  it("CA13: al completarse una generación (cambia refreshKey) vuelve a consultar", async () => {
    fetchMock.mockResolvedValue(resumen(2));
    const { result, rerender } = render("");
    await waitFor(() => expect(result.current.status).toBe("ready"));
    fetchMock.mockResolvedValue(resumen(1));
    rerender({ k: "job-1" });
    await waitFor(() => expect(result.current.summary?.upcoming.pending_meetings).toBe(1));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("un cambio de refreshKey durante una petición en vuelo provoca una nueva consulta después", async () => {
    const d1 = diferida<DashboardSummary>();
    fetchMock.mockReturnValueOnce(d1.promise).mockResolvedValue(resumen(0));
    const { result, rerender } = render("");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    rerender({ k: "job-1" }); // la respuesta en vuelo pudo leerse antes de terminar la generación
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => d1.resolve(resumen(2)));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.summary?.upcoming.pending_meetings).toBe(0));
  });

  it("CA13: una respuesta antigua no sobrescribe los datos de otra sesión u organización", async () => {
    const vieja = diferida<DashboardSummary>();
    fetchMock.mockReturnValueOnce(vieja.promise);
    const { result } = render();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    persistAuthToken("jwt-otra-org", true); // cambió la sesión/organización mientras se esperaba
    fetchMock.mockResolvedValue(resumen(4));
    await act(async () => {
      window.dispatchEvent(new Event("dossier:auth-me-changed"));
    });
    await waitFor(() => expect(result.current.summary?.upcoming.pending_meetings).toBe(4));

    await act(async () => vieja.resolve(resumen(99))); // llega tarde la de la sesión anterior
    expect(result.current.summary?.upcoming.pending_meetings).toBe(4);
  });

  it("al deshabilitarse (cierre de sesión) descarta los datos", async () => {
    fetchMock.mockResolvedValue(resumen(2));
    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useDashboardSummary({ enabled: on, refreshKey: "" }),
      { initialProps: { on: true } },
    );
    await waitFor(() => expect(result.current.status).toBe("ready"));
    rerender({ on: false });
    expect(result.current.summary).toBeNull();
    expect(result.current.status).toBe("idle");
  });
});
