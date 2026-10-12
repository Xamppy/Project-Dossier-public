/**
 * Cliente HTTP mínimo para hablar con la API FastAPI (registro / login).
 *
 * - `NEXT_PUBLIC_API_URL`: URL base del backend (ej. http://127.0.0.1:8000).
 *   Defínela en `frontend/.env.local` (no subas ese archivo a git).
 * - El navegador solo puede llamar a otro origen si el backend tiene CORS
 *   permitiendo el origen del Next.js (ver `CORS_ORIGINS` en `.env` del backend).
 */

import type { Locale } from "@/i18n/types";
import { clearCalendarEventsCache } from "@/lib/calendar-events-cache";

/** Clave donde guardamos el JWT tras login o registro (localStorage o sessionStorage). */
export const AUTH_TOKEN_STORAGE_KEY = "dossier_access_token";

export function getApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (raw) return raw.replace(/\/$/, "");
  return "http://127.0.0.1:8000";
}

/** Marca interna: página HTTPS + API en http (el navegador bloquea el fetch). */
const FETCH_FAILED_MIXED_CONTENT = "__dossier_fetch_mixed_content__";

export type AuthUser = {
  id: string;
  email: string;
  full_name: string;
  company_name: string;
  /** `personal` = espacio sin nombre de empresa comercial (solo tú). */
  workspace_kind?: "personal" | "work";
  organization_id?: string;
  role?: string;
  is_platform_admin?: boolean;
  /** Plan de la organización activa (`organizations.plan`). */
  organization_plan?: string;
  credits_balance?: number;
  credits_monthly_limit?: number;
  /** Texto libre: qué es la empresa (personaliza prompts de dossiers). */
  organization_company_summary?: string | null;
  /** Sector o área de negocio. */
  organization_industry_or_area?: string | null;
  /** Idioma de interfaz (sincronizado con Configuración). */
  locale?: string;
  timezone?: string;
  /** match | es | en | pt | … — idioma de salida de dossiers. */
  dossier_output_language?: string;
  /** 7, 14, 30, 90 o null (conservar indefinidamente). */
  dossier_retention_days?: number | null;
};

/** Fila devuelta por `GET /dossiers` (tabla `dossiers` en PostgreSQL). */
export type DossierListItem = {
  type?: "dossier";
  id: string;
  subject_name: string | null;
  subject_email: string | null;
  status: string;
  status_message?: string | null;
  depth_level: string;
  credits_consumed: number;
  created_at: string | null;
  updated_at: string | null;
  dossier_data: unknown;
  trigger_source?: string | null;
  calendar_meeting?: string | null;
  module_kind?: "corporate" | "person" | "mixed";
  dossier_folder_id?: string | null;
};

/** Carpeta con dossiers de empresa + persona (mismo evento de calendario). */
export type DossierFolderListItem = {
  type: "folder";
  id: string;
  title: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  trigger_source?: string | null;
  calendar_meeting?: string | null;
  dossiers: DossierListItem[];
};

export type DossierListEntry = DossierListItem | DossierFolderListItem;

export function isDossierFolderEntry(
  entry: DossierListEntry
): entry is DossierFolderListItem {
  return entry.type === "folder";
}

export type DossiersListResponse = {
  organization_id: string;
  items: DossierListEntry[];
};

export type DossierFolderDetailResponse = DossierFolderListItem;

/** Permisos efectivos del dossier para el usuario actual. */
export type DossierPermissions = {
  is_owner: boolean;
  can_share: boolean;
  can_delete: boolean;
  can_mutate: boolean;
};

export type DossierShareItem = {
  user_id: string;
  email: string;
  full_name: string;
  shared_at: string | null;
};

export type OrgMemberItem = {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
};

export type OrgMemberManageItem = OrgMemberItem & {
  joined_at: string | null;
  is_self: boolean;
};

export type OrgInviteItem = {
  id: string;
  email: string;
  role: string;
  status: string;
  invite_url: string | null;
  created_at: string | null;
  expires_at: string | null;
  joined_immediately: boolean;
};

export type OrgInvitePreview = {
  organization_id: string;
  organization_name: string;
  email: string;
  role: string;
  email_domain: string;
  expires_at: string | null;
  valid: boolean;
  token?: string | null;
};

/** Respuesta de `GET /dossiers/{id}` (detalle). */
export type DossierDetailResponse = {
  id: string;
  organization_id: string;
  requested_by_user_id?: string;
  subject_name: string | null;
  subject_email: string | null;
  status: string;
  depth_level: string;
  credits_consumed: number;
  created_at: string | null;
  updated_at: string | null;
  dossier_data: unknown;
  alerts: unknown;
  agents_activated?: string[];
  agents_failed?: string[];
  data_sources_used?: string[];
  generation_duration_ms?: number | null;
  status_message?: string | null;
  trigger_source?: string | null;
  calendar_meeting?: string | null;
  dossier_folder_id?: string | null;
  permissions?: DossierPermissions;
  shares?: DossierShareItem[];
};

export type AuthSuccessResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

/** Perfil mínimo guardado tras login/registro para mostrar nombre en el layout (sidebar). */
export type DossierUserPreview = {
  email: string;
  full_name: string;
  company_name?: string;
  workspace_kind?: "personal" | "work";
  organization_plan?: string;
  is_platform_admin?: boolean;
};

export const DOSSIER_USER_PREVIEW_KEY = "dossier_user_preview";

export function readDossierUserPreview(): DossierUserPreview | null {
  if (typeof window === "undefined") return null;
  const raw =
    window.localStorage.getItem(DOSSIER_USER_PREVIEW_KEY) ??
    window.sessionStorage.getItem(DOSSIER_USER_PREVIEW_KEY);
  if (!raw) return null;
  try {
    const o = JSON.parse(raw) as Record<string, unknown>;
    if (typeof o.email !== "string" || typeof o.full_name !== "string") return null;
    return {
      email: o.email,
      full_name: o.full_name,
      company_name: typeof o.company_name === "string" ? o.company_name : undefined,
      workspace_kind:
        o.workspace_kind === "personal" || o.workspace_kind === "work"
          ? o.workspace_kind
          : undefined,
      organization_plan:
        typeof o.organization_plan === "string" ? o.organization_plan : undefined,
      is_platform_admin: typeof o.is_platform_admin === "boolean" ? o.is_platform_admin : undefined,
    };
  } catch {
    return null;
  }
}

