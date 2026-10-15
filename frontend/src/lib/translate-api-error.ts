import type { TranslateFn } from "@/i18n";
import type { TranslationKey } from "@/i18n/types";
import type { DossierApiError } from "@/lib/dossier-api";
import { toPublicErrorMessage } from "@/lib/public-error-message";

type ApiErrorDetail = { code?: string; domain?: string };

const API_ERROR_CODES: Record<string, TranslationKey> = {
  CORPORATE_EMAIL_REQUIRED: "settings.members.error_corporate_email",
  INVITE_WRONG_DOMAIN: "settings.members.error_invite_wrong_domain",
  INVITES_WORKSPACE_ONLY: "settings.members.error_invites_workspace_only",
};

const LEGACY_API_MESSAGES: Record<string, TranslationKey> = {
  "Tu correo debe ser de dominio corporativo (no Gmail, Outlook personal, etc.).":
    "settings.members.error_corporate_email",
  "Las invitaciones solo están disponibles para organizaciones de empresa.":
    "settings.members.error_invites_workspace_only",
};

function extractDetail(body: unknown): ApiErrorDetail | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "object" && detail !== null && !Array.isArray(detail)) {
    const d = detail as ApiErrorDetail;
    if (typeof d.code === "string") return d;
  }
  return null;
}

export function translateApiError(err: DossierApiError, t: TranslateFn): string {
  const validation = err.body && typeof err.body === "object"
    ? (err.body as { detail?: unknown }).detail
    : null;
  if (err.status === 422 && Array.isArray(validation) && validation.some((item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const field = item as { type?: unknown; loc?: unknown };
    return field.type === "password_too_long_bytes"
      && Array.isArray(field.loc)
      && field.loc.length === 2
      && field.loc[0] === "body"
      && field.loc[1] === "password";
  })) {
    return t("auth.error.password_max_bytes");
  }

  const detail = extractDetail(err.body);
  if (detail?.code) {
    const key = API_ERROR_CODES[detail.code];
    if (key) {
      if (detail.domain) return t(key, { domain: detail.domain });
      return t(key);
    }
  }

  const legacyKey = LEGACY_API_MESSAGES[err.message];
  if (legacyKey) return t(legacyKey);

  const domainMatch = err.message.match(/^Solo puedes invitar correos del dominio @(.+)\.$/);
  if (domainMatch) {
    return t("settings.members.error_invite_wrong_domain", { domain: domainMatch[1] });
  }

  return toPublicErrorMessage(err.message, t, "api");
}
