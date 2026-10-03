import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import AutomationPage from "./page";

const patch = vi.fn();
const status = vi.fn();
const me = vi.fn();

vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return {
    ...actual,
    getStoredAccessToken: () => "jwt",
    fetchCalendarAutomationStatus: () => status(),
    fetchAuthMe: () => me(),
    patchCalendarAutomationSettings: (b: unknown) => patch(b),
  };
});
vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return {
    useTranslation: () => ({ t, locale: "es", preferences: { locale: "es" }, setLocale: () => {} }),
    usePreferences: () => ({ t, locale: "es", preferences: { locale: "es" }, effectiveTimezone: "UTC", ready: true }),
  };
});
vi.mock("@/components/auth/MutatorGuard", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/components/dashboard/TopBar", () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock("@/components/dashboard/CalendarFormatGuideAnyAction", () => ({ default: () => <button type="button">Guía de formato</button> }));
vi.mock("@/components/dashboard/AutomationCalendarPreview", () => ({
  default: () => <div data-testid="calendario">calendario</div>,
}));

function estado(over: Record<string, unknown> = {}) {
  return {
    enabled: true,
    poll_seconds: 60,
    advance_minutes: 20,
    advance_minutes_stored: 20,
    has_calendars: true,
    skip_internal_meetings: false,
    scheduled_events: 2,
    next_due: null,
    integrations: [{ provider: "google" }],
    ...over,
  };
}

beforeEach(() => {
  patch.mockReset().mockResolvedValue({ message: "Guardado" });
  status.mockReset().mockResolvedValue(estado());
  me.mockReset().mockResolvedValue({ organization_plan: "pro" });
});

describe("/dashboard/automation · distribución", () => {
  it("el calendario ocupa el ancho completo, fuera del bloque de reglas", async () => {
    render(<AutomationPage />);
    const calendario = await screen.findByTestId("calendario");
    const reglas = screen.getByText("Reglas de automatización", { selector: "summary *, summary" }).closest("details")!;
    expect(reglas.contains(calendario)).toBe(false);
    expect(calendario.closest(".xl\\:col-span-2")).toBeNull();
    expect(calendario.closest(".xl\\:grid-cols-3")).toBeNull();
  });

  it("las reglas están en un bloque plegable cerrado por defecto", async () => {
    render(<AutomationPage />);
    await screen.findByTestId("calendario");
    const reglas = screen.getByText("Reglas de automatización", { selector: "summary *, summary" }).closest("details")!;
    expect(reglas.tagName).toBe("DETAILS");
    expect(reglas).not.toHaveAttribute("open");
  });

  it("la guía de formato sigue accesible en la cabecera del calendario", async () => {
    render(<AutomationPage />);
    await screen.findByTestId("calendario");
    expect(screen.getByRole("button", { name: "Guía de formato" })).toBeInTheDocument();
  });
});

describe("/dashboard/automation · reglas conservadas", () => {
  async function abrirReglas() {
    const user = userEvent.setup();
    const resumen = (await screen.findAllByText("Reglas de automatización"))[0];
    await user.click(resumen);
    return user;
  }

  it("cambiar la antelación guarda con el mismo contrato", async () => {
    render(<AutomationPage />);
    const user = await abrirReglas();
    await waitFor(() => expect(screen.getByRole("combobox")).toBeEnabled());
    await user.selectOptions(screen.getByRole("combobox"), "30");
    expect(patch).toHaveBeenCalledWith({ advance_minutes: 30 });
  });

  it("el filtro de reuniones internas sigue funcionando", async () => {
    render(<AutomationPage />);
    const user = await abrirReglas();
    const check = await screen.findByRole("checkbox");
    await waitFor(() => expect(check).toBeEnabled());
    await user.click(check);
    expect(patch).toHaveBeenCalledWith({ skip_internal_meetings: true });
  });

  it("el plan gratuito conserva la restricción: aviso y controles deshabilitados", async () => {
    me.mockResolvedValue({ organization_plan: "free" });
    render(<AutomationPage />);
    await abrirReglas();
    expect(await screen.findByText(createTranslator("es")("billing.automation_requires_pro"))).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });

  it("muestra el estado de la cola dentro del bloque de reglas", async () => {
    render(<AutomationPage />);
    await abrirReglas();
    const bloque = (await screen.findAllByText("Reglas de automatización"))[0].closest("details")!;
    await waitFor(() => expect(within(bloque).getByText(/Reuniones en cola: 2/)).toBeInTheDocument());
  });
});
