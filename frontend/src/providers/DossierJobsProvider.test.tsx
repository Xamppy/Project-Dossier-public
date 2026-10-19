import { StrictMode, useEffect } from "react";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import { AUTH_ME_CHANGED_EVENT } from "@/hooks/useAuthMe";
import { DossierApiError, type DossierGenerationJobApi } from "@/lib/dossier-api";
import {
  DossierJobStreamError,
  type DossierJobStreamErrorKind,
  type DossierJobStreamHandlers,
} from "@/lib/dossier-job-stream";
import { DossierJobsProvider, useDossierJobs } from "./DossierJobsProvider";

// El adaptador SSE se sustituye por un registro de suscripciones que la prueba
// controla: así se verifica el ciclo de vida del proveedor (cuántas conexiones,
// cuándo se cierran, qué hace con cada evento). El transporte real se prueba en
// src/lib/dossier-job-stream.test.ts.

type FakeSub = { jobId: string; handlers: DossierJobStreamHandlers; closed: boolean };

const h = vi.hoisted(() => ({
  subs: [] as FakeSub[],
  pathname: "/dashboard",
  api: {
    fetchDossierGenerationJobs: vi.fn(),
    fetchDossierGenerationJob: vi.fn(),
    cancelDossierGenerationJob: vi.fn(),
    enqueuePersonResearch: vi.fn(),
    fetchEnqueueGoogleCalendarDossier: vi.fn(),
    fetchEnqueueOutlookCalendarDossier: vi.fn(),
    createCorporateDossier: vi.fn(),
  },
}));

vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return { ...actual, ...h.api };
});
vi.mock("@/lib/dossier-job-stream", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-job-stream")>();
  return {
    ...actual,
    openDossierJobStream: (jobId: string, handlers: DossierJobStreamHandlers) => {
      const sub: FakeSub = { jobId, handlers, closed: false };
      h.subs.push(sub);
      return {
        close: () => {
          sub.closed = true;
        },
        lastEventId: () => null,
      };
    },
  };
});
vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return {
    useTranslation: () => ({ t, locale: "es" }),
    usePreferences: () => ({ preferences: { locale: "es", outputLanguage: "match", timezone: "UTC" } }),
  };
});
vi.mock("next/navigation", () => ({ usePathname: () => h.pathname }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    onClick,
  }: {
    href: string;
    children: React.ReactNode;
    onClick?: () => void;
  }) => (
    <a href={href} onClick={onClick}>
      {children}
    </a>
  ),
}));

const t = createTranslator("es");
const ACTIVE_KEY = "dossier_active_job_ids";
const TOAST_KEY = "dossier_toast_job_ids";

type JobBase = Pick<DossierGenerationJobApi, "job_type" | "calendar_provider" | "external_event_id">;

const MODES: { name: string; base: JobBase; source?: "pdl" | "gemini_web" }[] = [
  {
    name: "Calendario Google",
    base: { job_type: "calendar_manual", calendar_provider: "google", external_event_id: "evt-g" },
  },
  {
    name: "Calendario Outlook",
    base: { job_type: "calendar_manual", calendar_provider: "microsoft", external_event_id: "evt-o" },
  },
  {
    name: "Personas PDL",
    base: { job_type: "person_manual", calendar_provider: null, external_event_id: null },
    source: "pdl",
  },
  {
    name: "Personas Web pública",
    base: { job_type: "person_manual", calendar_provider: null, external_event_id: null },
    source: "gemini_web",
  },
];

function job(over: Partial<DossierGenerationJobApi> & { id: string }): DossierGenerationJobApi {
  return {
    status: "running",
    job_type: "calendar_manual",
    calendar_provider: "google",
    external_event_id: "evt",
    meeting_label: `Trabajo ${over.id}`,
    credits_estimated: 2,
    credits_consumed: 0,
    error_message: null,
    result: null,
    ...over,
  };
}

function terminalResult(base: JobBase, source?: "pdl" | "gemini_web") {
  if (base.job_type === "person_manual") {
    return {
      filters_applied: { research_source: source },
      search_attempts: [],
      profile_urls: [],
      profiles: [],
      posts_by_url: {},
      llm_analysis_markdown: "# Informe",
      warnings: [],
      saved_dossier: {
        id: `d-${source}`,
        organization_id: "o",
        status: "complete",
        credits_consumed: 1,
        generation_duration_ms: 10,
      },
    };
  }
  return {
    saved_dossiers: {
      folder: { id: "f-9" },
      person: { id: "p-9", status: "complete" },
    },
  };
}

