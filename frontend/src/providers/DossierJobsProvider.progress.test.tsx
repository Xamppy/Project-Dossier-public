import { useEffect } from "react";
import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import { AUTH_ME_CHANGED_EVENT } from "@/hooks/useAuthMe";
import { DossierApiError, type DossierGenerationJobApi } from "@/lib/dossier-api";
import { normalizeProgressSnapshot, parseProgressEvent } from "@/lib/dossier-job-progress";
import { DossierJobStreamError, type DossierJobStreamHandlers } from "@/lib/dossier-job-stream";
import { JOB_EVENTS, loadS510Fixture, type S510Frame } from "@/test/s510-fixtures";
import { DossierJobsProvider, useDossierJobs } from "./DossierJobsProvider";

// Progreso de S5.4 en el proveedor: la única suscripción de S5.1 entrega también
// agent_progress, stage_progress y partial_result, que se fusionan por revisión
// sin pisar toasts, resultados ni el merge no regresivo del estado del job.

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
  default: ({ href, children, onClick }: { href: string; children: React.ReactNode; onClick?: () => void }) => (
    <a href={href} onClick={onClick}>
      {children}
    </a>
  ),
}));

const t = createTranslator("es");
const FIX = "00000000-0000-4000-8000-000000000001";

const probe: { value: ReturnType<typeof useDossierJobs> | null } = { value: null };
const ctx = () => {
  if (!probe.value) throw new Error("El proveedor aún no se montó");
  return probe.value;
};
const jobOf = (id: string) => ctx().jobs.find((j) => j.id === id);

function Probe() {
  const value = useDossierJobs();
  useEffect(() => {
    probe.value = value;
  });
  return null;
}

function renderProvider() {
  return render(
    <DossierJobsProvider>
      <Probe />
    </DossierJobsProvider>,
  );
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

const subsFor = (id: string) => h.subs.filter((s) => s.jobId === id);
const openSubs = (id: string) => subsFor(id).filter((s) => !s.closed);

/** Entrega frames por el stream abierto del job, como lo haría el adaptador real. */
function feed(jobId: string, frames: S510Frame[]) {
  for (const frame of frames) {
    const [sub] = openSubs(jobId);
    if (!sub) throw new Error(`No hay stream abierto para ${jobId} (frame ${frame.id})`);
    act(() => {
      if (JOB_EVENTS.has(frame.event)) {
        sub.handlers.onSnapshot(frame.data as unknown as DossierGenerationJobApi, {
          event: frame.event as "job_status",
          eventId: String(frame.id),
        });
      } else {
        const event = parseProgressEvent(frame.event, frame.data, jobId);
        if (!event) throw new Error(`frame ${frame.id} inválido`);
        sub.handlers.onProgress?.(event, { eventId: String(frame.id) });
      }
    });
  }
}

const finalProgress = (name: Parameters<typeof loadS510Fixture>[0]) =>
  normalizeProgressSnapshot(loadS510Fixture(name).snapshot_final.progress);

beforeEach(() => {
  h.subs.length = 0;
  h.pathname = "/dashboard";
  for (const fn of Object.values(h.api)) fn.mockReset();
  h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [] });
  h.api.fetchDossierGenerationJob.mockRejectedValue(new DossierApiError(404, "Job no encontrado."));
  localStorage.setItem("dossier_access_token", "tok");
});