/** Alineado con `persistAuthToken`: local = recuérdame / post-registro; session = sesión temporal. */
export function writeDossierUserPreview(
  data: DossierUserPreview,
  storage: "local" | "session"
): void {
  if (typeof window === "undefined") return;
  const raw = JSON.stringify(data);
  if (storage === "local") {
    window.localStorage.setItem(DOSSIER_USER_PREVIEW_KEY, raw);
    window.sessionStorage.removeItem(DOSSIER_USER_PREVIEW_KEY);
  } else {
    window.sessionStorage.setItem(DOSSIER_USER_PREVIEW_KEY, raw);
    window.localStorage.removeItem(DOSSIER_USER_PREVIEW_KEY);
  }
}

/** Error de red o respuesta HTTP no OK con cuerpo parseable de FastAPI. */
export class DossierApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "DossierApiError";
    this.status = status;
    this.body = body;
  }

  /** True si falló fetch (servidor apagado, DNS, etc.). */
  isNetworkError(): boolean {
    return this.status === 0;
  }

  /** Página en HTTPS y `NEXT_PUBLIC_API_URL` en http (contenido mixto; el navegador bloquea). */
  isMixedContentBlocked(): boolean {
    return this.status === 0 && this.message === FETCH_FAILED_MIXED_CONTENT;
  }
}

function throwFetchFailed(): never {
  if (typeof window !== "undefined" && window.location.protocol === "https:") {
    const base = getApiBaseUrl().trim().toLowerCase();
    if (base.startsWith("http:")) {
      throw new DossierApiError(0, FETCH_FAILED_MIXED_CONTENT);
    }
  }
  throw new DossierApiError(0, "NETWORK");
}

function formatFastApiValidationItem(item: unknown): string {
  if (!item || typeof item !== "object") return JSON.stringify(item);
  const o = item as { loc?: unknown[]; msg?: unknown };
  const loc =
    Array.isArray(o.loc) && o.loc.length > 0
      ? o.loc.map((x) => (typeof x === "string" ? x : String(x))).join(".")
      : "";
  const msg = typeof o.msg === "string" ? o.msg : "";
  if (loc && msg) return `${loc}: ${msg}`;
  if (msg) return msg;
  return JSON.stringify(item);
}

function parseFastApiDetail(data: unknown): string {
  if (!data || typeof data !== "object") return "";
  const d = data as { detail?: unknown };
  if (typeof d.detail === "string") return d.detail;
  if (typeof d.detail === "object" && d.detail !== null && !Array.isArray(d.detail)) {
    const obj = d.detail as { code?: unknown };
    if (typeof obj.code === "string") return obj.code;
  }
  if (Array.isArray(d.detail)) {
    return d.detail.map((item) => formatFastApiValidationItem(item)).join(" ");
  }
  return "";
}

function assertAuthSuccessResponse(data: unknown): asserts data is AuthSuccessResponse {
  if (!data || typeof data !== "object") {
    throw new DossierApiError(
      502,
      "La API respondió con un cuerpo inválido (no es JSON de auth).",
      data
    );
  }
  const d = data as Record<string, unknown>;
  if (typeof d.access_token !== "string" || !d.access_token) {
    throw new DossierApiError(
      502,
      "La API respondió sin access_token. Revisa la consola de red y la URL del backend.",
      data
    );
  }
  if (!d.user || typeof d.user !== "object") {
    throw new DossierApiError(502, "La API respondió sin objeto user.", data);
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch {
    throwFetchFailed();
  }

  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }

  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }

  return parsed as T;
}

export async function authRegister(payload: {
  email: string;
  password: string;
  full_name: string;
  company_name?: string | null;
  workspace_kind?: "personal" | "work";
  invite_token?: string | null;
  locale?: Locale | null;
  timezone?: string | null;
}): Promise<AuthSuccessResponse> {
  const data = await postJson<AuthSuccessResponse>("/auth/register", payload);
  assertAuthSuccessResponse(data);
  return data;
}

export async function authLogin(payload: {
  email: string;
  password: string;
}): Promise<AuthSuccessResponse> {
  const data = await postJson<AuthSuccessResponse>("/auth/login", payload);
  assertAuthSuccessResponse(data);
  return data;
}

/** Respuesta de POST /auth/forgot-password (siempre la misma si HTTP 200). */
export type ForgotPasswordResponse = { ok: true };

/** Solicitud de recuperación de contraseña (el backend no revela si el correo existe). */
export async function authForgotPassword(payload: {
  email: string;
}): Promise<ForgotPasswordResponse> {
  return postJson<ForgotPasswordResponse>("/auth/forgot-password", payload);
}

/** Perfil del usuario autenticado (JWT). */
export async function fetchAuthMe(): Promise<AuthUser> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/me`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida de /auth/me.", parsed);
  }
  return parsed as AuthUser;
}

/** Re-emite JWT con rol/org actuales (p. ej. tras cambio de rol en la org). */
export async function refreshAuthSession(): Promise<AuthSuccessResponse> {
  const data = await postJsonWithAuth<AuthSuccessResponse>("/auth/session/refresh", {});
  assertAuthSuccessResponse(data);
  const remember = getAuthTokenStorageMode() === "local";
  persistAuthToken(data.access_token, remember);
  return data;
}

/** Membresía del usuario para el selector de organización. */
export type UserOrganizationItem = {
  organization_id: string;
  organization_name: string;
  role: string;
  workspace_kind: "personal" | "work";
  is_primary: boolean;
  is_active: boolean;
};

/** Organizaciones a las que pertenece el usuario autenticado. */
export async function fetchMyOrganizations(): Promise<{ items: UserOrganizationItem[] }> {
  return getJsonWithAuth<{ items: UserOrganizationItem[] }>("/auth/me/organizations");
}

/** Cambia la organización activa de la sesión y guarda el JWT nuevo. */
export async function switchActiveOrganization(
  organizationId: string
): Promise<AuthSuccessResponse> {
  const data = await postJsonWithAuth<AuthSuccessResponse>("/auth/session/switch", {
    organization_id: organizationId,
  });
  assertAuthSuccessResponse(data);
  const remember = getAuthTokenStorageMode() === "local";
  persistAuthToken(data.access_token, remember);
  return data;
}

export type AuthUserPreferencesPatch = {
  locale?: string;
  timezone?: string;
  dossier_output_language?: string;
  dossier_retention_days?: number | null;
};

/** Sincroniza idioma de interfaz / zona horaria / idioma de dossiers con PostgreSQL. */
export async function patchAuthUserPreferences(
  payload: AuthUserPreferencesPatch
): Promise<AuthUser> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/me/preferences`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida de /auth/me/preferences.", parsed);
  }
  return parsed as AuthUser;
}

