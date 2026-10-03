import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { adaptMeetings } from "@/lib/calendar-events";
import { calendarUiLabels } from "@/i18n/calendar-ui-labels";
import MeetingsCalendar from "./MeetingsCalendar";

const TZ = "America/Santiago";

function eventos() {
  return [
    ...adaptMeetings(
      "google",
      [{ id: "g1", tema: "Reunión Acme", inicio: "2026-10-06T13:00:00Z", fin: "2026-10-06T14:00:00Z" }],
      TZ,
      "x",
    ).events,
    ...adaptMeetings(
      "microsoft",
      [
        { id: "m1", tema: "Revisión Globex", inicio: "2026-10-06T15:00:00Z", fin: "2026-10-06T16:00:00Z" },
        { id: "d1", tema: "Feriado", inicio: "2026-10-08", fin: "2026-10-09", todo_el_dia: true },
      ],
      TZ,
      "x",
    ).events,
  ];
}

function setup(over: Partial<React.ComponentProps<typeof MeetingsCalendar>> = {}) {
  const onRangeChange = vi.fn();
  const onSelectEvent = vi.fn();
  const utils = render(
    <MeetingsCalendar
      events={eventos()}
      locale="es"
      timezone={TZ}
      labels={calendarUiLabels("es")}
      initialView="timeGridWeek"
      onRangeChange={onRangeChange}
      onSelectEvent={onSelectEvent}
      {...over}
    />,
  );
  return { onRangeChange, onSelectEvent, ...utils };
}

const ultima = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls[fn.mock.calls.length - 1][0];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-07T15:00:00Z")); // miércoles
});
afterEach(() => vi.useRealTimers());

describe("MeetingsCalendar · navegación y ventana consultada (CA1)", () => {
  it("la vista inicial Semana informa la ventana de la semana visible en la zona del usuario", async () => {
    const { onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());
    expect(ultima(onRangeChange)).toMatchObject({
      view: "timeGridWeek",
      window: { desde: "2026-10-05T00:00:00-03:00", hasta: "2026-10-12T00:00:00-03:00" },
    });
  });

  it("Siguiente, Anterior y Hoy piden la ventana correcta", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(ultima(onRangeChange).window.desde).toBe("2026-10-12T00:00:00-03:00");
    await user.click(screen.getByRole("button", { name: "Anterior" }));
    await user.click(screen.getByRole("button", { name: "Anterior" }));
    expect(ultima(onRangeChange).window.desde).toBe("2026-09-28T00:00:00-03:00");
    await user.click(screen.getByRole("button", { name: "Hoy" }));
    expect(ultima(onRangeChange).window.desde).toBe("2026-10-05T00:00:00-03:00");
  });

  it("cambiar a Día y a Mes solicita el intervalo de esa vista, incluidos los días de meses contiguos", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Día" }));
    expect(ultima(onRangeChange)).toMatchObject({
      view: "timeGridDay",
      window: { desde: "2026-10-07T00:00:00-03:00", hasta: "2026-10-08T00:00:00-03:00" },
    });

    await user.click(screen.getByRole("button", { name: "Mes" }));
    const m = ultima(onRangeChange);
    expect(m.view).toBe("dayGridMonth");
    expect(m.window.desde).toBe("2026-09-28T00:00:00-03:00"); // lunes anterior al 1 de octubre
    const dias = (Date.parse(m.window.hasta) - Date.parse(m.window.desde)) / 86_400_000;
    expect(dias % 7).toBeCloseTo(0, 1);
    expect(dias).toBeLessThanOrEqual(62);
    expect(Date.parse(m.window.hasta)).toBeGreaterThan(Date.parse("2026-11-01T00:00:00-03:00"));
  });

  it("el cambio de horario dentro de la ventana usa el offset correcto en cada extremo", async () => {
    vi.setSystemTime(new Date("2026-09-03T15:00:00Z")); // semana del 31/08 al 07/09: cruza el cambio de Santiago
    const { onRangeChange } = setup({ initialView: "dayGridMonth" });
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());
    const w = ultima(onRangeChange).window;
    expect(w.desde).toBe("2026-08-31T00:00:00-04:00");
    expect(w.hasta.endsWith("-03:00")).toBe(true);
  });

  it("al cambiar la zona horaria se vuelve a informar la ventana con el nuevo offset", async () => {
    const { onRangeChange, rerender } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());
    expect(ultima(onRangeChange).window.desde).toBe("2026-10-05T00:00:00-03:00");

    rerender(
      <MeetingsCalendar
        events={eventos()}
        locale="es"
        timezone="Europe/London"
        labels={calendarUiLabels("es")}
        initialView="timeGridWeek"
        onRangeChange={onRangeChange}
        onSelectEvent={vi.fn()}
      />,
    );
    await waitFor(() => expect(ultima(onRangeChange).window.desde).toBe("2026-10-05T00:00:00+01:00"));
  });

  it("el primer día de la semana depende del idioma", async () => {
    const en = setup({ locale: "en", labels: calendarUiLabels("en") });
    await waitFor(() => expect(en.onRangeChange).toHaveBeenCalled());
    expect(ultima(en.onRangeChange).window.desde).toBe("2026-10-04T00:00:00-03:00"); // domingo
  });
});

