import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import { adaptMeetings } from "@/lib/calendar-events";
import { findJobForEvent, isEventJobActive } from "@/lib/calendar-jobs";
import { DossierApiError } from "@/lib/dossier-api";
import CalendarEventDetails from "./CalendarEventDetails";

const TZ = "America/Santiago";
const enqueueCalendarJob = vi.fn();
const state: { jobs: Record<string, unknown>[] } = { jobs: [] };

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  const prefs = { locale: "es", timezone: "America/Santiago", timezoneFollowSystem: false };
  return {
    usePreferences: () => ({ preferences: prefs, effectiveTimezone: "America/Santiago", t, locale: "es" }),
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

function evento(over: Record<string, unknown> = {}, provider: "google" | "microsoft" = "google") {
  return adaptMeetings(
    provider,
    [
      {
        id: "ev1",
        tema: "Reunión con Acme",
        descripcion: "Empresa: Acme\nContacto: Ana Pérez",
        participantes: "ana@acme.test (organizador)",
        ubicacion: "Sala 3",
        inicio: "2026-10-06T13:00:00Z",
        fin: "2026-10-06T14:00:00Z",
        ...over,
      },
    ],
    TZ,
    "Sin asunto",
  ).events[0];
}

function setup(e = evento(), trigger?: HTMLElement) {
  const onClose = vi.fn();
  const utils = render(<CalendarEventDetails event={e} onClose={onClose} returnFocusTo={trigger ?? null} />);
  return { onClose, ...utils };
}

beforeEach(() => {
  enqueueCalendarJob.mockReset();
  enqueueCalendarJob.mockResolvedValue("job-1");
  state.jobs = [];
});

describe("CalendarEventDetails · contenido", () => {
  it("muestra título, fecha en la zona del usuario, proveedor, participantes, ubicación y descripción", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Reunión con Acme" })).toBeInTheDocument();
    expect(screen.getByText(/10:00/)).toBeInTheDocument(); // 13:00Z en Santiago (UTC-3)
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.getByText(/ana@acme\.test/)).toBeInTheDocument();
    expect(screen.getByText("Sala 3")).toBeInTheDocument();
    expect(screen.getByText(/Contacto: Ana Pérez/)).toBeInTheDocument();
  });

  it("la descripción se presenta como texto, nunca como marcado (CA8)", () => {
    const { container } = setup(evento({ descripcion: "<b>negrita</b><img src=x onerror=alert(1)>" }));
    expect(container.querySelector("b, img")).toBeNull();
    expect(screen.getByText(/negrita/)).toBeInTheDocument();
  });

  it("evento de día completo muestra la etiqueta y no una hora", () => {
    setup(evento({ inicio: "2026-10-12", fin: "2026-10-13", todo_el_dia: true }));
    expect(screen.getByText(/Todo el día/)).toBeInTheDocument();
  });

  it("sin hora de fin válida no se inventa una (CA8)", () => {
    setup(evento({ fin: "" }));
    expect(screen.getByText(/10:00/)).toBeInTheDocument();
    expect(screen.queryByText(/10:00\s*[–-]\s*\d/)).toBeNull();
  });

  it("descripción vacía avisa de cómo completarla", () => {
    setup(evento({ descripcion: "" }));
    expect(screen.getByText(createTranslator("es")("overview.calendar_description_empty"))).toBeInTheDocument();
  });
});

