"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import AuthShell from "@/components/AuthShell";
import FormField from "@/components/FormField";
import PrimaryButton from "@/components/PrimaryButton";
import {
  authLogin,
  clearAuthSession,
  DossierApiError,
  fetchAuthMe,
  getApiBaseUrl,
  getStoredAccessToken,
  persistAuthToken,
  writeDossierUserPreview,
} from "@/lib/dossier-api";
import { useTranslation } from "@/providers/PreferencesProvider";

const REMEMBER_PREF_KEY = "dossier_login_remember";
const LAST_EMAIL_KEY = "dossier_last_login_email";

/** Ruta interna segura tras login (misma regla que al enviar el formulario). */
function resolvePostLoginRedirect(): string {
  if (typeof window === "undefined") return "/dashboard";
  const raw = new URLSearchParams(window.location.search).get("next");
  if (raw && raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "/dashboard";
}

type Errors = {
  email?: string;
  password?: string;
};

export default function LoginPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [errors, setErrors] = useState<Errors>({});
  const [loading, setLoading] = useState(false);
  /** Error global devuelto por la API (credenciales, red, servidor no configurado, etc.). */
  const [formError, setFormError] = useState<string | null>(null);

  /**
   * Si ya hay JWT válido, ir al dashboard. Si el token existe pero la API lo rechaza, limpiar sesión.
   */
  useEffect(() => {
    let cancelled = false;

    async function tryExistingSession() {
      const token = getStoredAccessToken();
      if (!token) {
        const pref = localStorage.getItem(REMEMBER_PREF_KEY);
        const rememberOn = pref !== "0";
        setRemember(rememberOn);
        if (rememberOn) {
          const last = localStorage.getItem(LAST_EMAIL_KEY);
          if (last) setEmail(last);
        }
        const params = new URLSearchParams(window.location.search);
        if (params.get("reason") === "session_expired") {
          setFormError(t("auth.error.session_expired"));
        } else if (params.get("error") === "google") {
          setFormError(t("auth.error.google"));
        }
        return;
      }
      try {
        await fetchAuthMe();
        if (!cancelled) router.replace(resolvePostLoginRedirect());
      } catch (e) {
        if (cancelled) return;
        if (e instanceof DossierApiError && e.status === 401) {
          clearAuthSession();
          setFormError(t("auth.error.session_expired"));
        }
        const pref = localStorage.getItem(REMEMBER_PREF_KEY);
        const rememberOn = pref !== "0";
        setRemember(rememberOn);
        if (rememberOn) {
          const last = localStorage.getItem(LAST_EMAIL_KEY);
          if (last) setEmail(last);
        }
      }
    }

    void tryExistingSession();
    return () => {
      cancelled = true;
    };
  }, [router, t]);

  function validate(): Errors {
    const next: Errors = {};
    if (!email.trim()) {
      next.email = t("auth.error.email_required");
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      next.email = t("auth.error.email_invalid");
    }
    if (!password) {
      next.password = t("auth.error.password_required");
    } else if (password.length < 6) {
      next.password = t("auth.error.password_min");
    }
    return next;
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const v = validate();
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length > 0) return;

    setLoading(true);
    try {
      const data = await authLogin({ email: email.trim(), password });
      persistAuthToken(data.access_token, remember);
      writeDossierUserPreview(
        {
          email: data.user.email,
          full_name: data.user.full_name,
          company_name: data.user.company_name,
          workspace_kind: data.user.workspace_kind,
          organization_plan: data.user.organization_plan,
          is_platform_admin: !!data.user.is_platform_admin,
        },
        remember ? "local" : "session"
      );
      try {
        localStorage.setItem(REMEMBER_PREF_KEY, remember ? "1" : "0");
        if (remember) {
          localStorage.setItem(LAST_EMAIL_KEY, email.trim());
        } else {
          localStorage.removeItem(LAST_EMAIL_KEY);
        }
      } catch {
        /* private mode / quota */
      }
      router.push(resolvePostLoginRedirect());
    } catch (e) {
      if (e instanceof DossierApiError) {
        if (e.isMixedContentBlocked()) setFormError(t("auth.error.mixed_content"));
        else if (e.isNetworkError()) setFormError(t("auth.error.network"));
        else setFormError(e.message || t("auth.error.server"));
      } else {
        setFormError(t("auth.error.server"));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      title={t("auth.login.title")}
      subtitle={t("auth.login.subtitle")}
      footer={
        <>
          {t("auth.login.no_account")}{" "}
          <Link
            href="/register"
            className="font-semibold"
            style={{ color: "var(--accent-from)" }}
          >
            {t("auth.login.create_account")}
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        {formError && (
          <p
            className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
            role="alert"
          >
            {formError}
          </p>
        )}
        <FormField
          label={t("auth.login.email")}
          name="email"
          type="email"
          placeholder="tu@empresa.com"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <FormField
          label={t("auth.login.password")}
          name="password"
          type="password"
          passwordToggle
          placeholder="••••••••"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />

        <div className="flex items-center justify-between text-sm">
          <label className="inline-flex items-center gap-2 cursor-pointer" style={{ color: "var(--text-muted)" }}>
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => {
                const checked = e.target.checked;
                setRemember(checked);
                try {
                  localStorage.setItem(REMEMBER_PREF_KEY, checked ? "1" : "0");
                  if (!checked) {
                    localStorage.removeItem(LAST_EMAIL_KEY);
                  }
                } catch {
                  /* ignore */
                }
              }}
              className="h-4 w-4 rounded border border-zinc-700"
            />
            {t("auth.login.remember")}
          </label>
          <Link
            href="/forgot"
            className="font-medium"
            style={{ color: "var(--accent-from)" }}
          >
            {t("auth.login.forgot")}
          </Link>
        </div>

        <PrimaryButton type="submit" loading={loading}>
          {t("auth.login.submit")}
        </PrimaryButton>

        <div className="relative my-2">
          <div className="absolute inset-0 flex items-center">
            <span
              className="w-full border-t"
              style={{ borderColor: "var(--border-subtle)" }}
            />
          </div>
          <div className="relative flex justify-center">
            <span
              className="px-3 text-xs uppercase tracking-wider"
              style={{
                color: "var(--text-subtle)",
                backgroundColor: "var(--bg-page)",
              }}
            >
              {t("auth.login.or_continue")}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {/* Navegación completa: la API redirige a Google y vuelve a /auth/google. */}
          <a
            href={`${getApiBaseUrl()}/auth/google/login`}
            className="flex h-11 items-center justify-center gap-2 rounded-lg border text-sm font-medium transition hover:opacity-90"
            style={{
              borderColor: "var(--border-default)",
              backgroundColor: "var(--bg-surface)",
              color: "var(--text-primary)",
            }}
          >
            Google
          </a>
          <button
            type="button"
            disabled
            title={t("auth.login.microsoft_soon")}
            className="flex h-11 items-center justify-center gap-2 rounded-lg border text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              borderColor: "var(--border-default)",
              backgroundColor: "var(--bg-surface)",
              color: "var(--text-primary)",
            }}
          >
            Microsoft
          </button>
        </div>
      </form>
    </AuthShell>
  );
}