export type ChangePasswordPayload = {
  current_password: string;
  new_password: string;
};

export type ChangeEmailPayload = {
  new_email: string;
  current_password: string;
};

export type DeleteAccountPayload = {
  current_password: string;
  confirm: "DELETE";
};

export async function patchMyPassword(payload: ChangePasswordPayload): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/me/password`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throwFetchFailed();
  }
  if (!res.ok) {
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { detail: text.slice(0, 500) };
    }
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
}

export async function patchMyEmail(payload: ChangeEmailPayload): Promise<AuthSuccessResponse> {
  const data = await patchJsonWithAuth<AuthSuccessResponse>("/auth/me/email", payload);
  assertAuthSuccessResponse(data);
  return data;
}

export async function deleteMyAccount(payload: DeleteAccountPayload): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/me`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throwFetchFailed();
  }
  if (!res.ok) {
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { detail: text.slice(0, 500) };
    }
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
}

export type AdminOverview = {
  users_total: number;
  organizations_total: number;
  dossiers_total: number;
};

export type AdminUserRow = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_platform_admin: boolean;
  created_at: string | null;
  organization_id: string | null;
  organization_name: string | null;
  workspace_kind?: "personal" | "work" | null;
  plan: string | null;
  credits_balance: number | null;
  credits_monthly_limit: number | null;
  dossiers_count: number;
};

export type AdminUsersResponse = { total: number; items: AdminUserRow[] };

export type AdminOrgRow = {
  id: string;
  name: string;
  slug: string;
  plan: string;
  credits_balance: number;
  credits_monthly_limit: number;
  is_active: boolean;
  members_count: number;
  dossiers_count: number;
  created_at: string | null;
  workspace_kind?: "personal" | "work";
};

export type AdminOrgsResponse = { total: number; items: AdminOrgRow[] };

export type AdminDossierRow = {
  id: string;
  organization_id: string;
  organization_name: string;
  workspace_kind?: "personal" | "work";
  requested_by_user_id: string;
  requested_by_email: string;
  subject_name: string | null;
  subject_email: string | null;
  status: string;
  credits_consumed: number;
  created_at: string | null;
};

export type AdminDossiersResponse = { total: number; items: AdminDossierRow[] };

async function getJsonWithAuth<T>(path: string): Promise<T> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as T;
}

/** Estado de un indicador de Resumen: cada uno es una situación distinta, no un cero. */
export type DashboardMetricState = "ok" | "empty" | "partial" | "unavailable" | "not_connected";

export type DashboardMetricContext = {
  state: DashboardMetricState;
  /** Código estable que el cliente traduce (p. ej. `calendar_incomplete`). */
  reason: string | null;
  /** La evidencia es fiable desde esta fecha (ISO 8601). */
  measured_from: string | null;
  measured_to: string | null;
};

export type DashboardSummary = {
  as_of: string;
  timezone: string;
  upcoming: DashboardMetricContext & {
    from: string;
    to: string;
    eligible_meetings: number | null;
    prepared_meetings: number | null;
    pending_meetings: number | null;
    coverage_percent: number | null;
  };
  /** Créditos estimados para generar lo que falta en las reuniones de los próximos 7 días. */
  preparation_cost: DashboardMetricContext & {
    from: string;
    to: string;
    estimated_credits: number | null;
    meetings_to_generate: number | null;
    /** `unlimited` = Enterprise sin bloqueo por saldo; `disabled` = cobro desactivado. */
    billing: "charged" | "unlimited" | "disabled";
    exceeds_balance: boolean | null;
  };
  credits: DashboardMetricContext & {
    balance: number | null;
    monthly_limit: number | null;
  };
};

/**
 * Indicadores de Resumen (`GET /dashboard/summary`). Usuario y organización salen del JWT:
 * no se envía ningún identificador. Solo lectura: no genera dossiers ni consume créditos.
 */
export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const data = await getJsonWithAuth<Partial<DashboardSummary> | null>("/dashboard/summary");
  if (!data || !data.upcoming || !data.preparation_cost || !data.credits) {
    throw new DossierApiError(502, "Respuesta inválida de /dashboard/summary.", data);
  }
  return data as DashboardSummary;
}

async function patchJsonWithAuth<T>(
  path: string,
  body: unknown,
  method: "PATCH" | "POST" = "PATCH"
): Promise<T> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as T;
}

export async function fetchAdminOverview(): Promise<AdminOverview> {
  return getJsonWithAuth<AdminOverview>("/admin/overview");
}

export async function fetchAdminUsers(limit = 50, offset = 0): Promise<AdminUsersResponse> {
  const q = `limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`;
  return getJsonWithAuth<AdminUsersResponse>(`/admin/users?${q}`);
}

export async function fetchAdminOrganizations(limit = 50, offset = 0): Promise<AdminOrgsResponse> {
  const q = `limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`;
  return getJsonWithAuth<AdminOrgsResponse>(`/admin/organizations?${q}`);
}

export async function fetchAdminDossiers(limit = 50, offset = 0): Promise<AdminDossiersResponse> {
  const q = `limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`;
  return getJsonWithAuth<AdminDossiersResponse>(`/admin/dossiers?${q}`);
}

