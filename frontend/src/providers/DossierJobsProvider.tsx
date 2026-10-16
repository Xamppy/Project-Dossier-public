"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  DossierApiError,
  cancelDossierGenerationJob,
  createCorporateDossier,
  enqueuePersonResearch,
  fetchDossierGenerationJob,
  fetchDossierGenerationJobs,
  fetchEnqueueGoogleCalendarDossier,
  fetchEnqueueOutlookCalendarDossier,
  type CalendarProvider,
  type CalendarGenerarDossierItem,
  type CreateCorporateDossierPayload,
  type DossierGenerationJobApi,
  type DossierGenerationJobStatus,
  type OutlookReunionApi,
  type PersonResearchPayload,
  type PersonResearchApiResponse,
} from "@/lib/dossier-api";
import {
  openDossierJobStream,
  parseJobSnapshot,
  type DossierJobStreamError,
  type DossierJobStreamSubscription,
} from "@/lib/dossier-job-stream";
import {
  applyProgressEvent,
  mergeProgress,
  normalizeProgressSnapshot,
  type DossierJobProgressEvent,
} from "@/lib/dossier-job-progress";
import { classifyJobOutcome } from "@/lib/dossier-job-outcome";
import DossierJobProgressDetails from "@/components/dossier/DossierJobProgressDetails";
import { AUTH_ME_CHANGED_EVENT } from "@/hooks/useAuthMe";
import { isPdlProfileFoundInfoWarning } from "@/lib/translate-pdl-warning";
import {
  translateBackendWarning,
  translateDossierStatusMessage,
} from "@/lib/translate-backend-message";
import { resolveDossierOutputLanguage } from "@/lib/resolve-output-language";
import { findJobForEvent, isEventJobActive } from "@/lib/calendar-jobs";
import { formatCalendarMeetingInstant } from "@/lib/format";
import type { TranslationKey } from "@/i18n/types";
import { usePreferences, useTranslation } from "@/providers/PreferencesProvider";

const STORAGE_KEY = "dossier_active_job_ids";
const TOAST_JOB_IDS_KEY = "dossier_toast_job_ids";
// Solo el ID: la vista previa vive en el job del servidor, no en el navegador.
const SELECTED_PERSON_JOB_KEY = "dossier_person_selected_job_id";
const TERMINAL: DossierGenerationJobStatus[] = ["completed", "failed", "cancelled"];

type TrackedJob = DossierGenerationJobApi & {
  toastDismissed?: boolean;
};

/**
 * Estado de la conexión SSE de un job, separado de su `status`: un corte de red
 * no demuestra que la generación haya fallado. Sin entrada = conectado o conectando.
 */
export type DossierJobConnection =
  | { state: "interrupted"; reason: "session" | "transport" }
  | { state: "resyncing" };

type DossierJobsContextValue = {
  jobs: TrackedJob[];
  enqueueCalendarJob: (
    provider: CalendarProvider,
    options: { eventId: string; reunion?: OutlookReunionApi },
  ) => Promise<string>;
  enqueuePersonResearchJob: (payload: PersonResearchPayload) => Promise<string>;
  enqueueCorporateDossierJob: (
    payload: CreateCorporateDossierPayload,
    label: string,
    creditsEstimated?: number,
  ) => Promise<string>;
  cancelJob: (jobId: string) => Promise<void>;
  /** Con `provider`, solo cuentan los jobs de ese calendario (dos proveedores pueden repetir un id). */
  isEventGenerating: (eventId: string | undefined | null, provider?: CalendarProvider) => boolean;
  getJobForEvent: (
    eventId: string | undefined | null,
    provider?: CalendarProvider,
  ) => TrackedJob | undefined;
  getActivePersonJob: () => TrackedJob | undefined;
  getActiveCorporateJob: () => TrackedJob | undefined;
  dismissToast: (jobId: string) => void;
  /** Estado de la conexión en tiempo real del job; `undefined` si está conectado. */
  getJobConnection: (jobId: string) => DossierJobConnection | undefined;
  /** Recuperación manual tras un corte: un snapshot REST y, si sigue activo, un stream nuevo. */
  resyncJob: (jobId: string) => Promise<void>;
  /** Ejecución de Personas que se está mirando (S5.4). */
  selectedPersonJobId: string | null;
  selectPersonJob: (jobId: string | null) => void;
};

