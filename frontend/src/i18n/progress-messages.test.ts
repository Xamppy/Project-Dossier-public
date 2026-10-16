import { describe, expect, it } from "vitest";
import { createTranslator } from "@/i18n";
import de from "@/i18n/messages/de";
import en from "@/i18n/messages/en";
import es from "@/i18n/messages/es";
import fr from "@/i18n/messages/fr";
import it_ from "@/i18n/messages/it";
import pt from "@/i18n/messages/pt";
import type { Locale, TranslationKey } from "@/i18n/types";

// CA11/CA24 (S5.4): los textos del progreso existen en los siete idiomas del
// dashboard. en-gb hereda de en (no hay variante ortográfica que cambiar).

const OWN: Record<string, Record<string, string>> = { es, pt, it: it_, fr, de };
const S54_KEYS = (Object.keys(en) as TranslationKey[]).filter(
  (k) => k.startsWith("progress.") || k === "person_research.eta_estimate",
);
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("i18n · textos de S5.4", () => {
  it("hay un catálogo completo de textos de progreso en inglés", () => {
    expect(S54_KEYS.length).toBeGreaterThanOrEqual(80);
  });

  it.each(Object.keys(OWN))("%s traduce cada texto con los mismos marcadores", (locale) => {
    const messages = OWN[locale];
    for (const key of S54_KEYS) {
      const text = messages[key];
      expect(text, `${locale} · ${key}`).toBeTruthy();
      expect(placeholders(text), `${locale} · ${key}`).toEqual(placeholders((en as Record<string, string>)[key]));
    }
  });

  it.each(["es", "en", "en-gb", "pt", "it", "fr", "de"] as Locale[])(
    "%s nunca muestra la clave en lugar del texto",
    (locale) => {
      const t = createTranslator(locale);
      for (const key of S54_KEYS) expect(t(key)).not.toBe(key);
    },
  );

  it("en-gb hereda de en", () => {
    const gb = createTranslator("en-gb");
    const us = createTranslator("en");
    for (const key of S54_KEYS) expect(gb(key)).toBe(us(key));
  });

  it.each(Object.keys(OWN))("%s ya no promete búsqueda en internet en «Web pública»", (locale) => {
    const t = createTranslator(locale as Locale);
    expect(t("person_research.source_gemini_hint")).toBe(t("progress.no_live_web_search"));
  });
});