export type AdminUserRolesPatchBody = {
  is_platform_admin: boolean;
};

/** Actualiza solo el rol de administrador de plataforma (`PATCH /admin/users/{id}`). */
export async function patchAdminUserRoles(
  userId: string,
  body: AdminUserRolesPatchBody
): Promise<AdminUserRow> {
  return patchJsonWithAuth<AdminUserRow>(`/admin/users/${encodeURIComponent(userId)}`, body);
}

/** Elimina una cuenta de usuario (`DELETE /admin/users/{id}`, solo admin de plataforma). */
export async function deleteAdminUser(userId: string): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/admin/users/${encodeURIComponent(userId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  if (res.status === 204) return;
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
  throw new DossierApiError(res.status, msg, parsed);
}

export type OrganizationPlanPatchBody = {
  plan: "free" | "pro" | "enterprise";
};

/** Cambia el plan de la organización del JWT (solo rol `admin` en la org). */
export async function patchOrganizationPlan(body: OrganizationPlanPatchBody): Promise<AuthUser> {
  return patchJsonWithAuth<AuthUser>("/auth/organization/plan", body);
}

export type OrganizationDossierContextPatchBody = {
  company_summary: string;
  industry_or_area: string;
};

/** Contexto de empresa para prompts (solo rol `admin` en la org). */
export async function patchOrganizationDossierContext(
  body: OrganizationDossierContextPatchBody
): Promise<AuthUser> {
  return patchJsonWithAuth<AuthUser>("/auth/organization/dossier-context", body);
}

/**
 * Guarda el JWT: localStorage si "recuérdame", si no sessionStorage (se pierde al cerrar pestaña).
 * Limpia el otro almacén para no dejar un token viejo.
 */
export function persistAuthToken(token: string, remember: boolean): void {
  if (typeof window === "undefined") return;
  if (remember) {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  } else {
    sessionStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  }
}

/** Dónde está guardado el JWT (alineado con persistAuthToken). */
export function getAuthTokenStorageMode(): "local" | "session" {
  if (typeof window === "undefined") return "local";
  if (window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)) return "local";
  if (window.sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY)) return "session";
  return "local";
}

/** JWT actual guardado por `persistAuthToken` (localStorage o sessionStorage). */
export function getStoredAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return (
    localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ??
    sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
  );
}

/** Quita JWT y vista previa de usuario en local y session (cerrar sesión). */
export function clearAuthSession(): void {
  clearCalendarEventsCache();
  if (typeof window === "undefined") return;
  localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  localStorage.removeItem(DOSSIER_USER_PREVIEW_KEY);
  sessionStorage.removeItem(DOSSIER_USER_PREVIEW_KEY);
}

async function postJsonWithAuth<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw err;
    }
    throwFetchFailed();
  }

  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }

  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }

  return parsed as T;
}

/** Igual que ``CorporateCompanyResolution`` en la API (Pydantic). */
export type CorporateCompanyResolutionPayload =
  | {
      source: "companies_house";
      title: string;
      company_number: string;
    }
  | {
      source: "sec_edgar";
      title: string;
      ticker: string;
      cik: string;
    };

export type CreateCorporateDossierPayload = {
  subject_query: string;
  subject_email?: string;
  depth: "basic" | "standard" | "deep";
  resolution?: CorporateCompanyResolutionPayload;
  /** Código de idioma de salida (es, en, pt, …) desde Configuración. */
  output_language?: string;
};

/** Coincidencias UK/US para desambiguar el nombre de empresa. */
export type CorporateCompanySearchUk = {
  company_number: string;
  title: string;
  company_status: string;
  company_type: string;
};

export type CorporateCompanySearchUs = {
  ticker: string;
  title: string;
  cik: string;
};

export type CorporateCompanySearchResponse = {
  query: string;
  uk: CorporateCompanySearchUk[];
  us: CorporateCompanySearchUs[];
  warnings: string[];
};

export type CreateCorporateDossierResponse = {
  id: string;
  organization_id: string;
  status: string;
  credits_consumed: number;
  organization_credits_balance: number;
  generation_duration_ms: number | null;
  cache_hit?: boolean;
};

/** Búsqueda de empresas (UK + US) para elegir el registro correcto. */
export async function fetchCorporateCompanySearch(
  q: string
): Promise<CorporateCompanySearchResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers/corporate/company-search?q=${encodeURIComponent(q)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as CorporateCompanySearchResponse;
}

export type PersonResearchPayload = {
  full_name: string;
  job_area?: string | null;
  company?: string | null;
  country?: string | null;
  city?: string | null;
  extra_keywords?: string | null;
  email?: string | null;
  linkedin_url?: string | null;
  start?: number;
  max_profiles?: number;
  reveal_contact_details?: boolean;
  include_posts?: boolean;
  /** `gemini_web` | `pdl` (por defecto) */
  research_source?: "gemini_web" | "pdl";
  /** Código de idioma de salida (es, en, pt, …) desde Configuración. */
  output_language?: string;
  /** Encola la generación y responde con job_id. */
  async_mode?: boolean;
  /** Ejecuta investigación nueva sin reutilizar informe previo. */
  force_refresh?: boolean;
  /** Actualiza un dossier existente (misma carpeta de reunión). */
  replace_dossier_id?: string;
};

export type PdlHealthResponse = {
  configured: boolean;
  status: string;
  message?: string;
  api_reachable?: boolean;
  enrich_access?: boolean;
  search_access?: boolean;
  test_match?: boolean;
};

export type PersonSavedDossier = {
  id: string;
  organization_id: string;
  status: string;
  credits_consumed: number;
  generation_duration_ms: number | null;
};

export type PersonResearchApiResponse = {
  filters_applied: Record<string, unknown>;
  search_attempts: unknown[];
  profile_urls: string[];
  profiles: unknown[];
  posts_by_url: Record<string, unknown>;
  llm_analysis_markdown: string | null;
  /** True si el informe incluyó bloque desde búsqueda web pública. */
  gemini_google_search_used?: boolean;
  warnings: string[];
  /** Presente si se guardó fila en `dossiers` (hay cuerpo de informe). */
  saved_dossier: PersonSavedDossier | null;
  /** `redis_cache` = reutilizado desde Redis; `generated` = pipeline ejecutado. */
  dossier_source?: "generated" | "redis_cache";
  /** True si el usuario pidió investigación nueva sin reutilizar informe previo. */
  force_refresh?: boolean;
};

