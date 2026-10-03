import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import type { DashboardSummary } from "@/lib/dossier-api";
import OverviewKpiCards from "./OverviewKpiCards";

const t = createTranslator("es");
const prefs = { locale: "es", timezone: "UTC", timezoneFollowSystem: false, dateFormat: "dd/mm/yyyy" };
vi.mock("@/providers/PreferencesProvider", () => ({
  useTranslation: () => ({ t, locale: "es", preferences: prefs, setLocale: () => {} }),
}));

const ctx = { state: "ok" as const, reason: null, measured_from: null, measured_to: null };
const resumen: DashboardSummary = {
  as_of: "2026-10-03T15:00:00Z",
  timezone: "UTC",
  upcoming: { ...ctx, from: "a", to: "b", eligible_meetings: 5, prepared_meetings: 3, pending_meetings: 2, coverage_percent: 60 },
  history: { ...ctx, from: "a", to: "b", eligible_meetings: 8, manually_prepared_on_time_meetings: 6, on_time_percent: 75, manual_on_time_dossiers: 11 },
  credits: { ...ctx, balance: 42, monthly_limit: 500 },
};

describe("OverviewKpiCards", () => {
  it("CA1/CA2: muestra los cuatro indicadores con sus valores reales", () => {
    render(<OverviewKpiCards summary={resumen} status="ready" />);
    const grupos = screen.getAllByRole("group");
    expect(grupos).toHaveLength(4);
    expect(within(grupos[0]).getByText("2")).toBeInTheDocument();
    expect(within(grupos[1]).getByText(/60\s?%/)).toBeInTheDocument();
    expect(within(grupos[2]).getByText(/75\s?%/)).toBeInTheDocument();
    expect(within(grupos[2]).getByText(/Reuniones: 6 de 8/)).toBeInTheDocument();
    expect(within(grupos[2]).getByText(/Dossiers generados por ti a tiempo: 11/)).toBeInTheDocument();
    expect(within(grupos[3]).getByText("42")).toBeInTheDocument();
  });

  it("CA14: distribución de cuatro, dos y una columna y tarjetas solo informativas", () => {
    const { container } = render(<OverviewKpiCards summary={resumen} status="ready" />);
    const rejilla = container.querySelector("section");
    expect(rejilla?.className).toContain("grid-cols-1");
    expect(rejilla?.className).toContain("sm:grid-cols-2");
    expect(rejilla?.className).toContain("lg:grid-cols-4");
    expect(container.querySelectorAll("a, button, [role=button], [tabindex]")).toHaveLength(0);
  });

  it("cargando: cuatro guiones ocupados y sin ceros", () => {
    render(<OverviewKpiCards summary={null} status="loading" />);
    for (const g of screen.getAllByRole("group")) {
      expect(g).toHaveAttribute("aria-busy", "true");
      expect(within(g).getByText("—")).toBeInTheDocument();
    }
  });

  it("error de consulta: avisa en las tarjetas y no muestra ceros", () => {
    render(<OverviewKpiCards summary={null} status="error" />);
    expect(screen.getAllByText(/No se pudieron cargar los indicadores/)).toHaveLength(4);
    expect(screen.queryByText("0")).toBeNull();
  });

  it("el texto accesible de la tarjeta de puntualidad distingue reuniones de dossiers", () => {
    render(<OverviewKpiCards summary={resumen} status="ready" />);
    const g = screen.getByRole("group", { name: "Preparadas a tiempo" });
    const id = g.getAttribute("aria-describedby")!;
    expect(document.getElementById(id)?.textContent).toMatch(/Conteo de dossiers/);
  });
});

describe("Resumen no calcula los indicadores con la lista de dossiers", () => {
  it("page.tsx ya no usa countListEntries ni las tarjetas heredadas", () => {
    const fuente = readFileSync(resolve(process.cwd(), "src/app/dashboard/page.tsx"), "utf8");
    expect(fuente).not.toContain("countListEntries");
    expect(fuente).not.toContain("stat.total_dossiers");
    expect(fuente).toContain("OverviewKpiCards");
  });
});
