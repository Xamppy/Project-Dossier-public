import type { Locale, TranslationKey } from "@/i18n/types";

/** Valor interno del selector cuando se sigue la zona del dispositivo. */
export const SYSTEM_TIMEZONE_VALUE = "__system__";

const LOCALE_MAP: Record<Locale, string> = {
  en: "en-US",
  "en-gb": "en-GB",
  es: "es-ES",
  pt: "pt-PT",
  it: "it-IT",
  fr: "fr-FR",
  de: "de-DE",
};

/** Zonas generales (una por franja horaria / región, sin listado IANA completo). */
export const GENERAL_TIMEZONE_OPTIONS: { value: string; labelKey: TranslationKey }[] = [
  { value: "UTC", labelKey: "timezone.utc" },
  { value: "Pacific/Honolulu", labelKey: "timezone.pacific" },
  { value: "America/Los_Angeles", labelKey: "timezone.us_west" },
  { value: "America/Denver", labelKey: "timezone.us_mountain" },
  { value: "America/Chicago", labelKey: "timezone.us_central" },
  { value: "America/New_York", labelKey: "timezone.us_east" },
  { value: "America/Mexico_City", labelKey: "timezone.mexico" },
  { value: "America/Bogota", labelKey: "timezone.colombia_peru" },
  { value: "America/Santiago", labelKey: "timezone.chile" },
  { value: "America/Sao_Paulo", labelKey: "timezone.brazil" },
  { value: "Europe/London", labelKey: "timezone.uk" },
  { value: "Europe/Madrid", labelKey: "timezone.spain" },
  { value: "Europe/Paris", labelKey: "timezone.central_europe" },
  { value: "Asia/Dubai", labelKey: "timezone.gulf" },
  { value: "Asia/Kolkata", labelKey: "timezone.india" },
  { value: "Asia/Singapore", labelKey: "timezone.southeast_asia" },
  { value: "Asia/Tokyo", labelKey: "timezone.japan_korea" },
  { value: "Australia/Sydney", labelKey: "timezone.australia" },
];

const GENERAL_VALUES = new Set(GENERAL_TIMEZONE_OPTIONS.map((o) => o.value));

function intlLocale(locale: Locale): string {
  return LOCALE_MAP[locale] ?? "en-US";
}

/** Offset corto UTC para la etiqueta (ej. GMT-4). */
export function formatTimezoneOffset(timeZone: string, locale: Locale): string {
  const bcp47 = intlLocale(locale);
  try {
    return (
      new Intl.DateTimeFormat(bcp47, {
        timeZone,
        timeZoneName: "shortOffset",
      })
        .formatToParts(new Date())
        .find((p) => p.type === "timeZoneName")?.value ?? ""
    );
  } catch {
    return "";
  }
}

export function formatGeneralTimezoneLabel(
  timeZone: string,
  locale: Locale,
  label: string,
): string {
  const offset = formatTimezoneOffset(timeZone, locale);
  return offset ? `${label} (${offset})` : label;
}

export function getGeneralTimezoneOptions(include?: string[]): {
  value: string;
  labelKey: TranslationKey | null;
}[] {
  const extras = (include ?? []).filter((tz) => tz && !GENERAL_VALUES.has(tz));
  return [
    ...GENERAL_TIMEZONE_OPTIONS,
    ...extras.map((value) => ({ value, labelKey: null as TranslationKey | null })),
  ];
}

function getOffsetMinutes(timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "longOffset",
  }).formatToParts(new Date());
  const raw = parts.find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  const m = raw.match(/GMT([+-])(\d{1,2})(?::(\d{2}))?/i);
  if (!m) return 0;
  const sign = m[1] === "-" ? -1 : 1;
  const hours = Number(m[2]);
  const mins = m[3] ? Number(m[3]) : 0;
  return sign * (hours * 60 + mins);
}

/** Si la zona guardada no está en la lista, usar la más cercana por offset. */
export function normalizeToGeneralTimezone(timeZone: string): string {
  const tz = timeZone?.trim();
  if (!tz || GENERAL_VALUES.has(tz)) return tz || "UTC";

  let targetOffset = 0;
  try {
    targetOffset = getOffsetMinutes(tz);
  } catch {
    return "UTC";
  }

  let best = "UTC";
  let bestDiff = Infinity;
  for (const candidate of GENERAL_TIMEZONE_OPTIONS) {
    const diff = Math.abs(getOffsetMinutes(candidate.value) - targetOffset);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = candidate.value;
    }
  }
  return best;
}

/** Zona IANA detectada en el navegador (ajuste del SO). */
export function getBrowserTimezone(): string {
  if (typeof Intl === "undefined") return "UTC";
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone?.trim();
    if (tz) return tz;
  } catch {
    /* ignore */
  }
  return "UTC";
}

export function getEffectiveTimezone(
  timezone: string,
  followSystem: boolean,
): string {
  if (followSystem) return getBrowserTimezone();
  return timezone?.trim() || getBrowserTimezone();
}

/** Etiqueta corta para la opción automática. */
export function formatBrowserTimezoneHint(locale: Locale): string {
  const tz = getBrowserTimezone();
  const offset = formatTimezoneOffset(tz, locale);
  const region = tz.replace(/_/g, " ").split("/").pop() ?? tz;
  return offset ? `${region} · ${offset}` : region;
}
