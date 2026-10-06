import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import { clearCalendarEventsCache } from "@/lib/calendar-events-cache";
import { findJobForEvent, isEventJobActive } from "@/lib/calendar-jobs";
import { DossierApiError, persistAuthToken } from "@/lib/dossier-api";
import type { CalendarEventosRangoResponse } from "@/lib/dossier-api";
import MeetingsCalendarSection from "./MeetingsCalendarSection";

const fetchRango = vi.fn();
const enqueueCalendarJob = vi.fn();
const proveedorConfigurado = vi.fn();
const state: { jobs: Record<string, unknown>[]; ready: boolean } = { jobs: [], ready: true };

vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return {
    ...actual,
    fetchCalendarEventosPorIntervalo: (...a: unknown[]) => fetchRango(...a),
    fetchGoogleIntegrationStartAsJson: vi.fn().mockResolvedValue({ authorize_url: "https://example.test/g" }),
    fetchMicrosoftIntegrationStartAsJson: vi.fn().mockResolvedValue({ authorize_url: "https://example.test/m" }),
    fetchCalendarDiagnostico: vi.fn().mockResolvedValue({ ok: true }),
    fetchCalendarProviderConfigured: (p: string) => proveedorConfigurado(p),
  };
});

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  const prefs = { locale: "es", timezone: "America/Santiago", timezoneFollowSystem: false };
  const value = () => ({
    preferences: prefs,
    effectiveTimezone: "America/Santiago",
    ready: state.ready,
    t,
    locale: "es",
  });
  return {
    usePreferences: value,
    useTranslation: () => ({ t, locale: "es", preferences: prefs, setLocale: () => {} }),
  };
});

vi.mock("@/providers/DossierJobsProvider", () => ({
  useDossierJobs: () => ({
    enqueueCalendarJob,
    isEventGenerating: (id: string, p?: "google" | "microsoft") => isEventJobActive(state.jobs as never, id, p),
    getJobForEvent: (id: string, p?: "google" | "microsoft") => findJobForEvent(state.jobs as never, id, p),
  }),
}));

/** Ancho que "mide" el contenedor del calendario (jsdom no tiene layout). */
const medida = { ancho: 1100 };

const SEMANA = { desde: "2026-10-05T00:00:00-03:00", hasta: "2026-10-12T00:00:00-03:00" };

function respuesta(reuniones: Record<string, unknown>[], extra: Partial<CalendarEventosRangoResponse> = {}): CalendarEventosRangoResponse {
  return {
    total: reuniones.length,
    reuniones: reuniones as never,
    mensaje: null,
    rango: null,
    completo: true,
    motivoIncompleto: null,
    ...extra,
  };
}

const reunionG = { id: "g1", tema: "Reunión Acme", inicio: "2026-10-06T13:00:00Z", fin: "2026-10-06T14:00:00Z", descripcion: "Contacto: Ana" };
const reunionM = { id: "m1", tema: "Revisión Globex", inicio: "2026-10-06T15:00:00Z", fin: "2026-10-06T16:00:00Z" };

function porProveedor(g: () => unknown, m: () => unknown) {
  fetchRango.mockImplementation(async (p: string) => (p === "google" ? g() : m())); // async: un throw es un rechazo, como en fetch
}

function rechazo(status: number, msg: string) {
  return () => {
    throw new DossierApiError(status, msg);
  };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-07T15:00:00Z"));
  fetchRango.mockReset();
  enqueueCalendarJob.mockReset();
  proveedorConfigurado.mockReset();
  proveedorConfigurado.mockResolvedValue(true);
  state.jobs = [];
  state.ready = true;
  clearCalendarEventsCache();
  persistAuthToken("jwt-ana", true);
  medida.ancho = 1100;
  const original = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
    return this.hasAttribute("data-calendar-container") ? medida.ancho : (original?.get?.call(this) ?? 0);
  });
});
afterEach(() => vi.useRealTimers());