describe("CalendarEventDetails · generación (CA7)", () => {
  it("abrir la reunión no genera ni cobra nada", () => {
    setup();
    expect(enqueueCalendarJob).not.toHaveBeenCalled();
  });

  it("generar envía proveedor, id original y la fila original", async () => {
    const user = userEvent.setup();
    const e = evento();
    setup(e);
    await user.click(screen.getByRole("button", { name: /generar dossier/i }));
    expect(enqueueCalendarJob).toHaveBeenCalledTimes(1);
    expect(enqueueCalendarJob).toHaveBeenCalledWith("google", { eventId: "ev1", reunion: e.raw });
  });

  it("un doble clic rápido solo encola una vez", async () => {
    const user = userEvent.setup();
    let liberar!: () => void;
    enqueueCalendarJob.mockImplementation(() => new Promise<string>((res) => (liberar = () => res("job-1"))));
    setup();
    const boton = screen.getByRole("button", { name: /generar dossier/i });
    await user.dblClick(boton);
    expect(enqueueCalendarJob).toHaveBeenCalledTimes(1);
    await act(async () => liberar());
  });

  it("mientras el job está activo el botón queda deshabilitado con el texto de progreso", () => {
    state.jobs = [{ id: "j", status: "running", job_type: "calendar_manual", calendar_provider: "google", external_event_id: "ev1" }];
    setup();
    expect(screen.getByRole("button", { name: /generando/i })).toBeDisabled();
  });

  it("el mismo id en el otro proveedor no bloquea este evento", () => {
    state.jobs = [{ id: "j", status: "running", job_type: "calendar_manual", calendar_provider: "microsoft", external_event_id: "ev1" }];
    setup(evento({}, "google"));
    expect(screen.getByRole("button", { name: /generar dossier/i })).toBeEnabled();
  });

  it("evento sin id: visible, con aviso y sin posibilidad de generar", () => {
    setup(evento({ id: null }));
    expect(screen.getByRole("button", { name: /generar dossier/i })).toBeDisabled();
    expect(screen.getByText(/no tiene identificador/i)).toBeInTheDocument();
  });

  it("errores de créditos o plan se muestran y permiten reintentar", async () => {
    const user = userEvent.setup();
    enqueueCalendarJob.mockRejectedValue(new DossierApiError(402, "Créditos insuficientes para generar"));
    setup();
    await user.click(screen.getByRole("button", { name: /generar dossier/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Créditos insuficientes para generar");
    expect(screen.getByRole("button", { name: /generar dossier/i })).toBeEnabled();
  });

  it("muestra el resultado solo si corresponde a esta reunión", () => {
    state.jobs = [
      {
        id: "j1", status: "completed", job_type: "calendar_manual", calendar_provider: "google", external_event_id: "ev1",
        result: { reunion: {}, dossier_generado: "x", dossier_corporativo: "# Informe corporativo de Acme", dossier_persona: null },
      },
      {
        id: "j2", status: "completed", job_type: "calendar_manual", calendar_provider: "google", external_event_id: "otro",
        result: { reunion: {}, dossier_generado: "x", dossier_corporativo: "# Informe de OTRA reunión", dossier_persona: null },
      },
      {
        id: "j3", status: "completed", job_type: "calendar_manual", calendar_provider: "microsoft", external_event_id: "ev1",
        result: { reunion: {}, dossier_generado: "x", dossier_corporativo: "# Informe del otro proveedor", dossier_persona: null },
      },
    ];
    setup();
    expect(screen.getByText(/Informe corporativo de Acme/)).toBeInTheDocument();
    expect(screen.queryByText(/OTRA reunión/)).toBeNull();
    expect(screen.queryByText(/otro proveedor/)).toBeNull();
  });

  it("un job fallido muestra su mensaje", () => {
    state.jobs = [{ id: "j", status: "failed", job_type: "calendar_manual", calendar_provider: "google", external_event_id: "ev1", error_message: "El proveedor de datos no respondió" }];
    setup();
    expect(screen.getByRole("alert")).toHaveTextContent("El proveedor de datos no respondió");
  });
});

describe("CalendarEventDetails · diálogo accesible (CA11)", () => {
  it("es un diálogo modal con nombre y recibe el foco", async () => {
    setup();
    const dialog = screen.getByRole("dialog", { name: "Reunión con Acme" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  });

  it("Escape lo cierra", async () => {
    const user = userEvent.setup();
    const { onClose } = setup();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("el botón Cerrar tiene nombre accesible", async () => {
    const user = userEvent.setup();
    const { onClose } = setup();
    await user.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("Tab no sale del diálogo", async () => {
    const user = userEvent.setup();
    setup();
    const dialog = screen.getByRole("dialog");
    for (let i = 0; i < 8; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    for (let i = 0; i < 8; i++) {
      await user.tab({ shift: true });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it("al cerrar devuelve el foco al elemento que lo abrió", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    const { unmount } = setup(evento(), trigger);
    unmount();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it("si el elemento ya no existe, el foco no se pierde en el vacío", () => {
    const trigger = document.createElement("button");
    const fallback = document.createElement("div");
    fallback.tabIndex = -1;
    document.body.appendChild(fallback);
    const onClose = vi.fn();
    const { unmount } = render(
      <CalendarEventDetails event={evento()} onClose={onClose} returnFocusTo={trigger} fallbackFocus={() => fallback} />,
    );
    unmount();
    expect(document.activeElement).toBe(fallback);
    fallback.remove();
  });
});
