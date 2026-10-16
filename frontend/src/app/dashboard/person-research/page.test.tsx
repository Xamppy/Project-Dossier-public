import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import type { DossierGenerationJobApi } from "@/lib/dossier-api";
import {
  DossierJobStreamError,
  type DossierJobStreamErrorKind,
  type DossierJobStreamHandlers,
} from "@/lib/dossier-job-stream";
import { parseProgressEvent } from "@/lib/dossier-job-progress";
import { DossierJobsProvider } from "@/providers/DossierJobsProvider";
import { JOB_EVENTS, loadS510Fixture, type S510Frame } from "@/test/s510-fixtures";
import PersonResearchPage from "./page";

// Personas (/dashboard/person-research) con el proveedor y el cliente HTTP
// reales: el servidor está detrás de un `fetch` simulado y el stream SSE lo
// controla la prueba. Cubre CA13-CA15 de S5.1 para Registros PDL y Web pública.

type FakeSub = { jobId: string; handlers: DossierJobStreamHandlers; closed: boolean };

const h = vi.hoisted(() => ({
  subs: [] as FakeSub[],
  params: new URLSearchParams(),
  /** S5.4: ID del próximo job encolado (los ejemplos de S5.10 usan un ID fijo). */
  forcedJobId: null as string | null,
}));

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
    usePreferences: () => ({
      preferences: { locale: "es", outputLanguage: "match", timezone: "UTC", dateFormat: "dd/mm/yyyy" },
    }),
  };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard/person-research",
  useSearchParams: () => h.params,
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/components/auth/MutatorGuard", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/dashboard/TopBar", () => ({
  default: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

const t = createTranslator("es");
const API = "https://api.dossier.test";

const MODOS = [
  { nombre: "Registros PDL", source: "pdl", boton: "person_research.source_pdl" },
  { nombre: "Web pública", source: "gemini_web", boton: "person_research.source_gemini" },
] as const;

type Llamada = { method: string; url: string; body: Record<string, unknown> | null };

let servidor: Map<string, DossierGenerationJobApi>;
let llamadas: Llamada[];
let secuencia: number;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function resultadoPersona(source: string, id: string) {
  return {
    filters_applied: { research_source: source },
    search_attempts: [],
    profile_urls: [],
    profiles: [],
    posts_by_url: {},
    llm_analysis_markdown: "# Informe",
    warnings: [],
    saved_dossier: {
      id,
      organization_id: "org",
      status: "complete",
      credits_consumed: 1,
      generation_duration_ms: 1200,
    },
  };
}

beforeEach(() => {
  h.subs.length = 0;
  h.params = new URLSearchParams();
  h.forcedJobId = null;
  servidor = new Map();
  llamadas = [];
  secuencia = 0;
  vi.stubEnv("NEXT_PUBLIC_API_URL", API);
  localStorage.setItem("dossier_access_token", "tok");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : null;
      llamadas.push({ method, url, body });
      if (url === `${API}/auth/me`) {
        return json({ email: "qa@dossier.test", organization_plan: "pro", credits_monthly_limit: 100 });
      }
      if (url === `${API}/dossiers/person/research` && method === "POST") {
        secuencia += 1;
        const job: DossierGenerationJobApi = {
          id: h.forcedJobId ?? `persona-${secuencia}`,
          status: "queued",
          job_type: "person_manual",
          calendar_provider: null,
          external_event_id: null,
          meeting_label: String(body?.full_name ?? ""),
          credits_estimated: 1,
          credits_consumed: 0,
        };
        servidor.set(job.id, job);
        return json({ async: true, job_id: job.id, status: "queued", meeting_label: job.meeting_label, credits_estimated: 1 });
      }
      if (url === `${API}/dossier-generation-jobs`) {
        return json({
          jobs: [...servidor.values()].filter((j) => j.status === "queued" || j.status === "running"),
        });
      }
      const cancel = url.match(/\/dossier-generation-jobs\/([^/]+)\/cancel$/);
      if (cancel && method === "POST") {
        const job = servidor.get(cancel[1]);
        if (!job) return json({ detail: "Job no encontrado." }, 404);
        const cancelado = { ...job, status: "cancelled" as const };
        servidor.set(job.id, cancelado);
        return json(cancelado);
      }
      const uno = url.match(/\/dossier-generation-jobs\/([^/]+)$/);
      if (uno) {
        const job = servidor.get(uno[1]);
        return job ? json(job) : json({ detail: "Job no encontrado." }, 404);
      }
      throw new Error(`Petición inesperada en la prueba: ${method} ${url}`);
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

function Pantalla({ enPersonas = true }: { enPersonas?: boolean }) {
  return (
    <DossierJobsProvider>{enPersonas ? <PersonResearchPage /> : <p>Otra sección</p>}</DossierJobsProvider>
  );
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

const subsFor = (id: string) => h.subs.filter((s) => s.jobId === id);
const openSubs = (id: string) => subsFor(id).filter((s) => !s.closed);
const postsDeInvestigacion = () =>
  llamadas.filter((c) => c.method === "POST" && c.url.endsWith("/dossiers/person/research"));

/** El servidor cambia el job y lo publica por su stream abierto. */
function publicar(id: string, over: Partial<DossierGenerationJobApi>, event = "job_status") {
  const job = { ...servidor.get(id)!, ...over };
  servidor.set(id, job);
  const [sub] = openSubs(id);
  if (!sub) throw new Error(`No hay stream abierto para ${id}`);
  act(() => {
    sub.handlers.onSnapshot(job, {
      event: event as "job_status" | "job_completed" | "job_failed",
      eventId: "1",
    });
  });
}

function cortar(id: string, kind: DossierJobStreamErrorKind, status: number | null = null) {
  const [sub] = openSubs(id);
  if (!sub) throw new Error(`No hay stream abierto para ${id}`);
  act(() => {
    sub.handlers.onError(new DossierJobStreamError(kind, status));
  });
}

async function iniciar(modo: (typeof MODOS)[number], nombre = "Ada Lovelace") {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: new RegExp(t(modo.boton)) }));
  const campo = screen.getByLabelText(t("person_research.full_name"));
  await user.clear(campo);
  await user.type(campo, nombre);
  await user.click(screen.getByRole("button", { name: t("generate.submit_one") }));
  await settle();
  return { user, jobId: `persona-${secuencia}` };
}

const panelGenerando = (nombre: string) =>
  screen.queryByText(t("person_research.generating_title", { name: nombre }));

describe.each(MODOS)("Personas · $nombre · estado general por SSE", (modo) => {
  it("CA13 · encola un person_manual asíncrono con su modalidad y abre un único stream", async () => {
    render(<Pantalla />);
    await settle();

    const { jobId } = await iniciar(modo);

    const [post] = postsDeInvestigacion();
    expect(post.body).toMatchObject({
      full_name: "Ada Lovelace",
      research_source: modo.source,
      async_mode: true,
      output_language: "es",
    });
    expect(panelGenerando("Ada Lovelace")).toBeInTheDocument();
    expect(openSubs(jobId)).toHaveLength(1);
  });

  it.each([
    ["completed", "job_completed"],
    ["failed", "job_failed"],
    ["cancelled", "job_failed"],
  ] as const)("CA13 · queued → running → %s llega por SSE y cierra el stream", async (estado, evento) => {
    render(<Pantalla />);
    await settle();
    const { jobId } = await iniciar(modo);

    publicar(jobId, { status: "running" });
    expect(panelGenerando("Ada Lovelace")).toBeInTheDocument();

    publicar(
      jobId,
      estado === "completed"
        ? { status: "completed", credits_consumed: 1, result: resultadoPersona(modo.source, `d-${modo.source}`) }
        : estado === "failed"
          ? { status: "failed", error_message: "Fallo del proveedor" }
          : { status: "cancelled" },
      evento,
    );
    await settle();

    expect(panelGenerando("Ada Lovelace")).not.toBeInTheDocument();
    expect(openSubs(jobId)).toHaveLength(0);
    expect(subsFor(jobId)).toHaveLength(1);
    if (estado === "completed") {
      expect(screen.getByRole("link", { name: t("dossier_jobs.view_dossier") })).toHaveAttribute(
        "href",
        `/dashboard/dossiers/d-${modo.source}`,
      );
    }
    if (estado === "failed") expect(screen.getByText("Fallo del proveedor")).toBeInTheDocument();
    if (estado === "cancelled") {
      expect(screen.getByText(t("dossier_jobs.cancelled"))).toBeInTheDocument();
      expect(screen.queryByText(t("dossier_jobs.failed"))).not.toBeInTheDocument();
    }
  });

  it("CA13 · salir de Personas y volver recupera el mismo trabajo sin abrir otro stream", async () => {
    const { rerender } = render(<Pantalla />);
    await settle();
    const { jobId } = await iniciar(modo);
    publicar(jobId, { status: "running" });

    rerender(<Pantalla enPersonas={false} />);
    expect(screen.getByText("Otra sección")).toBeInTheDocument();
    rerender(<Pantalla />);
    await settle();

    expect(panelGenerando("Ada Lovelace")).toBeInTheDocument();
    expect(subsFor(jobId)).toHaveLength(1);
    expect(openSubs(jobId)).toHaveLength(1);
  });

  it("CA15 · al recargar se restaura el trabajo activo y sigue por SSE hasta terminar", async () => {
    const primera = render(<Pantalla />);
    await settle();
    const { jobId } = await iniciar(modo);
    publicar(jobId, { status: "running" });
    primera.unmount();
    expect(openSubs(jobId)).toHaveLength(0);

    render(<Pantalla />);
    await settle();

    expect(panelGenerando("Ada Lovelace")).toBeInTheDocument();
    expect(openSubs(jobId)).toHaveLength(1);
    publicar(jobId, { status: "completed", result: resultadoPersona(modo.source, "d-r") }, "job_completed");
    await settle();
    expect(panelGenerando("Ada Lovelace")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: t("dossier_jobs.view_dossier") })).toHaveAttribute(
      "href",
      "/dashboard/dossiers/d-r",
    );
  });

  it("CA15 · reemplazar un dossier envía force_refresh y replace_dossier_id con la modalidad", async () => {
    h.params = new URLSearchParams({
      replace: "d-anterior",
      full_name: "Grace Hopper",
      research_source: modo.source,
    });
    const user = userEvent.setup();
    render(<Pantalla />);
    await settle();

    await user.click(screen.getByRole("button", { name: t("person_research.submit_replace") }));
    await settle();

    expect(postsDeInvestigacion()[0].body).toMatchObject({
      full_name: "Grace Hopper",
      research_source: modo.source,
      async_mode: true,
      force_refresh: true,
      replace_dossier_id: "d-anterior",
    });
    expect(openSubs(`persona-${secuencia}`)).toHaveLength(1);
  });

  it("CA15 · cancelar desde la página usa la API de jobs y cierra el stream", async () => {
    render(<Pantalla />);
    await settle();
    const { user, jobId } = await iniciar(modo);
    publicar(jobId, { status: "running" });

    await user.click(screen.getByRole("button", { name: t("person_research.cancel") }));
    await settle();

    expect(llamadas.some((c) => c.method === "POST" && c.url.endsWith(`/${jobId}/cancel`))).toBe(true);
    expect(panelGenerando("Ada Lovelace")).not.toBeInTheDocument();
    expect(openSubs(jobId)).toHaveLength(0);
  });

  it("CA15 · un corte de red se muestra en la página y la reconexión pide un único snapshot", async () => {
    render(<Pantalla />);
    await settle();
    const { user, jobId } = await iniciar(modo);
    publicar(jobId, { status: "running" });

    cortar(jobId, "network");
    await settle();

    const panel = panelGenerando("Ada Lovelace")!.closest("div") as HTMLElement;
    expect(within(panel).getByText(t("dossier_jobs.connection_lost"))).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: t("dossier_jobs.reconnect") }));
    await settle();

    const lecturas = llamadas.filter((c) => c.method === "GET" && c.url.endsWith(`/dossier-generation-jobs/${jobId}`));
    expect(lecturas).toHaveLength(1);
    expect(openSubs(jobId)).toHaveLength(1);
    expect(screen.queryByText(t("dossier_jobs.connection_lost"))).not.toBeInTheDocument();
    expect(panelGenerando("Ada Lovelace")).toBeInTheDocument();
  });

  it("CA15 · 401 en el stream pide iniciar sesión sin marcar el trabajo como fallido", async () => {
    render(<Pantalla />);
    await settle();
    const { jobId } = await iniciar(modo);

    cortar(jobId, "unauthorized", 401);
    await settle();

    const panel = panelGenerando("Ada Lovelace")!.closest("div") as HTMLElement;
    expect(within(panel).getByText(t("auth.error.session_expired"))).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: t("dossier_jobs.reconnect") })).not.toBeInTheDocument();
    expect(screen.queryByText(t("dossier_jobs.failed"))).not.toBeInTheDocument();
  });

  it("CA15 · 404 en el stream retira el trabajo y la página vuelve al formulario", async () => {
    render(<Pantalla />);
    await settle();
    const { jobId } = await iniciar(modo);

    cortar(jobId, "not_found", 404);
    await settle();

    expect(panelGenerando("Ada Lovelace")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("generate.submit_one") })).toBeInTheDocument();
  });

  it("CA15 · con el trabajo en curso, 60 s de reloj no generan lecturas periódicas del job", async () => {
    render(<Pantalla />);
    await settle();
    const { jobId } = await iniciar(modo);
    publicar(jobId, { status: "running" });
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });

    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(llamadas.filter((c) => /\/dossier-generation-jobs\/[^/]+$/.test(c.url))).toHaveLength(0);
  });
});