describe("DossierJobsProvider · S5.4 progreso por la suscripción de S5.1", () => {
  it("CA1 · isolates_progress_by_calendar_job · dos jobs de calendario solo cambian su propio progreso", async () => {
    const cal = loadS510Fixture("calendario-agente-caido");
    const other = { ...(cal.frames[1].data as unknown as DossierGenerationJobApi), id: "cal-B", external_event_id: "evt-B" };
    h.api.fetchDossierGenerationJobs.mockResolvedValue({
      jobs: [cal.frames[0].data as unknown as DossierGenerationJobApi, other],
    });
    renderProvider();
    await settle();
    expect(openSubs(FIX)).toHaveLength(1);
    expect(openSubs("cal-B")).toHaveLength(1);

    feed(FIX, cal.frames.slice(0, 20));
    // A mitad de camino ya se ven los perfiles de Ana, que solo llegan por partial_result.
    const ana = jobOf(FIX)?.progress?.scopes.find((s) => s.scope_id === "person:0");
    expect(ana?.partial_results.map((p) => p.section)).toEqual(["person_profiles"]);
    // Un evento del job A que llegara por el canal de B no se aplica a B.
    const stray = parseProgressEvent(cal.frames[2].event, cal.frames[2].data, FIX)!;
    act(() => openSubs("cal-B")[0].handlers.onProgress?.(stray, { eventId: "x" }));
    feed(FIX, cal.frames.slice(20));
    await settle();

    expect(jobOf(FIX)?.status).toBe("completed");
    expect(jobOf(FIX)?.progress).toEqual(finalProgress("calendario-agente-caido"));
    expect(jobOf("cal-B")?.progress).toEqual(normalizeProgressSnapshot(cal.frames[1].data.progress));
  });

  it("CA2 · applies_agent_revisions_idempotently · los eventos usan el stream existente: sin GET ni streams nuevos", async () => {
    const pdl = loadS510Fixture("personas-pdl");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [pdl.frames[0].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();

    feed(FIX, pdl.frames.slice(0, 12));
    const before = jobOf(FIX)?.progress;
    const stages = before?.scopes[0].kind === "person" ? before.scopes[0].stages : [];
    expect(stages.find((s) => s.stage_id === "person.profile_synthesis")).toMatchObject({ status: "completed", revision: 11 });
    feed(FIX, pdl.frames.slice(2, 12)); // duplicados
    expect(jobOf(FIX)?.progress).toBe(before);
    feed(FIX, pdl.frames.slice(12));
    await settle();

    expect(subsFor(FIX)).toHaveLength(1);
    expect(h.api.fetchDossierGenerationJob).not.toHaveBeenCalled();
    expect(jobOf(FIX)?.progress).toEqual(finalProgress("personas-pdl"));
  });

  it("aplicar progreso no pisa el toast descartado ni el resultado ni el estado del job", async () => {
    const pdl = loadS510Fixture("personas-pdl");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [pdl.frames[1].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();
    act(() => ctx().dismissToast(FIX));

    feed(FIX, pdl.frames.slice(2, 15));
    expect(jobOf(FIX)).toMatchObject({ status: "running", toastDismissed: true, result: null });
    expect(jobOf(FIX)?.progress?.scopes[0].partial_results.map((p) => p.section)).toEqual([
      "person_profiles",
      "person_report",
    ]);
    feed(FIX, pdl.frames.slice(15));
    await settle();

    expect(jobOf(FIX)).toMatchObject({ status: "completed", toastDismissed: true });
    expect(jobOf(FIX)?.result).toEqual(pdl.snapshot_final.result);
    expect(screen.queryByText(t("dossier_jobs.ready"))).not.toBeInTheDocument();
  });

  it("CA8 · restores_progress_from_snapshot · un job_status viejo no hace retroceder el progreso", async () => {
    const cal = loadS510Fixture("calendario-agente-caido");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [cal.frames[0].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();

    feed(FIX, cal.frames.slice(0, 28));
    const before = jobOf(FIX)?.progress;
    feed(FIX, [cal.frames[13]]); // job_status de la revisión 13
    expect(jobOf(FIX)?.progress).toEqual(before);
    expect(jobOf(FIX)?.status).toBe("running");
  });

  it("CA8 · un GET de recuperación se fusiona por revisión y el stream nuevo termina el trabajo", async () => {
    const pdl = loadS510Fixture("personas-pdl");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [pdl.frames[0].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();
    feed(FIX, pdl.frames.slice(0, 10));
    const partials = jobOf(FIX)?.progress?.scopes[0].partial_results;
    expect(partials?.map((p) => p.section)).toEqual(["person_profiles"]);

    act(() => openSubs(FIX)[0].handlers.onError(new DossierJobStreamError("network")));
    await settle();
    expect(ctx().getJobConnection(FIX)).toEqual({ state: "interrupted", reason: "transport" });
    expect(jobOf(FIX)?.progress?.scopes[0].partial_results).toEqual(partials);

    h.api.fetchDossierGenerationJob.mockResolvedValue(pdl.frames[1].data); // snapshot viejo
    await act(async () => {
      await ctx().resyncJob(FIX);
    });
    await settle();
    expect(jobOf(FIX)?.progress?.scopes[0].partial_results).toEqual(partials);
    expect(openSubs(FIX)).toHaveLength(1);

    feed(FIX, pdl.frames.slice(10));
    await settle();
    expect(jobOf(FIX)?.progress).toEqual(finalProgress("personas-pdl"));
  });

  it("CA9 · separates_transport_cancellation_and_generation_errors · al cancelar nada revive", async () => {
    const cancelled = loadS510Fixture("personas-cancelada");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [cancelled.frames[0].data as unknown as DossierGenerationJobApi] });
    h.api.cancelDossierGenerationJob.mockResolvedValue(cancelled.snapshot_final);
    renderProvider();
    await settle();
    feed(FIX, cancelled.frames.slice(0, 4));
    const running = jobOf(FIX)?.progress?.scopes[0];
    expect(running?.kind === "person" && running.stages.find((s) => s.stage_id === "person.pdl_enrich")?.status).toBe(
      "running",
    );
    const [sub] = openSubs(FIX);

    await act(async () => {
      await ctx().cancelJob(FIX);
    });
    await settle();
    expect(jobOf(FIX)?.status).toBe("cancelled");
    const closed = jobOf(FIX)?.progress;
    expect(closed).toEqual(finalProgress("personas-cancelada"));

    const late = parseProgressEvent(
      "stage_progress",
      { ...cancelled.frames[3].data, revision: 50, status: "completed" },
      FIX,
    )!;
    act(() => sub.handlers.onProgress?.(late, { eventId: "99" }));
    expect(jobOf(FIX)?.progress).toBe(closed);
    expect(screen.getByText(t("dossier_jobs.cancelled"))).toBeInTheDocument();
  });

  it("los jobs anteriores a S5.4 (sin progress) se comportan como antes", async () => {
    h.api.fetchDossierGenerationJobs.mockResolvedValue({
      jobs: [{ id: "viejo", status: "running", job_type: "calendar_manual", calendar_provider: "google", external_event_id: "e" }],
    });
    renderProvider();
    await settle();
    act(() =>
      openSubs("viejo")[0].handlers.onSnapshot(
        { id: "viejo", status: "running", job_type: "calendar_manual", progress: null },
        { event: "job_status", eventId: "1" },
      ),
    );
    expect(jobOf("viejo")?.progress ?? null).toBeNull();
    expect(screen.getByText(t("dossier_jobs.generating"))).toBeInTheDocument();
  });
});

describe("DossierJobsProvider · S5.4 ejecución de Personas seleccionada", () => {
  it("CA18 · restores_selected_person_result_and_mode · sobrevive al terminal y a recargar", async () => {
    const failed = loadS510Fixture("personas-pdl-informe-fallido").snapshot_final;
    h.api.fetchDossierGenerationJob.mockResolvedValue(failed);
    const first = renderProvider();
    await settle();

    act(() => ctx().selectPersonJob(FIX));
    await settle();
    expect(ctx().selectedPersonJobId).toBe(FIX);
    expect(jobOf(FIX)?.status).toBe("failed");
    expect(h.api.fetchDossierGenerationJob).toHaveBeenCalledTimes(1);
    first.unmount();

    renderProvider();
    await settle();
    expect(ctx().selectedPersonJobId).toBe(FIX);
    expect(jobOf(FIX)?.progress).toEqual(finalProgress("personas-pdl-informe-fallido"));
    expect(h.api.fetchDossierGenerationJob).toHaveBeenCalledTimes(2);
  });

  it("si el job seleccionado ya no existe (404) se olvida la selección", async () => {
    renderProvider();
    await settle();
    act(() => ctx().selectPersonJob("borrado"));
    await settle();
    expect(ctx().selectedPersonJobId).toBeNull();
  });

  it("un 404 en el stream del job seleccionado lo retira y limpia la selección", async () => {
    const pdl = loadS510Fixture("personas-pdl");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [pdl.frames[1].data as unknown as DossierGenerationJobApi] });
    h.api.fetchDossierGenerationJob.mockResolvedValue(pdl.frames[1].data);
    renderProvider();
    await settle();
    act(() => ctx().selectPersonJob(FIX));
    act(() => openSubs(FIX)[0].handlers.onError(new DossierJobStreamError("not_found", 404)));
    await settle();
    expect(jobOf(FIX)).toBeUndefined();
    expect(ctx().selectedPersonJobId).toBeNull();
    expect(h.api.fetchDossierGenerationJob).not.toHaveBeenCalled();
  });

  it("cambiar de sesión olvida la ejecución seleccionada", async () => {
    h.api.fetchDossierGenerationJob.mockResolvedValue(loadS510Fixture("personas-pdl").snapshot_final);
    renderProvider();
    await settle();
    act(() => ctx().selectPersonJob(FIX));
    await settle();
    act(() => {
      window.dispatchEvent(new Event(AUTH_ME_CHANGED_EVENT));
    });
    await settle();
    expect(ctx().selectedPersonJobId).toBeNull();
  });
});