export async function postPersonResearch(
  payload: PersonResearchPayload
): Promise<PersonResearchApiResponse> {
  return postJsonWithAuth<PersonResearchApiResponse>("/dossiers/person/research", payload);
}

export type EnqueuePersonResearchResponse = {
  async: true;
  job_id: string;
  status: DossierGenerationJobStatus;
  meeting_label?: string | null;
  credits_estimated?: number;
  mensaje?: string;
};

/** Encola investigación de persona (no bloquea; ver toast global / polling de jobs). */
export async function enqueuePersonResearch(
  payload: PersonResearchPayload
): Promise<EnqueuePersonResearchResponse> {
  const parsed = await postJsonWithAuth<EnqueuePersonResearchResponse | PersonResearchApiResponse>(
    "/dossiers/person/research",
    { ...payload, async_mode: true }
  );
  if (
    !parsed ||
    typeof parsed !== "object" ||
    !("async" in parsed) ||
    !parsed.async ||
    typeof (parsed as EnqueuePersonResearchResponse).job_id !== "string"
  ) {
    throw new DossierApiError(502, "La API no devolvió job_id para la generación asíncrona.", parsed);
  }
  return parsed as EnqueuePersonResearchResponse;
}

export async function getPdlIntegrationHealth(): Promise<PdlHealthResponse> {
  const res = await fetch(`${getApiBaseUrl()}/integrations/pdl/health`, { cache: "no-store" });
  const parsed = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg =
      typeof parsed === "object" && parsed && "detail" in parsed
        ? String((parsed as { detail?: unknown }).detail)
        : res.statusText;
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as PdlHealthResponse;
}

/** Genera dossier con pipeline LangGraph (UK + US + Gemini) y lo persiste en la API. */
export async function createCorporateDossier(
  payload: CreateCorporateDossierPayload,
  signal?: AbortSignal,
): Promise<CreateCorporateDossierResponse> {
  return postJsonWithAuth<CreateCorporateDossierResponse>(
    "/dossiers/corporate/generate",
    payload,
    signal,
  );
}

/**
 * Lista dossiers de la organización del token (`org_id` en el JWT).
 * Requiere haber aplicado el SQL de migración y tener filas en `dossiers`.
 */
export async function fetchDossiersFromApi(limit = 50): Promise<DossiersListResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers?limit=${encodeURIComponent(String(limit))}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as DossiersListResponse;
}

/** Carpeta con dossiers de un mismo evento (`GET /dossiers/folders/{id}`). */
export async function fetchDossierFolderById(
  folderId: string
): Promise<DossierFolderDetailResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers/folders/${encodeURIComponent(folderId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as DossierFolderDetailResponse;
}

/** Detalle de un dossier (`GET /dossiers/{id}`). */
export async function fetchDossierById(dossierId: string): Promise<DossierDetailResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers/${encodeURIComponent(dossierId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as DossierDetailResponse;
}

/** Miembros de la organización activa (`GET /auth/organization/members`). */
export async function fetchOrgMembers(): Promise<{ items: OrgMemberItem[] }> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/organization/members`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as { items: OrgMemberItem[] };
}

/** Miembros para gestión RBAC (`GET /auth/organization/members/manage`, solo admin org). */
export async function fetchOrgMembersForManagement(): Promise<{ items: OrgMemberManageItem[] }> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/organization/members/manage`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as { items: OrgMemberManageItem[] };
}

export async function patchOrgMemberRole(
  userId: string,
  role: string
): Promise<OrgMemberManageItem> {
  return patchJsonWithAuth<OrgMemberManageItem>(
    `/auth/organization/members/${encodeURIComponent(userId)}`,
    { role }
  );
}

export async function deleteOrgMember(userId: string): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/organization/members/${encodeURIComponent(userId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  if (res.status === 204) return;
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
  throw new DossierApiError(res.status, msg, parsed);
}

export async function fetchOrgInvites(): Promise<{
  organization_domain: string;
  items: OrgInviteItem[];
}> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/organization/invites`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as { organization_domain: string; items: OrgInviteItem[] };
}

export async function createOrgInvite(payload: {
  email: string;
  role: "admin" | "user" | "viewer";
}): Promise<OrgInviteItem> {
  return patchJsonWithAuth<OrgInviteItem>("/auth/organization/invites", payload, "POST");
}

export async function revokeOrgInvite(inviteId: string): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/organization/invites/${encodeURIComponent(inviteId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  if (res.status === 204) return;
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
  throw new DossierApiError(res.status, msg, parsed);
}

/** Vista previa pública de invitación (sin JWT). */
export async function fetchOrgInvitePreview(token: string): Promise<OrgInvitePreview> {
  const url = `${getApiBaseUrl()}/auth/organization/invites/preview?token=${encodeURIComponent(token)}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" } });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as OrgInvitePreview;
}

export async function fetchMyPendingInvites(): Promise<{ items: OrgInvitePreview[] }> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/auth/me/pending-invites`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as { items: OrgInvitePreview[] };
}

export async function acceptOrgInvite(token: string): Promise<AuthSuccessResponse> {
  const data = await patchJsonWithAuth<AuthSuccessResponse>(
    "/auth/organization/invites/accept",
    { token },
    "POST"
  );
  assertAuthSuccessResponse(data);
  return data;
}

export async function createDossierShare(
  dossierId: string,
  userId: string
): Promise<{ dossier_id: string; items: DossierShareItem[] }> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers/${encodeURIComponent(dossierId)}/shares`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ user_id: userId }),
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as { dossier_id: string; items: DossierShareItem[] };
}