const setupUser = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("MeetingsCalendarSection", () => {
  it("consulta ambos proveedores con la semana visible y pinta los eventos con su etiqueta (CA1)", async () => {
    porProveedor(() => respuesta([reunionG]), () => respuesta([reunionM]));
    render(<MeetingsCalendarSection />);

    expect(await screen.findByText("Reunión Acme")).toBeInTheDocument();
    expect(screen.getByText("Revisión Globex")).toBeInTheDocument();
    const llamadas = fetchRango.mock.calls.map((c) => [c[0], c[1]]);
    expect(llamadas).toContainEqual(["google", SEMANA]);
    expect(llamadas).toContainEqual(["microsoft", SEMANA]);
  });

  it("navegar solicita la ventana siguiente", async () => {
    const user = setupUser();
    porProveedor(() => respuesta([]), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    await waitFor(() => expect(fetchRango).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await waitFor(() =>
      expect(fetchRango.mock.calls.some((c) => c[1].desde === "2026-10-12T00:00:00-03:00")).toBe(true),
    );
  });

  it("si el calendario es estrecho (móvil o tableta con menú lateral) la vista inicial es Día", async () => {
    medida.ancho = 414;
    porProveedor(() => respuesta([]), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    await waitFor(() => expect(fetchRango).toHaveBeenCalled());
    expect(fetchRango.mock.calls[0][1]).toEqual({
      desde: "2026-10-07T00:00:00-03:00",
      hasta: "2026-10-08T00:00:00-03:00",
    });
    expect(screen.getByRole("button", { name: "Día" })).toHaveAttribute("aria-pressed", "true");
  });

  it("con ancho suficiente (≥ 640 px) la vista inicial es Semana", async () => {
    medida.ancho = 700;
    porProveedor(() => respuesta([]), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    await waitFor(() => expect(fetchRango).toHaveBeenCalled());
    expect(fetchRango.mock.calls[0][1]).toEqual(SEMANA);
    expect(screen.getByRole("button", { name: "Semana" })).toHaveAttribute("aria-pressed", "true");
  });

  it("no monta ni consulta hasta que las preferencias están listas", () => {
    state.ready = false;
    porProveedor(() => respuesta([]), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    expect(fetchRango).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Siguiente" })).toBeNull();
  });

  it("el filtro Google/Outlook oculta el otro proveedor y marca el botón activo", async () => {
    const user = setupUser();
    porProveedor(() => respuesta([reunionG]), () => respuesta([reunionM]));
    render(<MeetingsCalendarSection />);
    await screen.findByText("Reunión Acme");

    const filtros = screen.getByRole("group", { name: "Filtrar por calendario" });
    await user.click(within(filtros).getByRole("button", { name: /Google/ }));
    expect(within(filtros).getByRole("button", { name: /Google/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Reunión Acme")).toBeInTheDocument();
    expect(screen.queryByText("Revisión Globex")).toBeNull();

    await user.click(within(filtros).getByRole("button", { name: "Todas" }));
    expect(await screen.findByText("Revisión Globex")).toBeInTheDocument();
  });

  it("Google falla y Outlook responde: se ve Outlook más el error de Google con opción de reintentar (CA5)", async () => {
    const user = setupUser();
    porProveedor(rechazo(502, "Google no responde"), () => respuesta([reunionM]));
    render(<MeetingsCalendarSection />);

    expect(await screen.findByText("Revisión Globex")).toBeInTheDocument();
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Google");
    expect(alerta).toHaveTextContent("Google no responde");

    const antes = fetchRango.mock.calls.length;
    await user.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(fetchRango.mock.calls.length).toBeGreaterThan(antes));
  });

  it("proveedor desconectado se distingue de un error (CA5)", async () => {
    porProveedor(rechazo(404, "No hay Google Calendar conectado"), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    await waitFor(() => expect(screen.getByText(/Google no está conectado/)).toBeInTheDocument());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getAllByRole("button", { name: /conectar/i }).length).toBeGreaterThan(0);
  });

  it("si Outlook no está configurado en el servidor, no ofrece conectarlo ni filtrarlo", async () => {
    proveedorConfigurado.mockImplementation(async (p: string) => p === "google");
    porProveedor(() => respuesta([reunionG]), rechazo(404, "No hay Outlook conectado"));
    render(<MeetingsCalendarSection />);
    await screen.findByText("Reunión Acme");

    await waitFor(() => expect(screen.queryByRole("button", { name: /Conectar Outlook/ })).toBeNull());
    const filtros = screen.getByRole("group", { name: "Filtrar por calendario" });
    expect(within(filtros).queryByRole("button", { name: /Outlook/ })).toBeNull();
    expect(within(filtros).getByRole("button", { name: /Google/ })).toBeInTheDocument();
  });

  it("un período vacío lo dice y mantiene el calendario navegable (CA5)", async () => {
    porProveedor(() => respuesta([]), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    expect(await screen.findByText("No hay reuniones en este período.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeEnabled();
    expect(screen.queryByText(/no está conectado/)).toBeNull();
  });

  it("carga incompleta: avisa con el motivo y nunca afirma que todo está cargado (CA2)", async () => {
    porProveedor(
      () => respuesta([reunionG], { completo: false, motivoIncompleto: "limite_paginas" }),
      () => respuesta([]),
    );
    render(<MeetingsCalendarSection />);
    const aviso = await screen.findByText(/más reuniones de las que se pueden mostrar/);
    expect(aviso).toHaveTextContent("Google");
    expect(screen.queryByText("No hay reuniones en este período.")).toBeNull();
  });

  it("avisa de registros sin fecha válida sin romper la vista (CA8)", async () => {
    porProveedor(() => respuesta([reunionG, { id: "x", tema: "Roto", inicio: "???" }]), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    expect(await screen.findByText("Reunión Acme")).toBeInTheDocument();
    expect(screen.getByText(/1 registros sin fecha válida/)).toBeInTheDocument();
    expect(screen.queryByText("Roto")).toBeNull();
  });

  it("abrir una reunión muestra el detalle sin generar nada, y Escape devuelve el foco (CA7, CA11)", async () => {
    const user = setupUser();
    porProveedor(() => respuesta([reunionG]), () => respuesta([]));
    render(<MeetingsCalendarSection />);
    const evento = (await screen.findByText("Reunión Acme")).closest('[role="button"]') as HTMLElement;
    evento.focus();
    await user.keyboard("{Enter}");

    const dialogo = await screen.findByRole("dialog", { name: "Reunión Acme" });
    expect(dialogo).toBeInTheDocument();
    expect(enqueueCalendarJob).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(evento);
  });

  it("terminar el job de otra reunión no cambia la selección ni abre su resultado (CA7)", async () => {
    const user = setupUser();
    porProveedor(() => respuesta([reunionG]), () => respuesta([reunionM]));
    const { rerender } = render(<MeetingsCalendarSection />);
    await user.click(await screen.findByText("Reunión Acme"));
    await screen.findByRole("dialog", { name: "Reunión Acme" });

    state.jobs = [
      {
        id: "j", status: "completed", job_type: "calendar_manual", calendar_provider: "microsoft", external_event_id: "m1",
        result: { reunion: {}, dossier_generado: "x", dossier_corporativo: "# Informe de Globex", dossier_persona: null },
      },
    ];
    await act(async () => rerender(<MeetingsCalendarSection />));
    expect(screen.getByRole("dialog", { name: "Reunión Acme" })).toBeInTheDocument();
    expect(screen.queryByText(/Informe de Globex/)).toBeNull();
  });
});