// El contexto se captura en un efecto (no durante el render) para usarlo desde la prueba.
const probe: { value: ReturnType<typeof useDossierJobs> | null } = { value: null };
const ctx = () => {
  if (!probe.value) throw new Error("El proveedor aún no se montó");
  return probe.value;
};

function Probe() {
  const value = useDossierJobs();
  useEffect(() => {
    probe.value = value;
  });
  return (
    <ul>
      {value.jobs.map((j) => (
        <li key={j.id} data-testid={`job-${j.id}`}>
          {j.status}
        </li>
      ))}
    </ul>
  );
}

function renderProvider(strict = false) {
  const tree = (
    <DossierJobsProvider>
      <Probe />
    </DossierJobsProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

const statusOf = (id: string) => screen.queryByTestId(`job-${id}`)?.textContent ?? null;
const subsFor = (id: string) => h.subs.filter((s) => s.jobId === id);
const openSubs = (id: string) => subsFor(id).filter((s) => !s.closed);

function emit(snapshot: DossierGenerationJobApi, event = "job_status", eventId = "1") {
  const [sub] = openSubs(snapshot.id);
  if (!sub) throw new Error(`No hay stream abierto para ${snapshot.id}`);
  act(() => {
    sub.handlers.onSnapshot(snapshot, {
      event: event as "job_status" | "job_completed" | "job_failed",
      eventId,
    });
  });
}

function streamError(id: string, kind: DossierJobStreamErrorKind, status: number | null = null) {
  const [sub] = openSubs(id);
  if (!sub) throw new Error(`No hay stream abierto para ${id}`);
  act(() => {
    sub.handlers.onError(new DossierJobStreamError(kind, status));
  });
}

function stored(key: string): string[] {
  return JSON.parse(sessionStorage.getItem(key) ?? "[]") as string[];
}

beforeEach(() => {
  h.subs.length = 0;
  h.pathname = "/dashboard";
  for (const fn of Object.values(h.api)) fn.mockReset();
  h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [] });
  h.api.fetchDossierGenerationJob.mockRejectedValue(new DossierApiError(404, "Job no encontrado."));
  localStorage.setItem("dossier_access_token", "tok");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DossierJobsProvider · estado general por SSE", () => {
  it.each(MODES)(
    "CA1 · $name: abre un stream por job remoto activo y aplica su snapshot",
    async ({ base }) => {
      h.api.fetchDossierGenerationJobs.mockResolvedValue({
        jobs: [job({ id: "j1", status: "queued", ...base })],
      });
      renderProvider();
      await settle();

      expect(openSubs("j1")).toHaveLength(1);
      emit(job({ id: "j1", status: "running", ...base }));
      expect(statusOf("j1")).toBe("running");
    },
  );

  it.each(MODES)(
    "CA2 · $name: los eventos actualizan el job sin consultar su endpoint REST",
    async ({ base, source }) => {
      h.api.fetchDossierGenerationJobs.mockResolvedValue({
        jobs: [job({ id: "j1", status: "queued", ...base })],
      });
      renderProvider();
      await settle();
      const restBefore = h.api.fetchDossierGenerationJob.mock.calls.length;

      emit(job({ id: "j1", status: "running", ...base }), "job_status", "1");
      emit(
        job({
          id: "j1",
          status: "completed",
          credits_consumed: 2,
          result: terminalResult(base, source) as DossierGenerationJobApi["result"],
          ...base,
        }),
        "job_completed",
        "2",
      );

      expect(statusOf("j1")).toBe("completed");
      expect(ctx().jobs.find((j) => j.id === "j1")?.credits_consumed).toBe(2);
      expect(h.api.fetchDossierGenerationJob.mock.calls.length).toBe(restBefore);
      const link = screen.getByRole("link");
      expect(link).toHaveAttribute(
        "href",
        base.job_type === "person_manual" ? `/dashboard/dossiers/d-${source}` : "/dashboard/dossiers/folder/f-9",
      );
    },
  );

  it("CA3 · con jobs activos, 60 s de reloj no producen lecturas REST periódicas", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    h.api.fetchDossierGenerationJobs.mockResolvedValue({
      jobs: MODES.map((m, i) => job({ id: `j${i}`, status: "running", ...m.base })),
    });
    renderProvider();
    await settle();
    const listCalls = h.api.fetchDossierGenerationJobs.mock.calls.length;
    const oneCalls = h.api.fetchDossierGenerationJob.mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(h.api.fetchDossierGenerationJobs.mock.calls.length).toBe(listCalls);
    expect(h.api.fetchDossierGenerationJob.mock.calls.length).toBe(oneCalls);
  });

  it("CA4 · con StrictMode y varias actualizaciones hay una sola suscripción vigente por job", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({
      jobs: MODES.map((m, i) => job({ id: `j${i}`, status: "queued", ...m.base })),
    });
    h.api.fetchEnqueueGoogleCalendarDossier.mockResolvedValue({
      async: true,
      job_id: "nuevo",
      status: "queued",
      credits_estimated: 2,
    });
    renderProvider(true);
    await settle();

    for (let i = 0; i < MODES.length; i++) expect(openSubs(`j${i}`)).toHaveLength(1);
    const created = h.subs.length;

    emit(job({ id: "j0", status: "running" }));
    emit(job({ id: "j0", status: "running", credits_consumed: 1 }));
    emit(job({ id: "j2", status: "running", ...MODES[2].base }));
    await settle();
    expect(h.subs.length).toBe(created);

    await act(async () => {
      await ctx().enqueueCalendarJob("google", { eventId: "evt-n" });
    });
    expect(openSubs("nuevo")).toHaveLength(1);
    expect(h.subs.length).toBe(created + 1);
    for (let i = 0; i < MODES.length; i++) expect(openSubs(`j${i}`)).toHaveLength(1);
  });

  it.each([
    ["completed", "job_completed", "dossier_jobs.ready"],
    ["failed", "job_failed", "dossier_jobs.failed"],
    ["cancelled", "job_failed", "dossier_jobs.cancelled"],
  ] as const)(
    "CA5 · %s llegado por %s cierra el stream sin reabrirlo y respeta el estado del payload",
    async (status, event, toastKey) => {
      h.api.fetchDossierGenerationJobs.mockResolvedValue({
        jobs: [job({ id: "j1", status: "running" })],
      });
      renderProvider();
      await settle();

      emit(job({ id: "j1", status }), event);
      await settle();

      expect(statusOf("j1")).toBe(status);
      expect(openSubs("j1")).toHaveLength(0);
      expect(subsFor("j1")).toHaveLength(1);
      expect(screen.getByText(t(toastKey))).toBeInTheDocument();
      if (status === "cancelled") {
        expect(screen.queryByText(t("dossier_jobs.failed"))).not.toBeInTheDocument();
      }
    },
  );

  it("CA6 · desmontar cierra todos los streams y los callbacks tardíos no hacen nada", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({
      jobs: [job({ id: "a" }), job({ id: "b", ...MODES[2].base })],
    });
    const { unmount } = renderProvider();
    await settle();
    const subs = [...h.subs];
    expect(subs).toHaveLength(2);

    unmount();

    expect(subs.every((s) => s.closed)).toBe(true);
    expect(() =>
      act(() => {
        subs[0].handlers.onSnapshot(job({ id: "a", status: "completed" }), {
          event: "job_completed",
          eventId: "2",
        });
        subs[1].handlers.onError(new DossierJobStreamError("network"));
      }),
    ).not.toThrow();
  });

  it("CA6 · un cambio de sesión invalida streams y no conserva jobs de la identidad anterior", async () => {
    h.api.fetchDossierGenerationJobs
      .mockResolvedValueOnce({ jobs: [job({ id: "de-a", status: "running" })] })
      .mockResolvedValueOnce({ jobs: [job({ id: "de-b", status: "queued", ...MODES[3].base })] });
    renderProvider();
    await settle();
    const [anterior] = openSubs("de-a");
    expect(stored(ACTIVE_KEY)).toEqual(["de-a"]);

    await act(async () => {
      window.dispatchEvent(new Event(AUTH_ME_CHANGED_EVENT));
      await new Promise((r) => setTimeout(r, 0));
    });
    await settle();

    expect(anterior.closed).toBe(true);
    act(() => {
      anterior.handlers.onSnapshot(job({ id: "de-a", status: "completed" }), {
        event: "job_completed",
        eventId: "9",
      });
    });
    expect(statusOf("de-a")).toBeNull();
    expect(statusOf("de-b")).toBe("queued");
    expect(openSubs("de-b")).toHaveLength(1);
    expect(stored(ACTIVE_KEY)).toEqual(["de-b"]);
  });

  it("CA7 · una restauración tardía no pierde el job recién encolado ni revierte su estado", async () => {
    let resolveList!: (v: { jobs: DossierGenerationJobApi[] }) => void;
    h.api.fetchDossierGenerationJobs.mockReturnValue(
      new Promise((r) => {
        resolveList = r;
      }),
    );
    h.api.enqueuePersonResearch.mockResolvedValue({
      async: true,
      job_id: "nuevo",
      status: "queued",
      credits_estimated: 1,
    });
    renderProvider();

    await act(async () => {
      await ctx().enqueuePersonResearchJob({ full_name: "Ada Lovelace", research_source: "pdl" });
    });
    expect(openSubs("nuevo")).toHaveLength(1);
    emit(job({ id: "nuevo", status: "running", ...MODES[2].base }));

    await act(async () => {
      resolveList({
        jobs: [
          job({ id: "previo", status: "running" }),
          job({ id: "nuevo", status: "queued", ...MODES[2].base }),
        ],
      });
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(statusOf("nuevo")).toBe("running");
    expect(statusOf("previo")).toBe("running");
    expect(stored(ACTIVE_KEY).sort()).toEqual(["nuevo", "previo"]);
    expect(openSubs("nuevo")).toHaveLength(1);
    expect(openSubs("previo")).toHaveLength(1);
  });

  it("CA7 · los IDs restaurados que dan 404 se depuran del almacenamiento", async () => {
    sessionStorage.setItem(ACTIVE_KEY, JSON.stringify(["vencido", "vivo"]));
    h.api.fetchDossierGenerationJob.mockImplementation(async (id: string) => {
      if (id === "vivo") return job({ id: "vivo", status: "running" });
      throw new DossierApiError(404, "Job no encontrado.");
    });
    renderProvider();
    await settle();

    expect(statusOf("vencido")).toBeNull();
    expect(statusOf("vivo")).toBe("running");
    expect(stored(ACTIVE_KEY)).toEqual(["vivo"]);
    expect(openSubs("vencido")).toHaveLength(0);
  });

  it("CA7 · un aviso descartado no reaparece al llegar un duplicado del estado terminal", async () => {
    let resolveList!: (v: { jobs: DossierGenerationJobApi[] }) => void;
    h.api.fetchDossierGenerationJobs.mockReturnValue(
      new Promise((r) => {
        resolveList = r;
      }),
    );
    h.api.fetchEnqueueGoogleCalendarDossier.mockResolvedValue({
      async: true,
      job_id: "c1",
      status: "queued",
      credits_estimated: 2,
    });
    renderProvider();
    await act(async () => {
      await ctx().enqueueCalendarJob("google", { eventId: "evt-1" });
    });
    emit(job({ id: "c1", status: "completed", result: terminalResult(MODES[0].base) as never }), "job_completed");
    expect(screen.getByText(t("dossier_jobs.ready"))).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: t("dossier_jobs.dismiss") }));
    expect(screen.queryByText(t("dossier_jobs.ready"))).not.toBeInTheDocument();

    await act(async () => {
      resolveList({ jobs: [job({ id: "c1", status: "completed" })] });
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(screen.queryByText(t("dossier_jobs.ready"))).not.toBeInTheDocument();
    expect(stored(TOAST_KEY)).not.toContain("c1");
  });

  it("CA8 · un fallo de protocolo no corrompe el job ni abre un bucle de conexiones", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "running" })] });
    renderProvider();
    await settle();

    streamError("j1", "protocol");
    await settle();

    expect(statusOf("j1")).toBe("running");
    expect(subsFor("j1")).toHaveLength(1);
    expect(screen.getByText(t("dossier_jobs.connection_lost"))).toBeInTheDocument();
  });

  it.each(["network", "http", "unexpected_eof"] as const)(
    "CA9 · un corte %s conserva el job activo y ofrece reconectar, sin marcarlo fallido",
    async (kind) => {
      h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "running" })] });
      renderProvider();
      await settle();

      streamError("j1", kind, kind === "http" ? 503 : null);
      await settle();

      expect(statusOf("j1")).toBe("running");
      expect(screen.getByText(t("dossier_jobs.connection_lost"))).toBeInTheDocument();
      expect(screen.getByRole("button", { name: t("dossier_jobs.reconnect") })).toBeInTheDocument();
      expect(screen.queryByText(t("dossier_jobs.failed"))).not.toBeInTheDocument();
      expect(subsFor("j1")).toHaveLength(1);
    },
  );

  it.each([
    ["unauthorized", 401],
    ["forbidden", 403],
  ] as const)("CA9 · %s detiene el stream y pide iniciar sesión, sin reconexión", async (kind, status) => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "running" })] });
    renderProvider();
    await settle();

    streamError("j1", kind, status);
    await settle();

    expect(statusOf("j1")).toBe("running");
    expect(screen.getByText(t("auth.error.session_expired"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("dossier_jobs.reconnect") })).not.toBeInTheDocument();
    expect(subsFor("j1")).toHaveLength(1);
  });

  it("CA9 · 404 en el stream retira el job del seguimiento", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({
      jobs: [job({ id: "j1", status: "running" }), job({ id: "j2", status: "running" })],
    });
    renderProvider();
    await settle();

    streamError("j1", "not_found", 404);
    await settle();

    expect(statusOf("j1")).toBeNull();
    expect(statusOf("j2")).toBe("running");
    expect(stored(ACTIVE_KEY)).toEqual(["j2"]);
  });

  it("CA10 · reconectar pide un único snapshot, acepta la secuencia reiniciada y reabre si sigue activo", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "queued" })] });
    renderProvider();
    await settle();
    emit(job({ id: "j1", status: "running" }), "job_status", "7");
    streamError("j1", "network");
    await settle();
    h.api.fetchDossierGenerationJob.mockResolvedValue(job({ id: "j1", status: "running", credits_consumed: 1 }));

    await userEvent.click(screen.getByRole("button", { name: t("dossier_jobs.reconnect") }));
    await settle();

    expect(h.api.fetchDossierGenerationJob).toHaveBeenCalledTimes(1);
    expect(h.api.fetchDossierGenerationJob).toHaveBeenCalledWith("j1");
    expect(ctx().jobs[0].credits_consumed).toBe(1);
    expect(subsFor("j1")).toHaveLength(2);
    expect(openSubs("j1")).toHaveLength(1);
    expect(screen.queryByText(t("dossier_jobs.connection_lost"))).not.toBeInTheDocument();

    emit(job({ id: "j1", status: "completed" }), "job_completed", "1");
    expect(statusOf("j1")).toBe("completed");
  });

  it("CA10 · si el snapshot de recuperación es terminal no se abre otro stream", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "running" })] });
    renderProvider();
    await settle();
    streamError("j1", "unexpected_eof");
    await settle();
    h.api.fetchDossierGenerationJob.mockResolvedValue(job({ id: "j1", status: "completed" }));

    await userEvent.click(screen.getByRole("button", { name: t("dossier_jobs.reconnect") }));
    await settle();

    expect(statusOf("j1")).toBe("completed");
    expect(subsFor("j1")).toHaveLength(1);
    expect(h.api.fetchDossierGenerationJob).toHaveBeenCalledTimes(1);
  });

  it("CA10 · si la recuperación vuelve a fallar se conserva el job y se puede reintentar", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "running" })] });
    renderProvider();
    await settle();
    streamError("j1", "network");
    await settle();
    h.api.fetchDossierGenerationJob.mockRejectedValue(new DossierApiError(0, "NETWORK"));

    await userEvent.click(screen.getByRole("button", { name: t("dossier_jobs.reconnect") }));
    await settle();

    expect(h.api.fetchDossierGenerationJob).toHaveBeenCalledTimes(1);
    expect(statusOf("j1")).toBe("running");
    expect(subsFor("j1")).toHaveLength(1);
    expect(screen.getByRole("button", { name: t("dossier_jobs.reconnect") })).toBeInTheDocument();
  });

  it("CA11 · el corporativo manual local nunca abre stream y conserva generación, enlace y créditos", async () => {
    let resolveCorp!: (v: unknown) => void;
    h.api.createCorporateDossier.mockReturnValue(
      new Promise((r) => {
        resolveCorp = r;
      }),
    );
    renderProvider();
    await settle();

    let corpId = "";
    await act(async () => {
      corpId = await ctx().enqueueCorporateDossierJob({ company_name: "Acme" } as never, "Acme", 3);
    });
    expect(statusOf(corpId)).toBe("running");
    expect(subsFor(corpId)).toHaveLength(0);

    await act(async () => {
      resolveCorp({ id: "corp-1", credits_consumed: 3 });
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(statusOf(corpId)).toBe("completed");
    expect(ctx().jobs.find((j) => j.id === corpId)?.credits_consumed).toBe(3);
    expect(screen.getByRole("link", { name: t("dossier_jobs.view_dossier") })).toHaveAttribute(
      "href",
      "/dashboard/dossiers/corp-1",
    );
    expect(h.subs).toHaveLength(0);
  });

  it("CA11 · cancelar el corporativo local aborta su petición sin llamar a la API de jobs", async () => {
    let signal: AbortSignal | undefined;
    h.api.createCorporateDossier.mockImplementation((_p: unknown, s: AbortSignal) => {
      signal = s;
      return new Promise(() => {});
    });
    renderProvider();
    await settle();
    let corpId = "";
    await act(async () => {
      corpId = await ctx().enqueueCorporateDossierJob({ company_name: "Acme" } as never, "Acme");
    });

    await act(async () => {
      await ctx().cancelJob(corpId);
    });

    expect(signal?.aborted).toBe(true);
    expect(statusOf(corpId)).toBe("cancelled");
    expect(h.api.cancelDossierGenerationJob).not.toHaveBeenCalled();
  });

  it("CA11 · cancelar un job remoto usa la API y cierra su stream", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "running" })] });
    h.api.cancelDossierGenerationJob.mockResolvedValue(job({ id: "j1", status: "cancelled" }));
    renderProvider();
    await settle();

    await userEvent.click(screen.getByRole("button", { name: t("dossier_jobs.cancel") }));
    await settle();

    expect(h.api.cancelDossierGenerationJob).toHaveBeenCalledWith("j1");
    expect(statusOf("j1")).toBe("cancelled");
    expect(openSubs("j1")).toHaveLength(0);
  });

  it("CA11 · si cancelar falla se conserva el job, su stream y se muestra el error", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [job({ id: "j1", status: "running" })] });
    h.api.cancelDossierGenerationJob.mockRejectedValue(new DossierApiError(500, "No se pudo cancelar"));
    renderProvider();
    await settle();

    await userEvent.click(screen.getByRole("button", { name: t("dossier_jobs.cancel") }));
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cancelar");
    expect(statusOf("j1")).toBe("running");
    expect(openSubs("j1")).toHaveLength(1);
  });

  it("CA14 · Calendario y Personas simultáneos se actualizan y fallan de forma aislada", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({
      jobs: MODES.map((m, i) =>
        job({ id: `j${i}`, status: "running", credits_estimated: i + 1, ...m.base }),
      ),
    });
    renderProvider();
    await settle();

    emit(
      job({
        id: "j2",
        status: "completed",
        credits_estimated: 3,
        credits_consumed: 1,
        result: terminalResult(MODES[2].base, "pdl") as never,
        ...MODES[2].base,
      }),
      "job_completed",
    );
    streamError("j1", "network");
    await settle();

    expect(statusOf("j0")).toBe("running");
    expect(statusOf("j1")).toBe("running");
    expect(statusOf("j2")).toBe("completed");
    expect(statusOf("j3")).toBe("running");
    expect(openSubs("j0")).toHaveLength(1);
    expect(openSubs("j3")).toHaveLength(1);
    expect(screen.getAllByText(t("dossier_jobs.connection_lost"))).toHaveLength(1);
    expect(ctx().jobs.map((j) => [j.id, j.credits_estimated, j.credits_consumed])).toEqual([
      ["j0", 1, 0],
      ["j1", 2, 0],
      ["j2", 3, 1],
      ["j3", 4, 0],
    ]);
    const outlookToast = screen.getByText("Trabajo j1").closest("div.rounded-xl") as HTMLElement;
    expect(within(outlookToast).getByText(t("dossier_jobs.connection_lost"))).toBeInTheDocument();
  });
});
