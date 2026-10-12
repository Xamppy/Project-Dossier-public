import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCalendarProvidersConfigured } from "./useCalendarProvidersConfigured";

const consulta = vi.fn();

vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return { ...actual, fetchCalendarProviderConfigured: (p: string) => consulta(p) };
});

beforeEach(() => {
  consulta.mockReset();
});

describe("useCalendarProvidersConfigured", () => {
  it("parte en desconocido (null) para no ocultar nada mientras carga", () => {
    consulta.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useCalendarProvidersConfigured());
    expect(result.current).toEqual({ google: null, microsoft: null });
  });

  it("refleja lo que informa el servidor por proveedor", async () => {
    consulta.mockImplementation(async (p: string) => p === "google");
    const { result } = renderHook(() => useCalendarProvidersConfigured());
    await waitFor(() => expect(result.current).toEqual({ google: true, microsoft: false }));
  });

  it("si la consulta de un proveedor falla, queda desconocido y no se oculta", async () => {
    consulta.mockImplementation(async (p: string) => {
      if (p === "microsoft") throw new Error("red caída");
      return true;
    });
    const { result } = renderHook(() => useCalendarProvidersConfigured());
    await waitFor(() => expect(result.current.google).toBe(true));
    expect(result.current.microsoft).toBeNull();
  });
});
