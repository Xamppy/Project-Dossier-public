import { describe, expect, it } from "vitest";
import { createTranslator } from "@/i18n";
import { buildKpiCards, formatPercent } from "./dashboard-kpis";
import type { DashboardSummary } from "./dossier-api";

const base = (o: Partial<DashboardSummary> = {}): DashboardSummary => ({
  as_of: "2026-10-03T15:00:00Z",
  timezone: "UTC",
  upcoming: { state: "ok", reason: null, measured_from: "2026-10-03T15:00:00Z", measured_to: "2026-10-10T15:00:00Z",
    from: "2026-10-03T15:00:00Z", to: "2026-10-10T15:00:00Z", eligible_meetings: 5, prepared_meetings: 3,
    pending_meetings: 2, coverage_percent: 60 },
  preparation_cost: { state: "ok", reason: null, measured_from: "2026-10-03T15:00:00Z", measured_to: "2026-10-10T15:00:00Z",
    from: "2026-10-03T15:00:00Z", to: "2026-10-10T15:00:00Z", estimated_credits: 5, meetings_to_generate: 2,
    billing: "charged", exceeds_balance: false },
  credits: { state: "ok", reason: null, measured_from: null, measured_to: null, balance: 42, monthly_limit: 500 },
  ...o,
});

const t = createTranslator("es");
const entrada = (summary: DashboardSummary | null, status: "loading" | "ready" | "error" = "ready", extra = {}) =>
  buildKpiCards({ summary, status, t, locale: "es", ...extra });
const tarjeta = (cards: ReturnType<typeof buildKpiCards>, id: string) => cards.find((c) => c.id === id)!;
const noDisponible = { state: "unavailable" as const, measured_from: null, measured_to: null };

describe("buildKpiCards · valores reales", () => {
  it("CA1: 5 futuras y 3 preparadas muestran 2 pendientes y 60 %", () => {
    const cards = entrada(base());
    expect(cards.map((c) => c.id)).toEqual(["pending", "coverage", "cost", "credits"]);
    expect(tarjeta(cards, "pending").value).toBe("2");
    expect(tarjeta(cards, "coverage").value).toMatch(/^60\s?%$/);
    expect(tarjeta(cards, "pending").trendVariant).toBe("warning");
  });

  it("CA2: créditos para preparar muestra el estimado y cuántas reuniones lo requieren", () => {
    const c = tarjeta(entrada(base()), "cost");
    expect(c.label).toBe("Créditos para preparar");
    expect(c.value).toBe("5");
    expect((c.details ?? []).join(" | ")).toContain("2");
    expect(c.trendVariant).toBe("default");
  });

  it("CA9: si el estimado supera el saldo, la tarjeta lo advierte", () => {
    const s = base();
    s.preparation_cost = { ...s.preparation_cost, estimated_credits: 50, exceeds_balance: true };
    const c = tarjeta(entrada(s), "cost");
    expect(c.trendVariant).toBe("warning");
    expect(c.trend).toMatch(/supera/i); // va en la línea coloreada de advertencia, no entre los detalles
    expect((c.details ?? []).join(" ")).not.toMatch(/supera/i);
  });

  it("el texto accesible explica que es una estimación máxima de lo que falta", () => {
    expect(tarjeta(entrada(base()), "cost").description).toMatch(/estimaci/i);
  });

  it.each([
    ["unlimited", /sin costo/i],
    ["disabled", /desactivado/i],
  ] as const)("CA4: sin cobro (%s) muestra 0 y explica por qué", (billing, patron) => {
    const s = base();
    s.preparation_cost = { ...s.preparation_cost, estimated_credits: 0, billing };
    const c = tarjeta(entrada(s), "cost");
    expect(c.value).toBe("0");
    expect((c.details ?? []).join(" ")).toMatch(patron);
  });

  it("todo preparado: 0 créditos es un cero real", () => {
    const s = base();
    s.preparation_cost = { ...s.preparation_cost, estimated_credits: 0, meetings_to_generate: 0 };
    expect(tarjeta(entrada(s), "cost").value).toBe("0");
  });

  it("créditos: saldo real y referencia al límite del plan", () => {
    const c = tarjeta(entrada(base()), "credits");
    expect(c.value).toBe("42");
    expect(c.details?.join(" ")).toContain("500");
  });

  it("sin límite positivo no se inventa una referencia", () => {
    const s = base({ credits: { state: "ok", reason: null, measured_from: null, measured_to: null, balance: 3, monthly_limit: -1 } });
    expect(tarjeta(entrada(s), "credits").details ?? []).toEqual([]);
  });

  it("un cero real de cobertura con denominador positivo se muestra como 0 %", () => {
    const s = base();
    s.upcoming = { ...s.upcoming, prepared_meetings: 0, pending_meetings: 5, coverage_percent: 0 };
    expect(tarjeta(entrada(s), "coverage").value).toMatch(/^0\s?%$/);
  });

  it("los porcentajes se redondean a un decimal localizado en la presentación", () => {
    expect(formatPercent(100 / 3, "es")).toMatch(/^33,3\s?%$/);
    expect(formatPercent(100 / 3, "en")).toBe("33.3%");
    expect(formatPercent(60, "en-gb")).toBe("60%");
  });
});