describe("MeetingsCalendar · controles accesibles (CA11)", () => {
  it("expone selector de vista con estado, navegación agrupada y zona horaria visible", async () => {
    const { onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());

    const vistas = screen.getByRole("group", { name: "Vista del calendario" });
    expect(within(vistas).getByRole("button", { name: "Semana" })).toHaveAttribute("aria-pressed", "true");
    expect(within(vistas).getByRole("button", { name: "Día" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("group", { name: "Navegación del calendario" })).toBeInTheDocument();
    expect(screen.getByText("Zona horaria: America/Santiago")).toBeInTheDocument();
  });

  it("el período visible se anuncia como título en vivo", async () => {
    const { onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());
    const titulo = screen.getByRole("heading", { level: 3 });
    expect(titulo).toHaveAttribute("aria-live", "polite");
    expect(titulo.textContent).toMatch(/octubre/i);
  });
});

describe("MeetingsCalendar · eventos", () => {
  it("pinta título y etiqueta de proveedor (no solo color) y el día completo", async () => {
    const { onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());
    expect(await screen.findByText("Reunión Acme")).toBeInTheDocument();
    expect(screen.getByText("Revisión Globex")).toBeInTheDocument();
    expect(screen.getByText("Feriado")).toBeInTheDocument();
    expect(screen.getAllByText("Google").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Outlook").length).toBeGreaterThan(0);
  });

  it("cada evento lleva la clase de su proveedor en el DOM real (color + etiqueta)", async () => {
    const { onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());
    const g = (await screen.findByText("Reunión Acme")).closest(".dossier-ev");
    const m = screen.getByText("Revisión Globex").closest(".dossier-ev");
    expect(g).toHaveClass("dossier-ev--google");
    expect(m).toHaveClass("dossier-ev--microsoft");
  });

  it("pulsar o activar con teclado un evento informa su clave y el elemento", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onSelectEvent, onRangeChange } = setup();
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());

    await user.click(await screen.findByText("Reunión Acme"));
    expect(onSelectEvent).toHaveBeenLastCalledWith("google:g1", expect.any(HTMLElement));

    const boton = (await screen.findByText("Revisión Globex")).closest('[role="button"]') as HTMLElement;
    expect(boton).toHaveAttribute("tabindex", "0");
    boton.focus();
    await user.keyboard("{Enter}");
    expect(onSelectEvent).toHaveBeenLastCalledWith("microsoft:m1", expect.any(HTMLElement));
  });

  it("sin eventos el calendario sigue navegable", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onRangeChange } = setup({ events: [] });
    await waitFor(() => expect(onRangeChange).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(ultima(onRangeChange).window.desde).toBe("2026-10-12T00:00:00-03:00");
  });
});