describe("Personas · convivencia de modalidades y con Calendario", () => {
  it("CA14 · PDL y Web pública son ejecuciones separadas y un job de calendario no afecta a Personas", async () => {
    servidor.set("cal-1", {
      id: "cal-1",
      status: "running",
      job_type: "calendar_manual",
      calendar_provider: "google",
      external_event_id: "evt-1",
      meeting_label: "Reunión con Acme",
      credits_estimated: 3,
      credits_consumed: 0,
    });
    render(<Pantalla />);
    await settle();
    expect(openSubs("cal-1")).toHaveLength(1);

    const pdl = await iniciar(MODOS[0], "Ada Lovelace");
    publicar(pdl.jobId, { status: "completed", result: resultadoPersona("pdl", "d-pdl") }, "job_completed");
    await settle();
    const web = await iniciar(MODOS[1], "Grace Hopper");

    expect(pdl.jobId).not.toBe(web.jobId);
    expect(postsDeInvestigacion().map((c) => c.body?.research_source)).toEqual(["pdl", "gemini_web"]);
    expect(panelGenerando("Grace Hopper")).toBeInTheDocument();

    publicar("cal-1", { status: "failed", error_message: null }, "job_failed");
    await settle();

    expect(panelGenerando("Grace Hopper")).toBeInTheDocument();
    expect(openSubs(web.jobId)).toHaveLength(1);
    expect(screen.getByText(t("dossier_jobs.failed"))).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("link", { name: t("dossier_jobs.view_dossier") })).toHaveAttribute(
        "href",
        "/dashboard/dossiers/d-pdl",
      ),
    );
    expect(screen.queryByText(t("dossier_jobs.connection_lost"))).not.toBeInTheDocument();
  });
});

