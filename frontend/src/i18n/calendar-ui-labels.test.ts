import { describe, expect, it } from "vitest";
import { calendarUiLabels, fillLabel, type CalendarUiLabels } from "./calendar-ui-labels";

const LOCALES = ["en", "en-gb", "es", "pt", "it", "fr", "de"] as const;

const REQUIRED: (keyof CalendarUiLabels)[] = [
  "viewDay", "viewWeek", "viewMonth", "today", "previous", "next",
  "viewSelectorLabel", "navLabel", "timezoneLabel", "filterGroupLabel",
  "providerGoogle", "providerOutlook", "emptyPeriod", "providerDisconnected",
  "providerError", "retry", "incompleteLimit", "incompleteTimeout", "incompleteError",
  "discarded", "noEventId", "detailsTitle", "close", "when", "calendarName",
  "participants", "description", "calendarRegion", "rulesToggleSummary",
];

describe("etiquetas del calendario visual", () => {
  it.each(LOCALES)("%s define todas las claves nuevas con texto", (locale) => {
    const labels = calendarUiLabels(locale);
    for (const key of REQUIRED) {
      expect(labels[key], `${locale}.${key}`).toBeTruthy();
    }
  });

  it("los marcadores {…} de cada texto coinciden en todos los idiomas", () => {
    const marks = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");
    const base = calendarUiLabels("en");
    for (const locale of LOCALES) {
      const l = calendarUiLabels(locale);
      for (const key of REQUIRED) {
        expect(marks(l[key]), `${locale}.${key}`).toBe(marks(base[key]));
      }
    }
  });

  it("fillLabel sustituye marcadores y deja el resto intacto", () => {
    expect(fillLabel("{n} registros de {p}", { n: 3, p: "Google" })).toBe("3 registros de Google");
    expect(fillLabel("sin marcadores", { n: 1 })).toBe("sin marcadores");
  });
});
