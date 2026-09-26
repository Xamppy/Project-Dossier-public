"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createTranslator, type TranslateFn } from "@/i18n";
import type {
  DateFormat,
  Locale,
  OutputLanguage,
  ThemeChoice,
  TranslationKey,
  UserPreferences,
} from "@/i18n/types";
import { DEFAULT_PREFERENCES, normalizeAppLocale } from "@/i18n/types";
import { applyTheme } from "@/lib/theme";
import {
  authUserToPreferencesPatch,
  preferencesToAuthPatch,
} from "@/lib/auth-preferences-sync";
import { getStoredAccessToken, patchAuthUserPreferences, type AuthUser } from "@/lib/dossier-api";
import { getBrowserTimezone, getEffectiveTimezone } from "@/lib/timezones";

const STORAGE_KEY = "dossier-preferences";

type PreferencesContextValue = {
  preferences: UserPreferences;
  /** Zona horaria efectiva (sistema o manual). */
  effectiveTimezone: string;
  t: TranslateFn;
  locale: Locale;
  setTheme: (theme: ThemeChoice) => void;
  setLocale: (locale: Locale) => void;
  setTimezone: (timezone: string, followSystem?: boolean) => void;
  setDateFormat: (format: DateFormat) => void;
  setOutputLanguage: (lang: OutputLanguage) => void;
  setDossierExpiry: (expiry: string) => void;
  updatePreferences: (patch: Partial<UserPreferences>) => void;
  /** Fusiona preferencias devueltas por ``GET /auth/me`` (una vez por sesión). */
  hydrateFromAuthUser: (me: AuthUser) => void;
};

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

function loadPreferences(): UserPreferences {
  if (typeof window === "undefined") return DEFAULT_PREFERENCES;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const merged = { ...DEFAULT_PREFERENCES, ...JSON.parse(raw) } as UserPreferences;
      merged.locale = normalizeAppLocale(merged.locale);
      if (merged.timezoneFollowSystem === undefined) {
        merged.timezoneFollowSystem = false;
      }
      // Legado: «auto» = español; con UI no española suele confundirse con «match».
      if (merged.outputLanguage === "auto") {
        merged.outputLanguage = merged.locale === "es" ? "es" : "match";
      }
      return merged;
    }
    const legacyTheme = localStorage.getItem("dossier-theme") as ThemeChoice | null;
    if (legacyTheme) {
      return {
        ...DEFAULT_PREFERENCES,
        theme: legacyTheme,
        timezone: getBrowserTimezone(),
        timezoneFollowSystem: true,
      };
    }
  } catch {
    /* ignore */
  }
  return {
    ...DEFAULT_PREFERENCES,
    timezone: getBrowserTimezone(),
    timezoneFollowSystem: true,
  };
}