export async function deleteDossierShare(dossierId: string, userId: string): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers/${encodeURIComponent(dossierId)}/shares/${encodeURIComponent(userId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  if (!res.ok && res.status !== 204) {
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { detail: text.slice(0, 500) };
    }
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
}

/** Elimina un dossier (`DELETE /dossiers/{id}`). Respuesta 204 sin cuerpo. */
export async function deleteDossierFromApi(dossierId: string): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers/${encodeURIComponent(dossierId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { detail: text.slice(0, 500) };
    }
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
}

/** Elimina todos los dossiers de una carpeta (`DELETE /dossiers/folders/{id}`). */
export async function deleteDossierFolderFromApi(folderId: string): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossiers/folders/${encodeURIComponent(folderId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { detail: text.slice(0, 500) };
    }
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
}

/** Respuesta de ``GET /integrations/{google|microsoft}/start?as_json=true``. */
export type CalendarOAuthStartJson = { authorize_url: string; redirect_uri?: string | null };

/** @deprecated Usa ``CalendarOAuthStartJson``. */
export type MicrosoftOAuthStartJson = CalendarOAuthStartJson;

/** Inicia OAuth Microsoft (usuario de la app); devuelve la URL a la que redirigir el navegador. */
export async function fetchMicrosoftIntegrationStartAsJson(): Promise<CalendarOAuthStartJson> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/integrations/microsoft/start?as_json=true`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (
    !parsed ||
    typeof parsed !== "object" ||
    typeof (parsed as { authorize_url?: unknown }).authorize_url !== "string"
  ) {
    throw new DossierApiError(502, "La API no devolvió authorize_url.", parsed);
  }
  return parsed as CalendarOAuthStartJson;
}

/** Inicia OAuth Google Calendar (usuario de la app); devuelve la URL de autorización. */
export async function fetchGoogleIntegrationStartAsJson(): Promise<CalendarOAuthStartJson> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/integrations/google/start?as_json=true`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (
    !parsed ||
    typeof parsed !== "object" ||
    typeof (parsed as { authorize_url?: unknown }).authorize_url !== "string"
  ) {
    throw new DossierApiError(502, "La API no devolvió authorize_url.", parsed);
  }
  return parsed as CalendarOAuthStartJson;
}

export type CalendarProvider = "google" | "microsoft";

/** Desconecta un calendario conectado (Google u Outlook) del usuario actual. */
export async function disconnectCalendarIntegration(
  provider: CalendarProvider,
): Promise<void> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/integrations/${provider}/disconnect`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  if (!res.ok) {
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { detail: text.slice(0, 500) };
    }
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
}

export type CalendarDiagnosticoResponse = Record<string, unknown>;

/** Diagnóstico de calendario vacío (Google o Outlook). */
export async function fetchCalendarDiagnostico(
  provider: CalendarProvider,
): Promise<CalendarDiagnosticoResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const path =
    provider === "google"
      ? "/calendario/diagnostico-google"
      : "/calendario/diagnostico-outlook";
  const url = `${getApiBaseUrl()}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida de diagnóstico de calendario.", parsed);
  }
  return parsed as CalendarDiagnosticoResponse;
}

/** Fila normalizada de ``GET /calendario/eventos`` (Graph). */
export type OutlookReunionApi = {
  id?: string | null;
  tema?: string;
  descripcion?: string;
  participantes?: string;
  inicio?: string;
  fin?: string;
  ubicacion?: string;
  todo_el_dia?: boolean;
};

export type CalendarEventosApiResponse = {
  total: number;
  reuniones: OutlookReunionApi[];
  mensaje: string | null;
};

/** Lista reuniones de Outlook usando el JWT de la app y tokens en servidor. */
export async function fetchOutlookCalendarEventos(options?: {
  top?: number;
  incluir_pasadas?: boolean;
}): Promise<CalendarEventosApiResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const sp = new URLSearchParams();
  if (options?.top != null) sp.set("top", String(options.top));
  if (options?.incluir_pasadas) sp.set("incluir_pasadas", "true");
  const qs = sp.toString();
  const pathUrl = `${getApiBaseUrl()}/calendario/eventos-outlook${qs ? `?${qs}` : ""}`;
  let res: Response;
  try {
    res = await fetch(pathUrl, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida de /calendario/eventos-outlook.", parsed);
  }
  const o = parsed as Record<string, unknown>;
  const reuniones = Array.isArray(o.reuniones) ? (o.reuniones as OutlookReunionApi[]) : [];
  const total = typeof o.total === "number" ? o.total : reuniones.length;
  const mensaje = o.mensaje === null || typeof o.mensaje === "string" ? (o.mensaje as string | null) : null;
  return { total, reuniones, mensaje };
}

export type CalendarIncompleteReason = "limite_paginas" | "tiempo_agotado" | "error_proveedor";

export type CalendarEventosRangoResponse = {
  total: number;
  reuniones: OutlookReunionApi[];
  mensaje: string | null;
  rango: { desde: string; hasta: string } | null;
  /** `false` = el servidor devolvió solo una parte; nunca se debe presentar como la agenda completa. */
  completo: boolean;
  motivoIncompleto: CalendarIncompleteReason | null;
};

const INCOMPLETE_REASONS: CalendarIncompleteReason[] = ["limite_paginas", "tiempo_agotado", "error_proveedor"];

/**
 * Reuniones que se solapan con ``[desde, hasta)`` (RFC3339 con offset, máx. 62 días).
 * Solo se envían ``desde`` y ``hasta``: el servidor rechaza mezclarlos con ``top``/``dias``.
 */