// --- S5.4: avance real y resultados parciales en Personas --------------------

const FIX = "00000000-0000-4000-8000-000000000001";

/** El servidor publica los frames reales de S5.10 por el stream abierto del job. */
function alimentar(frames: S510Frame[]) {
  for (const frame of frames) {
    const [sub] = openSubs(FIX);
    if (!sub) throw new Error(`No hay stream abierto para ${FIX} (frame ${frame.id})`);
    act(() => {
      if (JOB_EVENTS.has(frame.event)) {
        servidor.set(FIX, frame.data as unknown as DossierGenerationJobApi);
        sub.handlers.onSnapshot(frame.data as unknown as DossierGenerationJobApi, {
          event: frame.event as "job_status",
          eventId: String(frame.id),
        });
      } else {
        const event = parseProgressEvent(frame.event, frame.data, FIX);
        if (!event) throw new Error(`frame ${frame.id} inválido`);
        sub.handlers.onProgress?.(event, { eventId: String(frame.id) });
      }
    });
  }
}

async function iniciarEjemplo(modo: (typeof MODOS)[number]) {
  h.forcedJobId = FIX;
  return iniciar(modo, "Ana Prueba");
}

const panelAvance = () => screen.getByRole("region", { name: t("progress.panel_title") });
const etapa = (panel: HTMLElement, label: string) =>
  within(panel).getByText(label).closest("li")?.querySelector("[data-stage-status]")?.textContent;
