import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import type { DossierGenerationJobApi } from "@/lib/dossier-api";
import { DossierJobsProvider } from "./DossierJobsProvider";

// Prueba de red de S5.1 (CA3/CA12): cliente HTTP y adaptador SSE reales, solo
// `fetch` simulado. Se cuenta cada petición que sale del proveedor, montado
// aislado para que NotificationsProvider (S5.2) no contamine el recuento.

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return {
    useTranslation: () => ({ t, locale: "es" }),
    usePreferences: () => ({ preferences: { locale: "es", outputLanguage: "match", timezone: "UTC" } }),
  };
});
vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

const API = "https://api.dossier.test/api";

const ACTIVOS: DossierGenerationJobApi[] = [
  { id: "cal-google", status: "running", job_type: "calendar_manual", calendar_provider: "google" },
  { id: "cal-outlook", status: "queued", job_type: "calendar_manual", calendar_provider: "microsoft" },
  { id: "persona-pdl", status: "running", job_type: "person_manual", calendar_provider: null },
  { id: "persona-web", status: "queued", job_type: "person_manual", calendar_provider: null },
];

type Llamada = { method: string; url: string };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Stream abierto que envía el estado actual y no se cierra (job en curso). */
function sseAbierto(job: DossierGenerationJobApi) {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(enc.encode(`id: 1\nevent: job_status\ndata: ${JSON.stringify(job)}\n\n`));
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

let llamadas: Llamada[];

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", API);
  localStorage.setItem("dossier_access_token", "tok");
  llamadas = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      llamadas.push({ method: init?.method ?? "GET", url });
      if (url === `${API}/dossier-generation-jobs`) return json({ jobs: ACTIVOS });
      const stream = url.match(/\/dossier-generation-jobs\/([^/]+)\/stream$/);
      if (stream) {
        const job = ACTIVOS.find((j) => j.id === stream[1]);
        return job ? sseAbierto(job) : json({ detail: "Job no encontrado." }, 404);
      }
      const uno = url.match(/\/dossier-generation-jobs\/([^/]+)$/);
      if (uno) {
        const job = ACTIVOS.find((j) => j.id === uno[1]);
        return job ? json(job) : json({ detail: "Job no encontrado." }, 404);
      }
      throw new Error(`Petición inesperada en la prueba: ${url}`);
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const esListado = (c: Llamada) => c.url === `${API}/dossier-generation-jobs`;
const esStream = (c: Llamada) => c.url.endsWith("/stream");
const esLecturaDeJob = (c: Llamada) => /\/dossier-generation-jobs\/[^/]+$/.test(c.url);

describe("DossierJobsProvider · tráfico HTTP con jobs de Calendario y Personas activos", () => {
  it("arranca con un listado y un stream por job; en 60 s no hay ninguna petición más", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    render(
      <DossierJobsProvider>
        <div />
      </DossierJobsProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(llamadas.filter(esListado)).toHaveLength(1);
    expect(llamadas.filter(esStream).map((c) => c.url).sort()).toEqual(
      ACTIVOS.map((j) => `${API}/dossier-generation-jobs/${j.id}/stream`).sort(),
    );
    const tras_arranque = llamadas.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(llamadas.length).toBe(tras_arranque);
    expect(llamadas.filter(esLecturaDeJob)).toHaveLength(0);
    expect(llamadas.every((c) => c.method === "GET")).toBe(true);
  });
});