export async function fetchCalendarEventosPorIntervalo(
  provider: CalendarProvider,
  range: { desde: string; hasta: string },
  options?: { signal?: AbortSignal },
): Promise<CalendarEventosRangoResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const path = provider === "google" ? "/calendario/eventos-google" : "/calendario/eventos-outlook";
  const qs = new URLSearchParams({ desde: range.desde, hasta: range.hasta }).toString();
  let res: Response;
  try {
    res = await fetch(`${getApiBaseUrl()}${path}?${qs}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      signal: options?.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, `Respuesta inválida de ${path}.`, parsed);
  }
  const o = parsed as Record<string, unknown>;
  const reuniones = Array.isArray(o.reuniones) ? (o.reuniones as OutlookReunionApi[]) : [];
  const rango = o.rango && typeof o.rango === "object" ? (o.rango as { desde: string; hasta: string }) : null;
  const motivo = INCOMPLETE_REASONS.find((r) => r === o.motivo_incompleto) ?? null;
  return {
    total: typeof o.total === "number" ? o.total : reuniones.length,
    reuniones,
    mensaje: typeof o.mensaje === "string" ? o.mensaje : null,
    rango,
    completo: o.completo !== false,
    motivoIncompleto: motivo,
  };
}

/** Lista eventos de Google Calendar (JWT + tokens en servidor). */
export async function fetchGoogleCalendarEventos(options?: {
  top?: number;
  incluir_pasadas?: boolean;
}): Promise<CalendarEventosApiResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const sp = new URLSearchParams();
  if (options?.top != null) sp.set("top", String(options.top));
  if (options?.incluir_pasadas) sp.set("incluir_pasadas", "true");
  const qs = sp.toString();
  const pathUrl = `${getApiBaseUrl()}/calendario/eventos-google${qs ? `?${qs}` : ""}`;
  let res: Response;
  try {
    res = await fetch(pathUrl, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida de /calendario/eventos-google.", parsed);
  }
  const o = parsed as Record<string, unknown>;
  const reuniones = Array.isArray(o.reuniones) ? (o.reuniones as OutlookReunionApi[]) : [];
  const total = typeof o.total === "number" ? o.total : reuniones.length;
  const mensaje = o.mensaje === null || typeof o.mensaje === "string" ? (o.mensaje as string | null) : null;
  return { total, reuniones, mensaje };
}

/** Referencia a dossier guardado en Mis Dossiers. */
export type CalendarSavedDossierRef = {
  id: string;
  status: string;
  subject_name?: string;
};

/** Ítem de ``GET /calendario/generar-dossiers``. */
export type CalendarGenerarDossierItem = {
  reunion: OutlookReunionApi;
  /** Compatibilidad: primer dossier disponible (corporativo o persona). */
  dossier_generado: string;
  dossier_corporativo?: string | null;
  dossier_persona?: string | null;
  dossier_personas?: Array<{
    index?: number;
    full_name?: string;
    job_area?: string | null;
    country?: string | null;
    email?: string | null;
    md?: string | null;
    cache_hit?: boolean;
    error?: string | null;
  }>;
  corporate_skipped_plan_free?: boolean;
  saved_dossiers?: {
    corporate?: CalendarSavedDossierRef;
    person?: CalendarSavedDossierRef;
    persons?: CalendarSavedDossierRef[];
    folder?: { id: string; title: string };
  };
  parse?: {
    company?: string;
    company_subject?: string;
    company_corporate?: string;
    company_corporate_source?: "subject" | "description" | "";
    company_person?: string;
    persons?: Array<{
      index?: number;
      full_name?: string;
      job_area?: string | null;
      country?: string | null;
      email?: string | null;
    }>;
    person_name?: string;
    person_job?: string | null;
    person_country?: string | null;
  };
  errors?: string[];
  dossier_persona_research?: {
    warnings?: string[];
    profiles?: unknown[];
    profile_urls?: string[];
    filters_applied?: Record<string, unknown>;
    gemini_google_search_used?: boolean;
  };
};

export type CalendarGenerarDossiersResponse = {
  total: number;
  dossiers: CalendarGenerarDossierItem[];
  mensaje?: string;
};

/**
 * Genera dossier(es) con IA a partir del calendario Outlook (token Microsoft en servidor + JWT de la app).
 * Usa POST para evitar corrupción de ids largos de Graph en la URL.
 */
export async function fetchGenerarDossiersDesdeCalendario(options?: {
  eventId?: string;
  reunion?: OutlookReunionApi;
  top?: number;
}): Promise<CalendarGenerarDossiersResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const pathUrl = `${getApiBaseUrl()}/calendario/generar-dossiers-outlook`;
  let res: Response;
  try {
    res = await fetch(pathUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        event_id: options?.eventId ?? null,
        reunion: options?.reunion ?? null,
        top: options?.top ?? null,
      }),
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida de /calendario/generar-dossiers-outlook.", parsed);
  }
  const o = parsed as Record<string, unknown>;
  const dossiers = Array.isArray(o.dossiers) ? (o.dossiers as CalendarGenerarDossierItem[]) : [];
  const total = typeof o.total === "number" ? o.total : dossiers.length;
  const mensaje = typeof o.mensaje === "string" ? o.mensaje : undefined;
  return { total, dossiers, mensaje };
}

/** Alias con naming simétrico a ``fetchGenerarDossiersDesdeGoogleCalendar``. */
export const fetchGenerarDossiersDesdeOutlookCalendar = fetchGenerarDossiersDesdeCalendario;

/**
 * Genera dossier(es) con IA a partir de Google Calendar (token en servidor + JWT de la app).
 */
export async function fetchGenerarDossiersDesdeGoogleCalendar(options?: {
  eventId?: string;
  reunion?: OutlookReunionApi;
  top?: number;
}): Promise<CalendarGenerarDossiersResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const pathUrl = `${getApiBaseUrl()}/calendario/generar-dossiers-google`;
  let res: Response;
  try {
    res = await fetch(pathUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        event_id: options?.eventId ?? null,
        reunion: options?.reunion ?? null,
        top: options?.top ?? null,
      }),
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida de /calendario/generar-dossiers-google.", parsed);
  }
  const o = parsed as Record<string, unknown>;
  const dossiers = Array.isArray(o.dossiers) ? (o.dossiers as CalendarGenerarDossierItem[]) : [];
  const total = typeof o.total === "number" ? o.total : dossiers.length;
  const mensaje = typeof o.mensaje === "string" ? o.mensaje : undefined;
  return { total, dossiers, mensaje };
}

export type DossierGenerationJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type DossierGenerationJobApi = {
  id: string;
  status: DossierGenerationJobStatus;
  job_type: string;
  calendar_provider?: "microsoft" | "google" | null;
  external_event_id?: string | null;
  meeting_label?: string | null;
  credits_estimated?: number;
  credits_consumed?: number;
  error_message?: string | null;
  result?: CalendarGenerarDossierItem | PersonResearchApiResponse | CreateCorporateDossierResponse | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type EnqueueCalendarDossierResponse = {
  async?: boolean;
  job_id?: string;
  status?: DossierGenerationJobStatus;
  meeting_label?: string | null;
  credits_estimated?: number;
  mensaje?: string;
  total?: number;
  dossiers?: CalendarGenerarDossierItem[];
};

async function postCalendarGenerarDossiers(
  pathUrl: string,
  body: Record<string, unknown>,
): Promise<EnqueueCalendarDossierResponse> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  let res: Response;
  try {
    res = await fetch(pathUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new DossierApiError(502, "Respuesta inválida del servidor.", parsed);
  }
  const o = parsed as Record<string, unknown>;
  if (o.async === true || typeof o.job_id === "string") {
    return {
      async: true,
      job_id: String(o.job_id),
      status: (o.status as DossierGenerationJobStatus) || "queued",
      meeting_label: typeof o.meeting_label === "string" ? o.meeting_label : null,
      credits_estimated: typeof o.credits_estimated === "number" ? o.credits_estimated : 0,
      mensaje: typeof o.mensaje === "string" ? o.mensaje : undefined,
    };
  }
  const dossiers = Array.isArray(o.dossiers) ? (o.dossiers as CalendarGenerarDossierItem[]) : [];
  const total = typeof o.total === "number" ? o.total : dossiers.length;
  const mensaje = typeof o.mensaje === "string" ? o.mensaje : undefined;
  return { async: false, total, dossiers, mensaje };
}

/**
 * Encola generación asíncrona desde calendario Outlook (por defecto async_mode=true).
 */
export async function fetchEnqueueOutlookCalendarDossier(options?: {
  eventId?: string;
  reunion?: OutlookReunionApi;
  top?: number;
  depth?: "basic" | "standard" | "deep";
  output_language?: string;
}): Promise<EnqueueCalendarDossierResponse> {
  return postCalendarGenerarDossiers(`${getApiBaseUrl()}/calendario/generar-dossiers-outlook`, {
    event_id: options?.eventId ?? null,
    reunion: options?.reunion ?? null,
    top: options?.top ?? null,
    async_mode: true,
    depth: options?.depth ?? "standard",
    output_language: options?.output_language ?? null,
  });
}

export async function fetchEnqueueGoogleCalendarDossier(options?: {
  eventId?: string;
  reunion?: OutlookReunionApi;
  top?: number;
  depth?: "basic" | "standard" | "deep";
  output_language?: string;
}): Promise<EnqueueCalendarDossierResponse> {
  return postCalendarGenerarDossiers(`${getApiBaseUrl()}/calendario/generar-dossiers-google`, {
    event_id: options?.eventId ?? null,
    reunion: options?.reunion ?? null,
    top: options?.top ?? null,
    async_mode: true,
    depth: options?.depth ?? "standard",
    output_language: options?.output_language ?? null,
  });
}

export async function fetchDossierGenerationJobs(options?: {
  activeOnly?: boolean;
}): Promise<{ jobs: DossierGenerationJobApi[] }> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const params = new URLSearchParams();
  if (options?.activeOnly === false) {
    params.set("active_only", "false");
  }
  const qs = params.toString();
  const url = `${getApiBaseUrl()}/dossier-generation-jobs${qs ? `?${qs}` : ""}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  const o = parsed as { jobs?: DossierGenerationJobApi[] };
  return { jobs: Array.isArray(o.jobs) ? o.jobs : [] };
}

export async function fetchDossierGenerationJob(
  jobId: string,
): Promise<DossierGenerationJobApi> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/dossier-generation-jobs/${encodeURIComponent(jobId)}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as DossierGenerationJobApi;
}