const lecturasDelJob = () => llamadas.filter((c) => c.method === "GET" && c.url.endsWith(`/dossier-generation-jobs/${FIX}`));

describe("Personas · S5.4 avance real y resultados parciales", () => {
  it("CA14 · renders_real_pdl_stages · Registros PDL: avance paso a paso y el perfil antes del informe", async () => {
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    const pdl = loadS510Fixture("personas-pdl");

    alimentar(pdl.frames.slice(0, 8));
    let panel = panelAvance();
    expect(etapa(panel, "Buscar el perfil en PDL")).toBe("Listo");
    expect(etapa(panel, "Preparar los perfiles encontrados")).toBe(t("progress.status.running"));
    expect(within(panel).getByRole("region", { name: t("progress.profiles_title") })).toHaveTextContent("Directora general");
    expect(within(panel).queryByRole("region", { name: t("progress.report_title") })).not.toBeInTheDocument();
    expect(panelGenerando("Ana Prueba")).toBeInTheDocument();

    alimentar(pdl.frames.slice(8));
    await settle();
    panel = panelAvance();
    expect(panelGenerando("Ana Prueba")).not.toBeInTheDocument();
    expect(within(panel).getByRole("region", { name: t("progress.report_title") })).toBeInTheDocument();
    expect(within(panel).getByText(t("dossier_jobs.ready"))).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: t("dossier_jobs.view_dossier") })).toHaveAttribute(
      "href",
      "/dashboard/dossiers/00000000-0000-4000-8000-000000000002",
    );
    expect(subsFor(FIX)).toHaveLength(1);
    expect(lecturasDelJob()).toHaveLength(0);
  });

  it("CA16 · keeps_person_profiles_when_report_fails · el informe falla y los perfiles siguen con «Ver información disponible»", async () => {
    const user = userEvent.setup();
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);

    alimentar(loadS510Fixture("personas-pdl-informe-fallido").frames);
    await settle();
    const panel = panelAvance();
    expect(within(panel).getByText(t("progress.outcome.failed_with_partial"))).toBeInTheDocument();
    expect(within(panel).getByRole("region", { name: t("progress.profiles_title") })).toHaveTextContent("Ana Prueba");
    expect(within(panel).queryByRole("link", { name: t("dossier_jobs.view_dossier") })).not.toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: t("progress.view_available") }));
    expect(
      within(document.activeElement as HTMLElement).getByRole("region", { name: t("progress.profiles_title") }),
    ).toBeInTheDocument();
  });

  it("CA15 · renders_model_only_progress_truthfully · Web pública: «Elaborando informe con IA», sin búsqueda en vivo ni texto antes de tiempo", async () => {
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[1]);
    const web = loadS510Fixture("personas-web-publica");

    alimentar(web.frames.slice(0, 4));
    let panel = panelAvance();
    expect(etapa(panel, "Elaborar el informe con IA")).toBe(t("progress.status.running_ai_report"));
    expect(within(panel).getByText(t("progress.no_live_web_search"))).toBeInTheDocument();
    expect(within(panel).queryByRole("region", { name: t("progress.report_title") })).not.toBeInTheDocument();
    expect(panel.textContent).not.toMatch(/PDL|%/);

    alimentar(web.frames.slice(4));
    await settle();
    panel = panelAvance();
    const report = within(panel).getByRole("region", { name: t("progress.report_title") });
    expect(within(report).getByText(t("progress.provenance.model_only"))).toBeInTheDocument();
  });

  it("CA18 · restores_selected_person_result_and_mode · cambiar el selector no reinterpreta la ejecución consultada", async () => {
    const user = userEvent.setup();
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    alimentar(loadS510Fixture("personas-pdl").frames);
    await settle();

    await user.click(screen.getByRole("button", { name: new RegExp(t("person_research.source_gemini")) }));
    expect(
      within(panelAvance()).getByText(t("progress.mode_label", { mode: t("person_research.source_pdl") })),
    ).toBeInTheDocument();
  });

  it("CA18 · al recargar se restaura la ejecución terminada y sus parciales aunque se cerró el aviso", async () => {
    const user = userEvent.setup();
    const primera = render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    alimentar(loadS510Fixture("personas-pdl-informe-fallido").frames);
    await settle();
    await user.click(screen.getByRole("button", { name: t("dossier_jobs.dismiss") }));
    primera.unmount();

    render(<Pantalla />);
    await settle();
    await settle();
    const panel = panelAvance();
    expect(within(panel).getByRole("region", { name: t("progress.profiles_title") })).toHaveTextContent("Ana Prueba");
    expect(within(panel).getByText(t("progress.outcome.failed_with_partial"))).toBeInTheDocument();
    expect(lecturasDelJob()).toHaveLength(1);
  });

  it("CA18 · el enlace «Ver información disponible» de un aviso (?job=) abre esa ejecución en Personas", async () => {
    servidor.set(FIX, loadS510Fixture("personas-pdl-informe-fallido").snapshot_final);
    h.params = new URLSearchParams({ job: FIX });
    render(<Pantalla />);
    await settle();
    await settle();
    const panel = panelAvance();
    expect(within(panel).getByRole("region", { name: t("progress.profiles_title") })).toHaveTextContent("Ana Prueba");
    expect(lecturasDelJob()).toHaveLength(1);
  });

  it("CA18 · salir de Personas y volver conserva el panel de la ejecución terminada", async () => {
    const { rerender } = render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    alimentar(loadS510Fixture("personas-pdl").frames);
    await settle();

    rerender(<Pantalla enPersonas={false} />);
    rerender(<Pantalla />);
    await settle();
    expect(within(panelAvance()).getByRole("region", { name: t("progress.report_title") })).toBeInTheDocument();
  });

  it("CA19 · renders_cached_person_result_without_fabricated_steps · la caché se presenta como resultado guardado de antes", async () => {
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    alimentar(loadS510Fixture("personas-cache").frames);
    await settle();
    const panel = panelAvance();
    expect(within(panel).getAllByText(t("progress.from_cache")).length).toBeGreaterThan(0);
    expect(within(panel).getByText(t("progress.from_cache_profiles", { count: 2 }))).toBeInTheDocument();
    expect(within(panel).queryByRole("region", { name: t("progress.profiles_title") })).not.toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: t("dossier_jobs.view_dossier") })).toBeInTheDocument();
  });

  it("CA9 · separates_transport_cancellation_and_generation_errors · cancelar detiene todo y nada revive", async () => {
    const user = userEvent.setup();
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    const cancelled = loadS510Fixture("personas-cancelada");
    alimentar(cancelled.frames.slice(0, 4));
    const [stale] = openSubs(FIX);
    // El servidor cierra el progreso al cancelar (ADR 0009): eso devuelve su POST.
    servidor.set(FIX, { ...cancelled.snapshot_final, status: "running" });

    await user.click(screen.getByRole("button", { name: t("person_research.cancel") }));
    await settle();
    const panel = panelAvance();
    expect(within(panel).getByText(t("progress.outcome.cancelled"))).toBeInTheDocument();
    expect(etapa(panel, "Buscar el perfil en PDL")).toBe(t("progress.status.cancelled"));

    const late = parseProgressEvent("stage_progress", { ...cancelled.frames[3].data, revision: 50, status: "completed" }, FIX)!;
    act(() => stale.handlers.onProgress?.(late, { eventId: "99" }));
    expect(etapa(panelAvance(), "Buscar el perfil en PDL")).toBe(t("progress.status.cancelled"));
  });

  it("CA9 · el corte de conexión se muestra aparte y no borra los parciales", async () => {
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    alimentar(loadS510Fixture("personas-pdl").frames.slice(0, 8));

    cortar(FIX, "network");
    await settle();
    const generando = panelGenerando("Ana Prueba")!.closest("div") as HTMLElement;
    expect(within(generando).getByText(t("dossier_jobs.connection_lost"))).toBeInTheDocument();
    const panel = panelAvance();
    expect(within(panel).getByRole("region", { name: t("progress.profiles_title") })).toBeInTheDocument();
    expect(within(panel).queryByText(t("dossier_jobs.connection_lost"))).not.toBeInTheDocument();
    expect(within(panel).queryByText(t("dossier_jobs.failed"))).not.toBeInTheDocument();
  });

  it("CA24 · aria-live (polite) anuncia hitos y no cada evento", async () => {
    render(<Pantalla />);
    await settle();
    await iniciarEjemplo(MODOS[0]);
    const pdl = loadS510Fixture("personas-pdl");
    const live = () => within(panelAvance()).getByRole("status");

    alimentar(pdl.frames.slice(0, 7));
    expect(live()).toHaveAttribute("aria-live", "polite");
    expect(live()).toHaveTextContent("");
    alimentar(pdl.frames.slice(7, 8));
    expect(live()).toHaveTextContent(t("progress.announce.profiles"));
    alimentar(pdl.frames.slice(8, 13));
    expect(live()).toHaveTextContent(t("progress.announce.profiles"));
    alimentar(pdl.frames.slice(13, 14));
    expect(live()).toHaveTextContent(t("progress.announce.report"));
    alimentar(pdl.frames.slice(14));
    await settle();
    expect(live()).toHaveTextContent(t("dossier_jobs.ready"));
  });

  it("CA24 · el texto de Web pública aclara que no hay búsqueda en vivo y la ETA es solo una estimación", async () => {
    const user = userEvent.setup();
    render(<Pantalla />);
    await settle();
    expect(screen.getByText(t("person_research.eta_estimate", { seconds: 40 }))).toBeInTheDocument();
    const web = screen.getByRole("button", { name: new RegExp(t("person_research.source_gemini")) });
    expect(web).toHaveTextContent(t("progress.no_live_web_search"));
    await user.click(web);
    expect(screen.getByText(t("person_research.eta_estimate", { seconds: 35 }))).toBeInTheDocument();
  });

  it("un job sin progress (anterior a S5.4) no muestra el panel nuevo", async () => {
    render(<Pantalla />);
    await settle();
    const { jobId } = await iniciar(MODOS[0]);
    publicar(jobId, { status: "completed", result: resultadoPersona("pdl", "d-1") }, "job_completed");
    await settle();
    expect(screen.queryByRole("region", { name: t("progress.panel_title") })).not.toBeInTheDocument();
  });
});