const DossierJobsContext = createContext<DossierJobsContextValue | null>(null);

function loadStoredJobIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveStoredJobIds(ids: string[]) {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    /* ignore */
  }
}

function loadToastJobIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(TOAST_JOB_IDS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveToastJobIds(ids: string[]) {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(TOAST_JOB_IDS_KEY, JSON.stringify(ids.slice(0, 12)));
  } catch {
    /* ignore */
  }
}

function loadSelectedPersonJobId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem(SELECTED_PERSON_JOB_KEY) || null;
  } catch {
    return null;
  }
}

function saveSelectedPersonJobId(id: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (id) sessionStorage.setItem(SELECTED_PERSON_JOB_KEY, id);
    else sessionStorage.removeItem(SELECTED_PERSON_JOB_KEY);
  } catch {
    /* ignore */
  }
}

function isActiveStatus(status: DossierGenerationJobStatus): boolean {
  return !TERMINAL.includes(status);
}

/** El corporativo manual usa un UUID local y una petición directa: no tiene stream. */
function hasServerStream(job: TrackedJob): boolean {
  return job.job_type !== "corporate_manual";
}

function statusRank(status: DossierGenerationJobStatus): number {
  if (status === "queued") return 0;
  if (status === "running") return 1;
  return 2;
}

/**
 * Aplica un snapshot del servidor sin retroceder: un estado terminal no se
 * reescribe y uno activo no vuelve atrás (`running` → `queued`). Así una
 * respuesta tardía o duplicada no pisa lo que ya llegó por el stream.
 * Conserva los campos solo visuales, como `toastDismissed`.
 */
function mergeSnapshot(prev: TrackedJob[], incoming: DossierGenerationJobApi): TrackedJob[] {
  const idx = prev.findIndex((j) => j.id === incoming.id);
  const progress = normalizeProgressSnapshot(incoming.progress);
  if (idx < 0) return [...prev, { ...incoming, progress }];
  const current = prev[idx];
  if (!isActiveStatus(current.status)) return prev;
  if (statusRank(incoming.status) < statusRank(current.status)) return prev;
  const next = [...prev];
  // El progreso se fusiona por revisión (S5.4): un snapshot viejo no lo hace retroceder.
  next[idx] = { ...current, ...incoming, progress: mergeProgress(current.progress, progress) };
  return next;
}

/**
 * Aplica un evento de progreso al job de su stream. Un job terminal ya no cambia:
 * lo que llegue después de cancelar o terminar no revive nada.
 */
function applyJobProgressEvent(
  prev: TrackedJob[],
  jobId: string,
  event: DossierJobProgressEvent,
): TrackedJob[] {
  if (event.job_id !== jobId) return prev;
  const idx = prev.findIndex((j) => j.id === jobId);
  if (idx < 0 || !isActiveStatus(prev[idx].status)) return prev;
  const current = prev[idx];
  const progress = applyProgressEvent(current.progress, event);
  if (progress === current.progress) return prev;
  const next = [...prev];
  next[idx] = { ...current, progress };
  return next;
}

function withoutKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  if (!(key in record)) return record;
  const next = { ...record };
  delete next[key];
  return next;
}

function connectionForError(
  error: DossierJobStreamError | DossierApiError,
): DossierJobConnection {
  const isSession =
    error instanceof DossierApiError
      ? error.status === 401 || error.status === 403
      : error.kind === "unauthorized" || error.kind === "forbidden";
  return { state: "interrupted", reason: isSession ? "session" : "transport" };
}

function calendarMeetingLabelFromReunion(
  reunion: OutlookReunionApi | undefined,
  preferences: ReturnType<typeof usePreferences>["preferences"],
): string | null {
  const tema = reunion?.tema?.trim();
  if (!tema) return null;
  const when = formatCalendarMeetingInstant(reunion?.inicio, preferences);
  return when ? `${tema} · ${when}` : tema;
}