function savePreferences(prefs: UserPreferences) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  localStorage.setItem("dossier-theme", prefs.theme);
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [ready, setReady] = useState(false);
  const serverHydratedRef = useRef(false);
  const lastPushedRef = useRef("");

  useEffect(() => {
    const loaded = loadPreferences();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hidrata desde localStorage (sistema externo) una sola vez al montar.
    setPreferences(loaded);
    applyTheme(loaded.theme);
    document.documentElement.lang = loaded.locale;
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    savePreferences(preferences);
    applyTheme(preferences.theme);
    document.documentElement.lang = preferences.locale;
  }, [preferences, ready]);

  useEffect(() => {
    if (!ready || preferences.theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const handler = () => applyTheme("system");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [preferences.theme, ready]);

  const updatePreferences = useCallback((patch: Partial<UserPreferences>) => {
    setPreferences((prev) => ({ ...prev, ...patch }));
  }, []);

  const hydrateFromAuthUser = useCallback((me: AuthUser) => {
    if (serverHydratedRef.current) return;
    const serverPatch = authUserToPreferencesPatch(me);
    const serverLocale = normalizeAppLocale(me.locale);
    const serverOut = (me.dossier_output_language || "match").trim();
    const serverTimezone = (me.timezone || "UTC").trim();
    const serverExpiry =
      me.dossier_retention_days === null || me.dossier_retention_days === undefined
        ? "never"
        : String(me.dossier_retention_days);
    const serverIsDefault =
      serverLocale === "es" &&
      serverOut === "match" &&
      (serverExpiry === "30" || serverExpiry === "never");

    setPreferences((prev) => {
      const localLocale = normalizeAppLocale(prev.locale);
      const localDiffersFromServerDefaults =
        localLocale !== "es" || prev.outputLanguage !== "match";
      const keepLocalLocale =
        localLocale !== "es" && serverLocale === "es";
      const next =
        serverIsDefault && localDiffersFromServerDefaults
          ? { ...prev, locale: localLocale }
          : keepLocalLocale
            ? { ...prev, ...serverPatch, locale: localLocale }
            : { ...prev, ...serverPatch, locale: normalizeAppLocale(serverPatch.locale ?? prev.locale) };
      // Clave del servidor: si local ≠ servidor, el efecto de sync hará PATCH.
      lastPushedRef.current = JSON.stringify({
        locale: serverLocale,
        timezone: serverTimezone,
        dossier_output_language: serverOut,
        dossier_retention_days:
          serverExpiry === "never" ? null : Number(serverExpiry),
      });
      return next;
    });
    serverHydratedRef.current = true;
  }, []);

  useEffect(() => {
    if (!ready || !serverHydratedRef.current) return;
    const token = getStoredAccessToken();
    if (!token) return;

    const payload = preferencesToAuthPatch(preferences);
    const key = JSON.stringify(payload);
    if (key === lastPushedRef.current) return;

    const timer = window.setTimeout(() => {
      void patchAuthUserPreferences(payload)
        .then(() => {
          lastPushedRef.current = key;
        })
        .catch(() => {
          /* sin sesión o red: se reintenta en el próximo cambio */
        });
    }, 400);

    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberado: solo estos campos viajan al backend via preferencesToAuthPatch(); listar el objeto `preferences` completo dispararia el debounce en cada cambio de UI que no le importa al servidor (p. ej. tema, que se maneja aparte).
  }, [
    preferences.locale,
    preferences.timezone,
    preferences.timezoneFollowSystem,
    preferences.outputLanguage,
    preferences.dossierExpiry,
    ready,
  ]);

  const effectiveTimezone = useMemo(
    () =>
      getEffectiveTimezone(
        preferences.timezone,
        preferences.timezoneFollowSystem ?? false,
      ),
    [preferences.timezone, preferences.timezoneFollowSystem],
  );

  const t = useMemo(
    () => createTranslator(preferences.locale),
    [preferences.locale]
  );

  const value = useMemo<PreferencesContextValue>(
    () => ({
      preferences,
      effectiveTimezone,
      t,
      locale: preferences.locale,
      setTheme: (theme) => updatePreferences({ theme }),
      setLocale: (locale) => updatePreferences({ locale: normalizeAppLocale(locale) }),
      setTimezone: (timezone, followSystem) =>
        updatePreferences({
          timezone,
          ...(followSystem !== undefined ? { timezoneFollowSystem: followSystem } : {}),
        }),
      setDateFormat: (dateFormat) => updatePreferences({ dateFormat }),
      setOutputLanguage: (outputLanguage) =>
        updatePreferences({ outputLanguage }),
      setDossierExpiry: (dossierExpiry) => updatePreferences({ dossierExpiry }),
      updatePreferences,
      hydrateFromAuthUser,
    }),
    [preferences, effectiveTimezone, t, updatePreferences, hydrateFromAuthUser]
  );

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences() {
  const ctx = useContext(PreferencesContext);
  if (!ctx) {
    throw new Error("usePreferences must be used within PreferencesProvider");
  }
  return ctx;
}

export function useTranslation() {
  const { t, locale, preferences, setLocale } = usePreferences();
  return { t, locale, preferences, setLocale };
}

export type { TranslationKey };