describe("buildKpiCards · estados distintos", () => {
  it("cargando: guion, ocupado y sin ceros", () => {
    for (const c of entrada(null, "loading")) {
      expect(c.value).toBe("—");
      expect(c.busy).toBe(true);
    }
  });

  it("error de consulta: guion con mensaje, nunca ceros", () => {
    for (const c of entrada(null, "error")) {
      expect(c.value).toBe("—");
      expect(c.busy).toBeFalsy();
      expect(c.details?.[0]).toMatch(/no se pudieron? /i);
    }
  });

  it("error de consulta con saldo conocido conserva los créditos reales", () => {
    const cards = entrada(null, "error", { fallbackCredits: { balance: 7, limit: 10 } });
    expect(tarjeta(cards, "credits").value).toBe("7");
    expect(tarjeta(cards, "cost").value).toBe("—");
  });

  it("sin calendario conectado: no afirma cero reuniones ni cero créditos por preparar", () => {
    const na = { state: "not_connected" as const, reason: "no_calendar_connected", measured_from: null, measured_to: null };
    const s = base({
      upcoming: { ...base().upcoming, ...na, eligible_meetings: null, prepared_meetings: null, pending_meetings: null, coverage_percent: null },
      preparation_cost: { ...base().preparation_cost, ...na, estimated_credits: null, meetings_to_generate: null, exceeds_balance: null },
    });
    const cards = entrada(s);
    expect(tarjeta(cards, "pending").value).toBe("—");
    expect(tarjeta(cards, "cost").value).toBe("—");
    expect(tarjeta(cards, "cost").details?.[0]).toMatch(/calendario/i);
    expect(tarjeta(cards, "credits").value).toBe("42");
  });

  it("sin reuniones en el periodo: pendientes y créditos en 0, cobertura en guion", () => {
    const s = base();
    const vacio = { state: "empty" as const, reason: "no_meetings_in_period" };
    s.upcoming = { ...s.upcoming, ...vacio, eligible_meetings: 0, prepared_meetings: 0, pending_meetings: 0, coverage_percent: null };
    s.preparation_cost = { ...s.preparation_cost, ...vacio, estimated_credits: 0, meetings_to_generate: 0 };
    const cards = entrada(s);
    expect(tarjeta(cards, "pending").value).toBe("0");
    expect(tarjeta(cards, "coverage").value).toBe("—");
    expect(tarjeta(cards, "coverage").details?.[0]).toBe("Sin reuniones en este período");
    expect(tarjeta(cards, "cost").value).toBe("0");
    expect(tarjeta(cards, "cost").details?.[0]).toBe("Sin reuniones en este período");
  });

  it.each([
    ["calendar_reauth_required", /vuelve a conectar/i],
    ["calendar_incomplete", /incompleta/i],
    ["calendar_unavailable", /no se pudo/i],
    ["calendar_busy", /ocupad|reintent/i],
  ])("calendario no disponible (%s) deja los derivados en guion con la causa", (reason, patron) => {
    const s = base({
      upcoming: { ...base().upcoming, ...noDisponible, reason, eligible_meetings: null, prepared_meetings: null,
        pending_meetings: null, coverage_percent: null },
      preparation_cost: { ...base().preparation_cost, ...noDisponible, reason, estimated_credits: null,
        meetings_to_generate: null, exceeds_balance: null },
    });
    for (const id of ["coverage", "cost"]) {
      const c = tarjeta(entrada(s), id);
      expect(c.value).toBe("—");
      expect(c.details?.[0]).toMatch(patron);
    }
  });
});

describe("buildKpiCards · idiomas", () => {
  it.each(["es", "en", "en-gb", "pt", "it", "fr", "de"] as const)("%s: cuatro tarjetas con rótulos distintos y sin claves sin traducir", (locale) => {
    const s = base();
    s.preparation_cost = { ...s.preparation_cost, exceeds_balance: true };
    const cards = buildKpiCards({ summary: s, status: "ready", t: createTranslator(locale), locale });
    const textos = cards.flatMap((c) => [c.label, ...(c.details ?? []), c.description ?? "", c.trend ?? ""]);
    expect(new Set(cards.map((c) => c.label)).size).toBe(4);
    for (const x of textos) {
      expect(x).not.toMatch(/^stat\./);
      expect(x).not.toMatch(/\{[a-z_]+\}/);
    }
  });
});
