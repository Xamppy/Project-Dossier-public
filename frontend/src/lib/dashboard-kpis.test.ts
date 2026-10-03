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
  history: { state: "ok", reason: null, measured_from: "2026-09-03T15:00:00Z", measured_to: "2026-10-03T15:00:00Z",
    from: "2026-09-03T15:00:00Z", to: "2026-10-03T15:00:00Z", eligible_meetings: 8,
    manually_prepared_on_time_meetings: 6, on_time_percent: 75, manual_on_time_dossiers: 11 },
  credits: { state: "ok", reason: null, measured_from: null, measured_to: null, balance: 42, monthly_limit: 500 },
  ...o,
});

const t = createTranslator("es");
const entrada = (summary: DashboardSummary | null, status: "loading" | "ready" | "error" = "ready", extra = {}) =>
  buildKpiCards({ summary, status, t, locale: "es", formatDate: (iso) => iso.slice(0, 10), ...extra });
const tarjeta = (cards: ReturnType<typeof buildKpiCards>, id: string) => cards.find((c) => c.id === id)!;

describe("buildKpiCards · valores reales", () => {
  it("CA1: 5 futuras y 3 preparadas muestran 2 pendientes y 60 %", () => {
    const cards = entrada(base());
    expect(cards.map((c) => c.id)).toEqual(["pending", "coverage", "on_time", "credits"]);
    expect(tarjeta(cards, "pending").value).toBe("2");
    expect(tarjeta(cards, "coverage").value).toMatch(/^60\s?%$/);
    expect(tarjeta(cards, "pending").trendVariant).toBe("warning");
  });

  it("CA2: 75 %, 6 de 8 reuniones y 11 dossiers, con el periodo móvil rotulado", () => {
    const c = tarjeta(entrada(base()), "on_time");
    expect(c.value).toMatch(/^75\s?%$/);
    const texto = (c.details ?? []).join(" | ");
    expect(texto).toContain("6 de 8");
    expect(texto).toContain("11");
    expect(texto).toMatch(/30 días/);
    expect(texto).not.toMatch(/mes/i); // «Últimos 30 días», no «Este mes»
  });

  it("la tarjeta de puntualidad explica la diferencia entre reuniones y dossiers en su texto accesible", () => {
    const c = tarjeta(entrada(base()), "on_time");
    expect(c.description).toMatch(/finalización|terminaron|generaste/i);
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

  it("un cero real con denominador positivo se muestra como 0 %", () => {
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
    const cards = entrada(null, "loading");
    for (const c of cards) {
      expect(c.value).toBe("—");
      expect(c.busy).toBe(true);
    }
  });

  it("error de consulta: guion con mensaje, nunca ceros", () => {
    const cards = entrada(null, "error");
    for (const c of cards) {
      expect(c.value).toBe("—");
      expect(c.busy).toBeFalsy();
      expect(c.details?.[0]).toMatch(/no se pudieron? /i);
    }
  });

  it("error de consulta con saldo conocido conserva los créditos reales", () => {
    const cards = entrada(null, "error", { fallbackCredits: { balance: 7, limit: 10 } });
    expect(tarjeta(cards, "credits").value).toBe("7");
    expect(tarjeta(cards, "coverage").value).toBe("—");
  });

  it("sin calendario conectado: no afirma cero reuniones", () => {
    const na = { state: "not_connected" as const, reason: "no_calendar_connected", measured_from: null, measured_to: null };
    const s = base({
      upcoming: { ...base().upcoming, ...na, eligible_meetings: null, prepared_meetings: null, pending_meetings: null, coverage_percent: null },
      history: { ...base().history, ...na, eligible_meetings: null, manually_prepared_on_time_meetings: null, on_time_percent: null, manual_on_time_dossiers: null },
    });
    const cards = entrada(s);
    expect(tarjeta(cards, "pending").value).toBe("—");
    expect(tarjeta(cards, "pending").details?.[0]).toMatch(/calendario/i);
    expect(tarjeta(cards, "credits").value).toBe("42"); // el saldo sigue visible
  });

  it("sin reuniones en el periodo: «Sin reuniones», porcentaje vacío y pendientes en 0", () => {
    const s = base();
    s.upcoming = { ...s.upcoming, state: "empty", reason: "no_meetings_in_period", eligible_meetings: 0,
      prepared_meetings: 0, pending_meetings: 0, coverage_percent: null };
    const cards = entrada(s);
    expect(tarjeta(cards, "pending").value).toBe("0");
    expect(tarjeta(cards, "coverage").value).toBe("—");
    expect(tarjeta(cards, "coverage").details?.[0]).toBe("Sin reuniones en este período");
  });

  it.each([
    ["calendar_reauth_required", /vuelve a conectar/i],
    ["calendar_incomplete", /incompleta/i],
    ["calendar_unavailable", /no se pudo/i],
    ["calendar_busy", /ocupad|reintent/i],
  ])("calendario no disponible (%s) deja los derivados en guion con la causa", (reason, patron) => {
    const un = { state: "unavailable" as const, reason, measured_from: null, measured_to: null };
    const s = base({
      upcoming: { ...base().upcoming, ...un, eligible_meetings: null, prepared_meetings: null, pending_meetings: null, coverage_percent: null },
    });
    const c = tarjeta(entrada(s), "coverage");
    expect(c.value).toBe("—");
    expect(c.details?.[0]).toMatch(patron);
  });

  it("historial parcial: muestra el intervalo realmente medido y no lo presenta como 30 días", () => {
    const s = base();
    s.history = { ...s.history, state: "partial", reason: "history_partial_evidence", measured_from: "2026-09-28T15:00:00Z" };
    const c = tarjeta(entrada(s), "on_time");
    const texto = (c.details ?? []).join(" | ");
    expect(texto).toMatch(/historial parcial/i);
    expect(texto).toContain("2026-09-28");
    expect(c.value).toMatch(/^75\s?%$/); // el porcentaje es de lo medido, declarado como parcial
  });

  it("sin evidencia disponible: guion con causa y los otros indicadores no se afectan", () => {
    const s = base();
    s.history = { ...s.history, state: "unavailable", reason: "evidence_unavailable", eligible_meetings: null,
      manually_prepared_on_time_meetings: null, on_time_percent: null, manual_on_time_dossiers: null };
    const cards = entrada(s);
    expect(tarjeta(cards, "on_time").value).toBe("—");
    expect(tarjeta(cards, "coverage").value).toMatch(/60/);
  });
});

describe("buildKpiCards · idiomas", () => {
  it.each(["es", "en", "en-gb", "pt", "it", "fr", "de"] as const)("%s: cuatro tarjetas con rótulos distintos y sin claves sin traducir", (locale) => {
    const cards = buildKpiCards({ summary: base(), status: "ready", t: createTranslator(locale), locale, formatDate: (i) => i });
    const textos = cards.flatMap((c) => [c.label, ...(c.details ?? []), c.description ?? ""]);
    expect(new Set(cards.map((c) => c.label)).size).toBe(4);
    for (const x of textos) {
      expect(x).not.toMatch(/^stat\./);
      expect(x).not.toMatch(/\{[a-z_]+\}/); // sin marcadores sin sustituir
    }
  });
});