function personJobWarning(job: TrackedJob): string | undefined {
  if (job.job_type !== "person_manual" || job.status !== "completed" || !job.result) {
    return undefined;
  }
  const personResult = job.result as PersonResearchApiResponse;
  const criticalWarnings = (personResult.warnings ?? []).filter(
    (w) =>
      !isPdlProfileFoundInfoWarning(w) &&
      !w.toLowerCase().includes("no se encontró información adicional") &&
      !w.toLowerCase().includes("no se encontró perfil verificable"),
  );
  return criticalWarnings[0];
}

export function DossierJobsProvider({ children }: { children: ReactNode }) {
  const { preferences } = usePreferences();
  const [jobs, setJobs] = useState<TrackedJob[]>([]);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;
  const corporateAbortRef = useRef<Map<string, AbortController>>(new Map());
  const [connections, setConnections] = useState<Record<string, DossierJobConnection>>({});
  // Hasta restaurar no se escribe sessionStorage: se perderían los IDs por restaurar.
  const [hydrated, setHydrated] = useState(false);
  // Cambia al cambiar de sesión u organización y relanza la restauración.
  const [sessionKey, setSessionKey] = useState(0);
  // Una suscripción SSE vigente por job remoto activo. Lo que llegue de una
  // suscripción que ya no está en el mapa (cerrada, de otra sesión) se ignora.
  const streamsRef = useRef<Map<string, DossierJobStreamSubscription>>(new Map());
  // Se incrementa al desmontar o cambiar de sesión: invalida respuestas en vuelo.
  const epochRef = useRef(0);
  // Ejecución de Personas que se está mirando (S5.4). Independiente del job activo:
  // sobrevive al terminal, a la navegación y, por sessionStorage, a una recarga.
  const [selectedPersonJobId, setSelectedPersonJobId] = useState<string | null>(null);
  // ID ya pedido por GET para restaurar la selección: una sola lectura por ID.
  const selectionFetchRef = useRef<string | null>(null);

  const forgetSelection = useCallback((jobId: string) => {
    setSelectedPersonJobId((current) => (current === jobId ? null : current));
    if (loadSelectedPersonJobId() === jobId) saveSelectedPersonJobId(null);
  }, []);

  const closeAllStreams = useCallback(() => {
    for (const stream of streamsRef.current.values()) stream.close();
    streamsRef.current.clear();
  }, []);

  useEffect(() => {
    return () => {
      epochRef.current += 1;
      closeAllStreams();
    };
  }, [closeAllStreams]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      const restored: DossierGenerationJobApi[] = [];
      try {
        const { jobs: activeFromApi } = await fetchDossierGenerationJobs({ activeOnly: true });
        if (cancelled) return;
        const byId = new Map<string, DossierGenerationJobApi>();
        for (const j of activeFromApi) byId.set(j.id, j);
        for (const id of [...loadStoredJobIds(), ...loadToastJobIds()]) {
          if (byId.has(id)) continue;
          try {
            byId.set(id, await fetchDossierGenerationJob(id));
          } catch {
            /* expirado, 404 o de otra identidad: no se restaura */
          }
          if (cancelled) return;
        }
        restored.push(...byId.values());
      } catch {
        /* sin sesión o API caída */
      }
      if (cancelled) return;
      // Fusión, no reemplazo: no se pierde lo encolado ni lo llegado por SSE mientras tanto.
      setJobs((prev) => restored.reduce(mergeSnapshot, prev));
      // sessionStorage refleja siempre la última selección, también la hecha antes de restaurar.
      setSelectedPersonJobId(loadSelectedPersonJobId());
      setHydrated(true);
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [sessionKey]);

  // El almacenamiento se sincroniza desde el estado resultante, no dentro de cada actualización.
  useEffect(() => {
    if (!hydrated) return;
    saveStoredJobIds(jobs.filter((j) => isActiveStatus(j.status)).map((j) => j.id));
    saveToastJobIds(
      jobs.filter((j) => !isActiveStatus(j.status) && !j.toastDismissed).map((j) => j.id),
    );
  }, [jobs, hydrated]);

  // Cambio de sesión u organización (señal existente de useAuthMe): nada de la
  // identidad anterior sigue conectado ni visible. Los corporativos locales en
  // curso se conservan como hasta ahora.
  useEffect(() => {
    function onSessionChange() {
      epochRef.current += 1;
      closeAllStreams();
      setJobs((prev) => prev.filter((j) => !hasServerStream(j)));
      setConnections({});
      setSelectedPersonJobId(null);
      saveSelectedPersonJobId(null);
      selectionFetchRef.current = null;
      setHydrated(false);
      setSessionKey((k) => k + 1);
    }
    window.addEventListener(AUTH_ME_CHANGED_EVENT, onSessionChange);
    return () => window.removeEventListener(AUTH_ME_CHANGED_EVENT, onSessionChange);
  }, [closeAllStreams]);

  const handleStreamError = useCallback(
    (jobId: string, error: DossierJobStreamError) => {
      if (error.kind === "not_found") {
        setJobs((prev) => prev.filter((j) => j.id !== jobId));
        setConnections((prev) => withoutKey(prev, jobId));
        forgetSelection(jobId);
        return;
      }
      setConnections((prev) => ({ ...prev, [jobId]: connectionForError(error) }));
    },
    [forgetSelection],
  );

  const openStream = useCallback(
    (jobId: string) => {
      let stream: DossierJobStreamSubscription | null = null;
      const isCurrent = () => stream !== null && streamsRef.current.get(jobId) === stream;
      stream = openDossierJobStream(jobId, {
        onSnapshot: (snapshot) => {
          if (isCurrent()) setJobs((prev) => mergeSnapshot(prev, snapshot));
        },
        // Misma suscripción para el progreso (S5.4): ningún componente abre streams propios.
        onProgress: (event) => {
          if (isCurrent()) setJobs((prev) => applyJobProgressEvent(prev, jobId, event));
        },
        onError: (error) => {
          if (!isCurrent()) return;
          streamsRef.current.delete(jobId);
          stream?.close();
          handleStreamError(jobId, error);
        },
      });
      streamsRef.current.set(jobId, stream);
    },
    [handleStreamError],
  );

  // Reconciliación: abre lo que falta y cierra lo que sobra, sin tocar las
  // conexiones que siguen siendo válidas. Un evento nuevo no reabre nada.
  useEffect(() => {
    const wanted = new Set(
      jobs
        .filter((j) => hasServerStream(j) && isActiveStatus(j.status) && !connections[j.id])
        .map((j) => j.id),
    );
    for (const [jobId, stream] of streamsRef.current) {
      if (wanted.has(jobId)) continue;
      stream.close();
      streamsRef.current.delete(jobId);
    }
    for (const jobId of wanted) {
      if (!streamsRef.current.has(jobId)) openStream(jobId);
    }
  }, [jobs, connections, openStream]);

  // Restaura la ejecución seleccionada si no está entre los jobs seguidos (p. ej. tras
  // recargar con un job ya terminado y su aviso cerrado): un único GET, no un sondeo.
  useEffect(() => {
    const jobId = selectedPersonJobId;
    if (!hydrated || !jobId || jobs.some((j) => j.id === jobId)) return;
    if (selectionFetchRef.current === jobId) return;
    selectionFetchRef.current = jobId;
    const epoch = epochRef.current;
    void fetchDossierGenerationJob(jobId)
      .then((raw) => {
        if (epoch !== epochRef.current) return;
        const job = parseJobSnapshot(raw, jobId);
        if (!job) {
          forgetSelection(jobId);
          return;
        }
        setJobs((prev) => mergeSnapshot(prev, job));
      })
      .catch((err: unknown) => {
        if (epoch !== epochRef.current) return;
        if (err instanceof DossierApiError && err.status === 404) forgetSelection(jobId);
      });
  }, [hydrated, selectedPersonJobId, jobs, forgetSelection]);

  const selectPersonJob = useCallback((jobId: string | null) => {
    selectionFetchRef.current = null;
    setSelectedPersonJobId(jobId);
    saveSelectedPersonJobId(jobId);
  }, []);

  const resyncJob = useCallback(async (jobId: string) => {
    const epoch = epochRef.current;
    setConnections((prev) => ({ ...prev, [jobId]: { state: "resyncing" } }));
    try {
      const fresh = parseJobSnapshot(await fetchDossierGenerationJob(jobId), jobId);
      if (epoch !== epochRef.current) return;
      if (!fresh) {
        setConnections((prev) => ({ ...prev, [jobId]: { state: "interrupted", reason: "transport" } }));
        return;
      }
      setJobs((prev) => mergeSnapshot(prev, fresh));
      // Sin entrada de conexión, la reconciliación abre un stream nuevo si sigue activo.
      setConnections((prev) => withoutKey(prev, jobId));
    } catch (err) {
      if (epoch !== epochRef.current) return;
      if (err instanceof DossierApiError && err.status === 404) {
        setJobs((prev) => prev.filter((j) => j.id !== jobId));
        setConnections((prev) => withoutKey(prev, jobId));
        forgetSelection(jobId);
        return;
      }
      const connection =
        err instanceof DossierApiError
          ? connectionForError(err)
          : ({ state: "interrupted", reason: "transport" } as const);
      setConnections((prev) => ({ ...prev, [jobId]: connection }));
    }
  }, [forgetSelection]);

  const getJobConnection = useCallback(
    (jobId: string) => connections[jobId],
    [connections],
  );

  const enqueueCalendarJob = useCallback(
    async (
      provider: CalendarProvider,
      options: { eventId: string; reunion?: OutlookReunionApi },
    ): Promise<string> => {
      const enqueue =
        provider === "google"
          ? fetchEnqueueGoogleCalendarDossier
          : fetchEnqueueOutlookCalendarDossier;
      const res = await enqueue({
        eventId: options.eventId,
        reunion: options.reunion,
        output_language: resolveDossierOutputLanguage(preferences),
      });
      if (!res.job_id) {
        throw new DossierApiError(502, "La API no devolvió job_id.");
      }
      const job: TrackedJob = {
        id: res.job_id,
        status: res.status ?? "queued",
        job_type: "calendar_manual",
        calendar_provider: provider === "google" ? "google" : "microsoft",
        external_event_id: options.eventId,
        meeting_label:
          calendarMeetingLabelFromReunion(options.reunion, preferences) ??
          res.meeting_label ??
          options.reunion?.tema ??
          null,
        credits_estimated: res.credits_estimated ?? 0,
        credits_consumed: 0,
      };
      setJobs((prev) => mergeSnapshot(prev, job));
      return res.job_id;
    },
    [preferences],
  );

  const enqueuePersonResearchJob = useCallback(
    async (payload: PersonResearchPayload): Promise<string> => {
      const res = await enqueuePersonResearch(payload);
      if (!res.job_id) {
        throw new DossierApiError(502, "La API no devolvió job_id.");
      }
      const job: TrackedJob = {
        id: res.job_id,
        status: res.status ?? "queued",
        job_type: "person_manual",
        calendar_provider: null,
        external_event_id: null,
        meeting_label: res.meeting_label ?? payload.full_name ?? null,
        credits_estimated: res.credits_estimated ?? 0,
        credits_consumed: 0,
      };
      setJobs((prev) => mergeSnapshot(prev, job));
      return res.job_id;
    },
    [],
  );

  const enqueueCorporateDossierJob = useCallback(
    async (
      payload: CreateCorporateDossierPayload,
      label: string,
      creditsEstimated = 0,
    ): Promise<string> => {
      const jobId = crypto.randomUUID();
      const controller = new AbortController();
      corporateAbortRef.current.set(jobId, controller);

      const job: TrackedJob = {
        id: jobId,
        status: "running",
        job_type: "corporate_manual",
        calendar_provider: null,
        external_event_id: null,
        meeting_label: label,
        credits_estimated: creditsEstimated,
        credits_consumed: 0,
      };

      setJobs((prev) => [...prev.filter((j) => j.id !== job.id), job]);

      void (async () => {
        try {
          const res = await createCorporateDossier(payload, controller.signal);
          corporateAbortRef.current.delete(jobId);
          setJobs((prev) =>
            prev.map((j) =>
              j.id === jobId
                ? {
                    ...j,
                    status: "completed" as const,
                    result: res,
                    credits_consumed: res.credits_consumed,
                  }
                : j,
            ),
          );
        } catch (err) {
          corporateAbortRef.current.delete(jobId);
          const cancelled = err instanceof Error && err.name === "AbortError";
          setJobs((prev) =>
            prev.map((j) =>
              j.id === jobId
                ? {
                    ...j,
                    status: cancelled ? ("cancelled" as const) : ("failed" as const),
                    error_message:
                      cancelled || !(err instanceof DossierApiError)
                        ? null
                        : err.message || null,
                  }
                : j,
            ),
          );
        }
      })();

      return jobId;
    },
    [],
  );

  const cancelJob = useCallback(
    async (jobId: string) => {
      const existing = jobsRef.current.find((j) => j.id === jobId);
      if (
        existing?.job_type === "corporate_manual" &&
        (existing.status === "queued" || existing.status === "running")
      ) {
        corporateAbortRef.current.get(jobId)?.abort();
        corporateAbortRef.current.delete(jobId);
        setJobs((prev) =>
          prev.map((j) => (j.id === jobId ? { ...j, status: "cancelled" as const } : j)),
        );
        return;
      }

      // Cancela el trabajo en el servidor; el stream se cierra al llegar el estado terminal.
      const updated = await cancelDossierGenerationJob(jobId);
      setJobs((prev) => mergeSnapshot(prev, updated));
    },
    [],
  );

  const getActivePersonJob = useCallback(() => {
    return jobs.find(
      (j) =>
        j.job_type === "person_manual" &&
        (j.status === "queued" || j.status === "running"),
    );
  }, [jobs]);

  const getActiveCorporateJob = useCallback(() => {
    return jobs.find(
      (j) =>
        j.job_type === "corporate_manual" &&
        (j.status === "queued" || j.status === "running"),
    );
  }, [jobs]);

  const isEventGenerating = useCallback(
    (eventId: string | undefined | null, provider?: CalendarProvider) =>
      isEventJobActive(jobs, eventId, provider),
    [jobs],
  );

  const getJobForEvent = useCallback(
    (eventId: string | undefined | null, provider?: CalendarProvider) =>
      findJobForEvent(jobs, eventId, provider),
    [jobs],
  );

  const dismissToast = useCallback((jobId: string) => {
    setJobs((prev) => prev.map((j) => (j.id === jobId ? { ...j, toastDismissed: true } : j)));
  }, []);

  const value = useMemo(
    () => ({
      jobs,
      enqueueCalendarJob,
      enqueuePersonResearchJob,
      enqueueCorporateDossierJob,
      cancelJob,
      isEventGenerating,
      getJobForEvent,
      getActivePersonJob,
      getActiveCorporateJob,
      dismissToast,
      getJobConnection,
      resyncJob,
      selectedPersonJobId,
      selectPersonJob,
    }),
    [
      jobs,
      enqueueCalendarJob,
      enqueuePersonResearchJob,
      enqueueCorporateDossierJob,
      cancelJob,
      isEventGenerating,
      getJobForEvent,
      getActivePersonJob,
      getActiveCorporateJob,
      dismissToast,
      getJobConnection,
      resyncJob,
      selectedPersonJobId,
      selectPersonJob,
    ],
  );

  return (
    <DossierJobsContext.Provider value={value}>
      {children}
      <DossierJobToasts
        jobs={jobs}
        connections={connections}
        onDismiss={dismissToast}
        onCancel={cancelJob}
        onResync={resyncJob}
      />
    </DossierJobsContext.Provider>
  );
}

