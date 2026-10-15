"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import AuthShell from "@/components/AuthShell";
import FormField from "@/components/FormField";
import PrimaryButton from "@/components/PrimaryButton";
import TimezoneSelect from "@/components/settings/TimezoneSelect";
import {
  authRegister,
  DossierApiError,
  fetchOrgInvitePreview,
  persistAuthToken,
  writeDossierUserPreview,
  type OrgInvitePreview,
} from "@/lib/dossier-api";
import { translateApiErrorMessage } from "@/lib/translate-backend-message";
import { getBrowserTimezone, getEffectiveTimezone } from "@/lib/timezones";
import { useTranslation, usePreferences } from "@/providers/PreferencesProvider";
import type { TranslationKey } from "@/i18n/types";
import type { Locale } from "@/i18n/types";

type AccountKind = "work" | "personal";

type Errors = {
  firstName?: string;
  lastName?: string;
  company?: string;
  orgSlug?: string;
  email?: string;
  password?: string;
  confirmPassword?: string;
  terms?: string;
};

function buildFullName(first: string, last: string): string {
  return `${first.trim()} ${last.trim()}`.trim();
}

/** Alineado con `organizations.slug`: minúsculas, números y guiones (URL-friendly). */
function slugifyOrganizationName(name: string): string {
  const raw = name
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  return raw.slice(0, 80);
}

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

const STRENGTH_KEYS: TranslationKey[] = [
  "auth.strength.very_weak",
  "auth.strength.weak",
  "auth.strength.fair",
  "auth.strength.strong",
];

const ACCOUNT_LOCALES: { value: Locale; native: string }[] = [
  { value: "es", native: "Español" },
  { value: "en", native: "English" },
  { value: "en-gb", native: "English (UK)" },
  { value: "pt", native: "Português" },
  { value: "fr", native: "Français" },
  { value: "de", native: "Deutsch" },
  { value: "it", native: "Italiano" },
];

function selectClassName(error?: string): string {
  return [
    "w-full rounded-lg border px-3 py-2 text-sm outline-none transition focus:ring-2",
    error ? "border-red-500" : "",
  ].join(" ");
}

function modeButtonClass(active: boolean): string {
  return [
    "rounded-md px-3 py-2 text-sm font-medium transition",
    active ? "shadow-sm" : "opacity-80 hover:opacity-100",
  ].join(" ");
}

function RegisterPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteToken = searchParams.get("invite")?.trim() || "";
  const { t, locale: uiLocale } = useTranslation();
  const { preferences } = usePreferences();
  const [accountKind, setAccountKind] = useState<AccountKind>("work");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [company, setCompany] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [timezone, setTimezone] = useState(getBrowserTimezone);
  const [timezoneFollowSystem, setTimezoneFollowSystem] = useState(true);
  const [accountLocale, setAccountLocale] = useState<Locale>(uiLocale);
  const [accepted, setAccepted] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [loading, setLoading] = useState(false);
  /** Mensaje de error de la API (email duplicado, BD no lista, red, etc.). */
  const [formError, setFormError] = useState<string | null>(null);
  const [invitePreview, setInvitePreview] = useState<OrgInvitePreview | null>(null);
  const [inviteLoading, setInviteLoading] = useState(Boolean(inviteToken));
  const draftHydratedRef = useRef(false);

  const isInviteFlow = Boolean(inviteToken && invitePreview?.valid);

  const fullName = buildFullName(firstName, lastName);

  useEffect(() => {
    if (!inviteToken) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- no hay invitacion que cargar, corta el estado de carga inicial.
      setInviteLoading(false);
      return;
    }
    let cancelled = false;
    setInviteLoading(true);
    void fetchOrgInvitePreview(inviteToken)
      .then((preview) => {
        if (cancelled) return;
        setInvitePreview(preview);
        if (preview.valid) {
          setAccountKind("work");
          setEmail(preview.email);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setInvitePreview(null);
        setFormError(
          e instanceof DossierApiError
            ? translateApiErrorMessage(e, t)
            : t("settings.members.invite_invalid")
        );
      })
      .finally(() => {
        if (!cancelled) setInviteLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [inviteToken, t]);

  useEffect(() => {
    if (preferences.timezoneFollowSystem) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- sincroniza el formulario con las preferencias del usuario (sistema externo: contexto de PreferencesProvider), no con una prop/estado local.
      setTimezoneFollowSystem(true);
      setTimezone(getBrowserTimezone());
    } else {
      setTimezoneFollowSystem(false);
      setTimezone(preferences.timezone || getBrowserTimezone());
    }
    setAccountLocale(preferences.locale);
  }, [preferences.timezone, preferences.timezoneFollowSystem, preferences.locale]);

  useEffect(() => {
    if (draftHydratedRef.current || typeof window === "undefined") return;
    const raw = sessionStorage.getItem("dossier_register_draft");
    if (!raw) return;
    try {
      const d = JSON.parse(raw) as Record<string, unknown>;
      const personal =
        d.account_kind === "personal" || d.use_work_organization === false;
      const kind: AccountKind = personal ? "personal" : "work";
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hidrata el formulario desde un borrador guardado en sessionStorage (sistema externo) una sola vez, protegido por draftHydratedRef.
      setAccountKind(kind);
      if (typeof d.first_name === "string") setFirstName(d.first_name);
      if (typeof d.last_name === "string") setLastName(d.last_name);
      if (
        typeof d.full_name === "string" &&
        typeof d.first_name !== "string" &&
        typeof d.last_name !== "string"
      ) {
        const parts = d.full_name.trim().split(/\s+/);
        if (parts[0]) setFirstName(parts[0]);
        if (parts.length > 1) setLastName(parts.slice(1).join(" "));
      }
      if (kind === "work" && typeof d.company_name === "string") {
        setCompany(d.company_name);
      }
      if (kind === "work") {
        if (typeof d.organization_slug_input === "string") {
          setOrgSlug(d.organization_slug_input);
        } else if (typeof d.organization_slug === "string") {
          setOrgSlug(d.organization_slug);
        }
      }
      if (typeof d.email === "string") setEmail(d.email);
    } catch {
      /* ignore */
    }
    draftHydratedRef.current = true;
  }, []);

  function setKind(next: AccountKind) {
    setAccountKind(next);
    if (next === "personal") {
      setOrgSlug("");
    } else {
      setOrgSlug("");
    }
  }

  function passwordStrength(pwd: string): { score: 0 | 1 | 2 | 3 } {
    let score = 0;
    if (pwd.length >= 8) score++;
    if (/[A-Z]/.test(pwd) && /[a-z]/.test(pwd)) score++;
    if (/\d/.test(pwd) && /[^A-Za-z0-9]/.test(pwd)) score++;
    return { score: Math.min(score, 3) as 0 | 1 | 2 | 3 };
  }

  const strength = passwordStrength(password);

  function resolvedOrganizationSlug(): string {
    if (accountKind === "personal") {
      return slugifyOrganizationName(fullName);
    }
    const manual = orgSlug.trim().toLowerCase();
    if (manual) return manual;
    return slugifyOrganizationName(company);
  }

  function validate(): Errors {
    const next: Errors = {};
    if (!firstName.trim()) next.firstName = t("auth.error.first_name_required");
    if (!lastName.trim()) next.lastName = t("auth.error.last_name_required");
    if (!isInviteFlow && accountKind === "work" && !company.trim()) {
      next.company = t("auth.error.company_required");
    }
    if (!isInviteFlow && accountKind === "work") {
      const manual = orgSlug.trim().toLowerCase();
      if (manual && (!SLUG_PATTERN.test(manual) || manual.length < 2)) {
        next.orgSlug = t("auth.error.slug_invalid");
      }
    }
    if (!email.trim()) {
      next.email = t("auth.error.email_required");
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      next.email = t("auth.error.email_invalid");
    }
    if (!password) {
      next.password = t("auth.error.password_required");
    } else if (password.length < 8) {
      next.password = t("auth.error.password_min_8");
    } else if (new TextEncoder().encode(password).length > 72) {
      next.password = t("auth.error.password_max_bytes");
    }
    if (!confirmPassword.trim()) {
      next.confirmPassword = t("auth.error.confirm_required");
    } else if (confirmPassword !== password) {
      next.confirmPassword = t("auth.error.password_mismatch");
    }
    if (!accepted) next.terms = t("auth.error.terms_required");

    const derived = resolvedOrganizationSlug();
    if (!isInviteFlow && (!derived || !SLUG_PATTERN.test(derived) || derived.length < 2)) {
      if (accountKind === "work" && !next.orgSlug) {
        next.company = t("auth.error.slug_unreadable");
      }
      if (
        accountKind === "personal" &&
        firstName.trim() &&
        lastName.trim() &&
        !next.firstName &&
        !next.lastName
      ) {
        next.lastName = t("auth.error.slug_unreadable");
      }
    }

    return next;
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const v = validate();
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length > 0) return;

    const finalSlug = resolvedOrganizationSlug();

    setLoading(true);
    try {
      if (typeof window !== "undefined") {
        const draft = {
          account_kind: accountKind,
          first_name: firstName.trim(),
          last_name: lastName.trim(),
          full_name: fullName,
          company_name: accountKind === "work" ? company.trim() : "",
          organization_slug: finalSlug,
          organization_slug_input:
            accountKind === "work" ? orgSlug.trim().toLowerCase() : "",
          email: email.trim().toLowerCase(),
          timezone,
          locale: accountLocale,
          ui_locale_at_signup: uiLocale,
        };
        sessionStorage.setItem("dossier_register_draft", JSON.stringify(draft));
      }

      const data = await authRegister({
        email: email.trim().toLowerCase(),
        password,
        full_name: fullName,
        locale: accountLocale,
        timezone: getEffectiveTimezone(timezone, timezoneFollowSystem),
        workspace_kind: isInviteFlow ? "work" : accountKind,
        ...(isInviteFlow
          ? { invite_token: inviteToken }
          : accountKind === "work"
            ? { company_name: company.trim() }
            : {}),
      });
      // Tras crear cuenta dejamos sesión iniciada (misma UX que "recuérdame" en login).
      persistAuthToken(data.access_token, true);
      writeDossierUserPreview(
        {
          email: data.user.email,
          full_name: data.user.full_name,
          company_name: data.user.company_name,
          workspace_kind: data.user.workspace_kind,
          organization_plan: data.user.organization_plan,
          is_platform_admin: !!data.user.is_platform_admin,
        },
        "local"
      );
      if (typeof window !== "undefined") {
        sessionStorage.removeItem("dossier_register_draft");
      }
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof DossierApiError) {
        if (err.isMixedContentBlocked()) setFormError(t("auth.error.mixed_content"));
        else if (err.isNetworkError()) setFormError(t("auth.error.network"));
        else setFormError(translateApiErrorMessage(err, t) || t("auth.error.server"));
      } else {
        setFormError(t("auth.error.server"));
      }
    } finally {
      setLoading(false);
    }
  }

  const borderDefault = "var(--border-default)";
  const bgInput = "var(--bg-input)";
  const textPrimary = "var(--text-primary)";
  const textSecondary = "var(--text-secondary)";
  const textSubtle = "var(--text-subtle)";
  const accentFrom = "var(--accent-from)";

  return (
    <AuthShell
      wide
      title={t("auth.register.title")}
      subtitle={t("auth.register.subtitle_credits")}
      footer={
        <>
          {t("auth.register.has_account")}{" "}
          <Link
            href="/login"
            className="font-semibold"
            style={{ color: accentFrom }}
          >
            {t("auth.register.sign_in")}
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
        {formError ? (
          <div
            role="alert"
            className="rounded-lg border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm"
            style={{ color: textPrimary }}
          >
            {formError}
          </div>
        ) : null}
        {inviteLoading ? (
          <p className="text-sm" style={{ color: textSubtle }}>
            {t("settings.members.invite_loading")}
          </p>
        ) : null}
        {isInviteFlow && invitePreview ? (
          <div
            className="rounded-lg border px-3 py-3 text-sm"
            style={{
              borderColor: borderDefault,
              backgroundColor: "var(--bg-surface)",
              color: textSecondary,
            }}
          >
            <p className="font-medium" style={{ color: textPrimary }}>
              {t("settings.members.register_invite_title", {
                org: invitePreview.organization_name,
              })}
            </p>
            <p className="mt-1 text-xs" style={{ color: textSubtle }}>
              {t("settings.members.register_invite_hint", {
                domain: invitePreview.email_domain,
                role: invitePreview.role,
              })}
            </p>
          </div>
        ) : null}
        {!isInviteFlow ? (
        <div className="flex flex-col gap-1.5">
          <span
            className="text-xs font-medium uppercase tracking-wide"
            style={{ color: textSubtle }}
          >
            {t("auth.register.account_mode")}
          </span>
          <div
            className="grid grid-cols-2 gap-1 rounded-lg border p-1"
            style={{
              borderColor: borderDefault,
              backgroundColor: "var(--bg-elevated, rgba(0,0,0,0.2))",
            }}
            role="group"
            aria-label={t("auth.register.account_mode")}
          >
            <button
              type="button"
              onClick={() => setKind("work")}
              className={modeButtonClass(accountKind === "work")}
              style={{
                backgroundColor: accountKind === "work" ? accentFrom : "transparent",
                color: accountKind === "work" ? "#0a0a0a" : textSecondary,
              }}
            >
              {t("auth.register.mode_work")}
            </button>
            <button
              type="button"
              onClick={() => setKind("personal")}
              className={modeButtonClass(accountKind === "personal")}
              style={{
                backgroundColor:
                  accountKind === "personal" ? accentFrom : "transparent",
                color: accountKind === "personal" ? "#0a0a0a" : textSecondary,
              }}
            >
              {t("auth.register.mode_personal")}
            </button>
          </div>
        </div>
        ) : null}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField
            label={t("auth.register.first_name")}
            name="firstName"
            placeholder="María"
            autoComplete="given-name"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            error={errors.firstName}
          />
          <FormField
            label={t("auth.register.last_name")}
            name="lastName"
            placeholder="Pérez"
            autoComplete="family-name"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            error={errors.lastName}
          />
        </div>

        {accountKind === "work" && !isInviteFlow ? (
          <>
            <FormField
              label={t("auth.register.company")}
              name="company"
              placeholder="Alloxentric"
              autoComplete="organization"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              error={errors.company}
            />
            <FormField
              label={t("auth.register.org_slug")}
              name="orgSlug"
              placeholder="mi-empresa"
              autoComplete="off"
              spellCheck={false}
              value={orgSlug}
              onChange={(e) =>
                setOrgSlug(
                  e.target.value
                    .toLowerCase()
                    .replace(/[^a-z0-9-]/g, "")
                    .slice(0, 80),
                )
              }
              error={errors.orgSlug}
              hint={t("auth.register.slug_hint_short")}
            />
          </>
        ) : null}

        <FormField
          label={
            accountKind === "work"
              ? t("auth.register.email_corporate")
              : t("auth.register.email")
          }
          name="email"
          type="email"
          placeholder={
            accountKind === "work" ? "tu@empresa.com" : "tu@email.com"
          }
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          readOnly={isInviteFlow}
          error={errors.email}
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField
            label={t("auth.login.password")}
            name="password"
            type="password"
            passwordToggle
            placeholder={t("auth.register.password_placeholder")}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={errors.password}
          />
          <FormField
            label={t("auth.register.confirm_password")}
            name="confirmPassword"
            type="password"
            passwordToggle
            placeholder={t("auth.register.password_placeholder")}
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            error={errors.confirmPassword}
          />
        </div>

        {password && !errors.password ? (
          <div className="flex items-center gap-2 text-xs -mt-0.5">
            <div className="flex h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800">
              <div
                className={`h-full transition-all ${
                  strength.score === 0
                    ? "w-1/12 bg-red-500"
                    : strength.score === 1
                      ? "w-1/3 bg-orange-500"
                      : strength.score === 2
                        ? "w-2/3 bg-yellow-500"
                        : "w-full bg-emerald-500"
                }`}
              />
            </div>
            <span style={{ color: "var(--text-muted)" }}>
              {t(STRENGTH_KEYS[strength.score])}
            </span>
          </div>
        ) : null}

        <details
          className="group rounded-lg border text-sm"
          style={{ borderColor: borderDefault }}
        >
          <summary
            className="cursor-pointer list-none px-3 py-2 font-medium outline-none transition hover:opacity-90 [&::-webkit-details-marker]:hidden"
            style={{ color: textSecondary }}
          >
            <span className="inline-flex w-full items-center justify-between gap-2">
              {t("auth.register.more_options")}
              <span className="inline-block text-xs opacity-70 transition group-open:rotate-180">
                ▼
              </span>
            </span>
          </summary>
          <div
            className="flex flex-col gap-3 border-t px-3 py-3"
            style={{ borderColor: borderDefault }}
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="timezone"
                  className="text-sm font-medium"
                  style={{ color: textSecondary }}
                >
                  {t("auth.register.timezone")}
                </label>
                <TimezoneSelect
                  id="timezone"
                  name="timezone"
                  timezone={timezone}
                  followSystem={timezoneFollowSystem}
                  title={t("auth.register.timezone_hint")}
                  onChange={({ timezone: tz, followSystem }) => {
                    setTimezone(tz);
                    setTimezoneFollowSystem(followSystem);
                  }}
                  locale={accountLocale}
                  systemLabel={t("settings.timezone_system")}
                  t={t}
                  className={selectClassName()}
                  style={{
                    backgroundColor: bgInput,
                    borderColor: borderDefault,
                    color: textPrimary,
                  }}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="accountLocale"
                  className="text-sm font-medium"
                  style={{ color: textSecondary }}
                >
                  {t("auth.register.account_language")}
                </label>
                <select
                  id="accountLocale"
                  name="accountLocale"
                  value={accountLocale}
                  title={t("auth.register.account_language_hint")}
                  onChange={(e) => setAccountLocale(e.target.value as Locale)}
                  className={selectClassName()}
                  style={{
                    backgroundColor: bgInput,
                    borderColor: borderDefault,
                    color: textPrimary,
                  }}
                >
                  {ACCOUNT_LOCALES.map(({ value, native }) => (
                    <option key={value} value={value}>
                      {native}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </details>

        <label
          className="flex cursor-pointer items-start gap-2 text-sm"
          style={{ color: "var(--text-muted)" }}
        >
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 rounded border border-zinc-700"
          />
          <span>
            {t("auth.register.terms_prefix")}{" "}
            <Link
              href="/terms"
              className="font-medium"
              style={{ color: accentFrom }}
            >
              {t("auth.register.terms_link")}
            </Link>{" "}
            {t("auth.register.and")}{" "}
            <Link
              href="/privacy"
              className="font-medium"
              style={{ color: accentFrom }}
            >
              {t("auth.register.privacy_link")}
            </Link>
            .
          </span>
        </label>
        {errors.terms ? (
          <span className="text-xs text-red-400">{errors.terms}</span>
        ) : null}

        <PrimaryButton type="submit" loading={loading}>
          {t("auth.register.create_free")}
        </PrimaryButton>
      </form>
    </AuthShell>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterPageContent />
    </Suspense>
  );
}