describe("DossierJobsProvider · S5.4 avisos con la clasificación del resultado", () => {
  it("CA5 · does_not_confuse_preview_with_saved_dossier · un guardado failed no da «Ver dossier»", async () => {
    const pdl = loadS510Fixture("personas-pdl");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [pdl.frames[1].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();
    const final = pdl.snapshot_final;
    const result = final.result as { saved_dossier: { status: string }; llm_analysis_markdown: string | null };
    result.saved_dossier.status = "failed";
    act(() =>
      openSubs(FIX)[0].handlers.onSnapshot({ ...final, progress: null }, { event: "job_completed", eventId: "9" }),
    );
    await settle();

    expect(screen.getByText(t("dossier_jobs.failed"))).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: t("dossier_jobs.view_dossier") })).not.toBeInTheDocument();
  });

  it("CA16 · keeps_person_profiles_when_report_fails · el aviso ofrece «Ver información disponible»", async () => {
    const failed = loadS510Fixture("personas-pdl-informe-fallido");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [failed.frames[0].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();
    feed(FIX, failed.frames);
    await settle();

    const link = screen.getByRole("link", { name: t("progress.view_available") });
    expect(link).toHaveAttribute("href", `/dashboard/person-research?job=${FIX}`);
    expect(screen.queryByRole("link", { name: t("dossier_jobs.view_dossier") })).not.toBeInTheDocument();
  });

  it("CA2 · el aviso de una reunión en curso muestra la lista compacta de la empresa y una línea por asistente", async () => {
    const cal = loadS510Fixture("calendario-agente-caido");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [cal.frames[0].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();
    feed(FIX, cal.frames.slice(0, 32));

    const toast = screen.getByText(t("dossier_jobs.generating")).closest("div.rounded-xl") as HTMLElement;
    const agents = within(toast).getByRole("list", {
      name: t("progress.agents_aria", { name: "Empresa de Prueba SA" }),
    });
    expect(within(agents).getAllByRole("listitem")).toHaveLength(5);
    expect(within(agents).getByText("Falló · error del proveedor")).toBeInTheDocument();
    expect(within(toast).getByText("Búsqueda ampliada en PDL · En curso")).toBeInTheDocument();
    expect(within(toast).queryByText(t("progress.preview_badge"))).not.toBeInTheDocument();
  });

  it("CA6 · handles_multiple_people_and_legacy_results · el aviso del calendario es parcial y nombra lo que faltó", async () => {
    const cal = loadS510Fixture("calendario-agente-caido");
    h.api.fetchDossierGenerationJobs.mockResolvedValue({ jobs: [cal.frames[0].data as unknown as DossierGenerationJobApi] });
    renderProvider();
    await settle();
    feed(FIX, cal.frames);
    await settle();

    const toast = screen.getByText(t("dossier_jobs.partial")).closest("div.rounded-xl") as HTMLElement;
    expect(within(toast).getByText(t("progress.outcome.missing", { items: "Reino Unido, Beto Ficticio" }))).toBeInTheDocument();
    expect(within(toast).getByRole("link", { name: t("dossier_jobs.view_folder") })).toHaveAttribute(
      "href",
      "/dashboard/dossiers/folder/00000000-0000-4000-8000-000000000005",
    );
  });
});