export async function cancelDossierGenerationJob(
  jobId: string
): Promise<DossierGenerationJobApi> {
  return postJsonWithAuth<DossierGenerationJobApi>(
    `/dossier-generation-jobs/${jobId}/cancel`,
    {}
  );
}

export type CalendarAutomationStatus = {
  enabled: boolean;
  poll_seconds: number;
  advance_minutes: number;
  advance_minutes_stored?: number;
  advance_minutes_from_env?: boolean;
  server_default_minutes?: number;
  work_meetings_only?: boolean;
  skip_internal_meetings?: boolean;
  has_calendars?: boolean;
  scheduled_events: number;
  next_due: string | null;
  integrations?: {
    provider: string;
    email: string | null;
    is_enabled: boolean;
    advance_minutes: number;
    skip_internal_meetings?: boolean;
  }[];
};

export type CalendarAutomationSettingsPatch = {
  advance_minutes?: number;
  skip_internal_meetings?: boolean;
};

export async function fetchCalendarAutomationStatus(): Promise<CalendarAutomationStatus> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/calendario/automation/status`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as CalendarAutomationStatus;
}

export async function patchCalendarAutomationSettings(
  patch: CalendarAutomationSettingsPatch
): Promise<{
  advance_minutes_stored: number;
  advance_minutes_effective: number;
  advance_minutes_from_env: boolean;
  skip_internal_meetings?: boolean;
  events_rescheduled?: number;
  message: string;
}> {
  const token = getStoredAccessToken();
  if (!token) {
    throw new DossierApiError(401, "No hay sesión. Inicia sesión de nuevo.");
  }
  const url = `${getApiBaseUrl()}/calendario/automation/settings`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(patch),
    });
  } catch {
    throwFetchFailed();
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = { detail: text.slice(0, 500) };
  }
  if (!res.ok) {
    const msg = parseFastApiDetail(parsed) || res.statusText || "HTTP_ERROR";
    throw new DossierApiError(res.status, msg, parsed);
  }
  return parsed as {
    advance_minutes_stored: number;
    advance_minutes_effective: number;
    advance_minutes_from_env: boolean;
    events_rescheduled?: number;
    message: string;
  };
}