const PERSON_RESEARCH_PATH = "/dashboard/person-research";
const CORPORATE_PATH = "/dashboard/corporate";

const HIDE_ACTIVE_TOAST_ON_PATH: Record<string, string> = {
  person_manual: PERSON_RESEARCH_PATH,
  corporate_manual: CORPORATE_PATH,
};

function jobToastLabel(
  job: TrackedJob,
  t: (key: TranslationKey, params?: Record<string, string | number>) => string,
): string {
  if (job.meeting_label) return job.meeting_label;
  if (job.job_type === "person_manual") return t("dossier_jobs.person_label");
  if (job.job_type === "corporate_manual") return t("dossier_jobs.corporate_label");
  return t("dossier_jobs.default_label");
}

function DossierJobToasts({
  jobs,
  connections,
  onDismiss,
  onCancel,
  onResync,
}: {
  jobs: TrackedJob[];
  connections: Record<string, DossierJobConnection>;
  onDismiss: (jobId: string) => void;
  onCancel: (jobId: string) => Promise<void>;
  onResync: (jobId: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const pathname = usePathname();
  const [cancelErr, setCancelErr] = useState<string | null>(null);
  const visible = jobs.filter((j) => {
    if (j.toastDismissed) return false;
    const isTerminal =
      j.status === "completed" || j.status === "failed" || j.status === "cancelled";
    const isActive = j.status === "queued" || j.status === "running";
    if (!isActive && !isTerminal) return false;
    const hideOnPath = HIDE_ACTIVE_TOAST_ON_PATH[j.job_type];
    if (hideOnPath && pathname === hideOnPath && isActive) {
      return false;
    }
    return true;
  });

  if (visible.length === 0) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-3 sm:w-[24rem]"
      aria-live="polite"
    >
      {visible.map((job) => {
        const label = jobToastLabel(job, t);
        // Clasificación pura del resultado (S5.4): un guardado `failed` no es éxito y
        // un job `failed` puede conservar información útil.
        const outcome = classifyJobOutcome(job);
        const href = outcome.savedHref;
        const isActive = job.status === "queued" || job.status === "running";
        const isFail = outcome.kind === "failed" || outcome.kind === "failed_with_partial";
        const isPartial = outcome.kind === "partial";
        const isOk = outcome.kind === "complete";
        const isCancelled = outcome.kind === "cancelled";
        const missing = isPartial
          ? [
              ...outcome.failedAgents.map((a) => t(`progress.agent.${a}` as TranslationKey)),
              ...outcome.failedPeople,
            ]
          : [];
        const availableHref =
          outcome.kind === "failed_with_partial" && job.job_type === "person_manual"
            ? `${PERSON_RESEARCH_PATH}?job=${encodeURIComponent(job.id)}`
            : null;
        const calendarWarning =
          isOk && job.job_type === "calendar_manual" && job.result
            ? (job.result as CalendarGenerarDossierItem).dossier_persona_research?.warnings?.[0]
            : undefined;
        const personWarning =
          (isPartial || isFail) && job.job_type === "person_manual"
            ? personJobWarning(job)
            : undefined;
        const connection = isActive ? connections[job.id] : undefined;

        return (
          <div
            key={job.id}
            className="rounded-xl border px-5 py-4 shadow-xl"
            style={{
              borderColor: "var(--border-strong)",
              backgroundColor: "var(--bg-panel)",
              color: "var(--text-primary)",
              boxShadow: "0 12px 32px rgba(10, 20, 40, 0.2)",
            }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-base font-semibold leading-snug">{label}</p>
                <p className="mt-1.5 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
                  {isActive && t("dossier_jobs.generating")}
                  {isOk && t("dossier_jobs.ready")}
                  {isPartial && t("dossier_jobs.partial")}
                  {isFail &&
                    (job.error_message
                      ? translateDossierStatusMessage(job.error_message, t) ??
                        t("errors.generation_failed")
                      : t("dossier_jobs.failed"))}
                  {isCancelled && t("dossier_jobs.cancelled")}
                </p>
                {calendarWarning && translateBackendWarning(calendarWarning, t) ? (
                  <p className="mt-1.5 text-sm ui-text-warning line-clamp-3 leading-relaxed">
                    {translateBackendWarning(calendarWarning, t)}
                  </p>
                ) : null}
                {personWarning && translateBackendWarning(personWarning, t) ? (
                  <p className="mt-1.5 text-sm ui-text-warning line-clamp-3 leading-relaxed">
                    {translateBackendWarning(personWarning, t)}
                  </p>
                ) : null}
                {isActive && job.job_type === "calendar_manual" ? (
                  // Avance compacto de la reunión: búsquedas de la empresa y una línea por asistente.
                  <DossierJobProgressDetails progress={job.progress} variant="compact" />
                ) : null}
                {missing.length > 0 ? (
                  <p className="mt-1.5 text-sm ui-text-warning leading-relaxed">
                    {t("progress.outcome.missing", { items: missing.join(", ") })}
                  </p>
                ) : null}
                {outcome.kind === "failed_with_partial" ? (
                  <p className="mt-1.5 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
                    {t("progress.available_hint")}
                  </p>
                ) : null}
                <JobConnectionNotice connection={connection} />
              </div>
              <button
                type="button"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-base opacity-60 transition hover:bg-[var(--hover-overlay)] hover:opacity-100"
                onClick={() => onDismiss(job.id)}
                aria-label={t("dossier_jobs.dismiss")}
              >
                ×
              </button>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4">
              {availableHref ? (
                <Link
                  href={availableHref}
                  className="inline-block text-sm font-medium underline"
                  onClick={() => onDismiss(job.id)}
                >
                  {t("progress.view_available")}
                </Link>
              ) : null}
              {(isOk || isPartial) && href && (
                <Link
                  href={href}
                  className="inline-block text-sm font-medium underline"
                  onClick={() => onDismiss(job.id)}
                >
                  {job.job_type === "person_manual" || job.job_type === "corporate_manual"
                    ? t("dossier_jobs.view_dossier")
                    : t("dossier_jobs.view_folder")}
                </Link>
              )}
              <JobReconnectButton
                connection={connection}
                onResync={() => void onResync(job.id)}
                className="text-sm font-medium underline transition hover:opacity-80"
              />
              {isActive && (
                <button
                  type="button"
                  className="text-sm font-medium transition hover:opacity-80"
                  style={{ color: "var(--alert-error-text)" }}
                  onClick={() => {
                    setCancelErr(null);
                    void onCancel(job.id).catch((e) => {
                      setCancelErr(
                        e instanceof DossierApiError ? e.message : t("dossier_jobs.failed"),
                      );
                    });
                  }}
                >
                  {t("dossier_jobs.cancel")}
                </button>
              )}
            </div>
            {cancelErr ? (
              <p className="mt-2 text-sm text-red-400" role="alert">
                {cancelErr}
              </p>
            ) : null}
            {isActive && (
              <div
                className="mt-3 h-1.5 w-full overflow-hidden rounded-full"
                style={{ backgroundColor: "var(--border-default)" }}
              >
                <div
                  className="h-full w-1/3 animate-pulse rounded-full"
                  style={{ backgroundColor: "var(--accent-primary)" }}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Aviso de conexión interrumpida de un job activo; nada si está conectado. */
export function JobConnectionNotice({
  connection,
  className = "mt-1.5 text-sm ui-text-warning leading-relaxed",
}: {
  connection: DossierJobConnection | undefined;
  className?: string;
}) {
  const { t } = useTranslation();
  if (connection?.state !== "interrupted") return null;
  return (
    <p className={className} role="status">
      {connection.reason === "session"
        ? t("auth.error.session_expired")
        : t("dossier_jobs.connection_lost")}
    </p>
  );
}

/**
 * Recuperación manual tras un corte de transporte. No se ofrece si el corte es
 * de sesión: volver a pedir con el mismo token daría otra vez 401.
 */
export function JobReconnectButton({
  connection,
  onResync,
  className,
}: {
  connection: DossierJobConnection | undefined;
  onResync: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const resyncing = connection?.state === "resyncing";
  if (!resyncing && !(connection?.state === "interrupted" && connection.reason === "transport")) {
    return null;
  }
  return (
    <button
      type="button"
      className={className}
      style={{ color: "var(--text-primary)" }}
      disabled={resyncing}
      onClick={onResync}
    >
      {resyncing ? t("dossier_jobs.reconnecting") : t("dossier_jobs.reconnect")}
    </button>
  );
}

export function useDossierJobs(): DossierJobsContextValue {
  const ctx = useContext(DossierJobsContext);
  if (!ctx) {
    throw new Error("useDossierJobs debe usarse dentro de DossierJobsProvider");
  }
  return ctx;
}
