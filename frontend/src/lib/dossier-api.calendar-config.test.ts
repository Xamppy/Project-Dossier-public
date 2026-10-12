import { afterEach, describe, expect, it, vi } from "vitest";

import { DossierApiError, fetchCalendarProviderConfigured } from "./dossier-api";

/**
 * Si el OAuth de un calendario no está configurado en el servidor, el dashboard oculta
 * su conexión: el botón solo llevaba a un error 500 de /integrations/{provider}/start.
 */

function respondeCon(body: unknown, status = 200) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchCalendarProviderConfigured", () => {
  it("consulta el oauth-config público del proveedor, sin token", async () => {
    const fetchSpy = respondeCon({ configured: true });

    await fetchCalendarProviderConfigured("microsoft");

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit | undefined];
    expect(url).toMatch(/\/integrations\/microsoft\/oauth-config$/);
    expect(JSON.stringify(init?.headers ?? {})).not.toMatch(/Authorization/);
  });

  it("devuelve configured tal cual", async () => {
    respondeCon({ configured: false, client_id_configured: true });
    expect(await fetchCalendarProviderConfigured("google")).toBe(false);

    respondeCon({ configured: true });
    expect(await fetchCalendarProviderConfigured("google")).toBe(true);
  });

  it("con una API anterior sin configured, usa client_id_configured", async () => {
    respondeCon({ client_id_configured: true });
    expect(await fetchCalendarProviderConfigured("microsoft")).toBe(true);
  });

  it("si la API responde error, lanza DossierApiError", async () => {
    respondeCon({ detail: "fallo" }, 500);
    await expect(fetchCalendarProviderConfigured("microsoft")).rejects.toBeInstanceOf(DossierApiError);
  });
});
