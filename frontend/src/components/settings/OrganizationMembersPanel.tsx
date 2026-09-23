"use client";

import { useCallback, useEffect, useState } from "react";
import DashboardCard from "@/components/dashboard/DashboardCard";
import {
  createOrgInvite,
  DossierApiError,
  deleteOrgMember,
  fetchOrgInvites,
  fetchOrgMembersForManagement,
  getStoredAccessToken,
  patchOrgMemberRole,
  refreshAuthSession,
  revokeOrgInvite,
  type OrgInviteItem,
  type OrgMemberManageItem,
} from "@/lib/dossier-api";
import { invalidateAuthMeCache, notifyAuthMeChanged, setAuthMeCache } from "@/hooks/useAuthMe";
import { translateApiError } from "@/lib/translate-api-error";
import type { OrgRole } from "@/lib/org-role";
import { useTranslation } from "@/providers/PreferencesProvider";
import type { TranslationKey } from "@/i18n/types";
import type { TranslateFn } from "@/i18n";

function memberApiErrorMessage(err: unknown, t: TranslateFn): string {
  if (err instanceof DossierApiError) return translateApiError(err, t);
  return t("settings.members.load_error");
}

const ASSIGNABLE_ROLES: OrgRole[] = ["admin", "user", "viewer"];

const ROLE_LABEL_KEYS: Record<OrgRole, TranslationKey> = {
  admin: "settings.members.role_admin",
  user: "settings.members.role_user",
  viewer: "settings.members.role_viewer",
  api_user: "settings.members.role_user",
};

function formatJoinedAt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

function inviteStatusLabel(status: string, t: (k: TranslationKey) => string): string {
  if (status === "pending") return t("settings.members.invite_status_pending");
  if (status === "accepted") return t("settings.members.invite_status_accepted");
  if (status === "revoked") return t("settings.members.invite_status_revoked");
  if (status === "expired") return t("settings.members.invite_status_expired");
  return status;
}

export default function OrganizationMembersPanel() {
  const { t } = useTranslation();
  const [members, setMembers] = useState<OrgMemberManageItem[]>([]);
  const [invites, setInvites] = useState<OrgInviteItem[]>([]);
  const [orgDomain, setOrgDomain] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "user" | "viewer">("user");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionOk, setActionOk] = useState<string | null>(null);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!getStoredAccessToken()) {
      setLoading(false);
      setLoadError(t("settings.members.load_error"));
      return;
    }
    setLoadError(null);
    setLoading(true);
    try {
      const [membersRes, invitesRes] = await Promise.all([
        fetchOrgMembersForManagement(),
        fetchOrgInvites(),
      ]);
      setMembers(membersRes.items);
      setInvites(invitesRes.items);
      setOrgDomain(invitesRes.organization_domain);
    } catch (e) {
      setMembers([]);
      setInvites([]);
      setLoadError(memberApiErrorMessage(e, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load() es async y hace sus propios setState tras el await; la llamada en si es sincrona pero solo dispara el trabajo, no cambia estado directamente.
    void load();
  }, [load]);

  async function handleRoleChange(member: OrgMemberManageItem, role: OrgRole) {
    if (busyUserId || member.role === role) return;
    setActionError(null);
    setActionOk(null);
    setBusyUserId(member.user_id);
    try {
      const updated = await patchOrgMemberRole(member.user_id, role);
      setMembers((prev) => prev.map((m) => (m.user_id === updated.user_id ? updated : m)));
      if (updated.is_self) {
        try {
          const session = await refreshAuthSession();
          setAuthMeCache(session.user);
          notifyAuthMeChanged();
        } catch {
          invalidateAuthMeCache();
          notifyAuthMeChanged();
        }
      }
    } catch (e) {
      setActionError(memberApiErrorMessage(e, t));
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleRemove(member: OrgMemberManageItem) {
    if (busyUserId || member.is_self) return;
    if (!window.confirm(t("settings.members.remove_confirm"))) return;
    setActionError(null);
    setActionOk(null);
    setBusyUserId(member.user_id);
    try {
      await deleteOrgMember(member.user_id);
      setMembers((prev) => prev.filter((m) => m.user_id !== member.user_id));
    } catch (e) {
      setActionError(memberApiErrorMessage(e, t));
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    const email = inviteEmail.trim().toLowerCase();
    if (!email || inviting) return;
    setActionError(null);
    setActionOk(null);
    setInviting(true);
    try {
      const created = await createOrgInvite({ email, role: inviteRole });
      setInvites((prev) => [created, ...prev]);
      setInviteEmail("");
      if (created.joined_immediately) {
        setActionOk(t("settings.members.invite_joined_immediately"));
        const membersRes = await fetchOrgMembersForManagement();
        setMembers(membersRes.items);
      } else {
        setActionOk(t("settings.members.invite_created"));
      }
    } catch (err) {
      setActionError(memberApiErrorMessage(err, t));
    } finally {
      setInviting(false);
    }
  }

  async function handleRevokeInvite(invite: OrgInviteItem) {
    if (busyUserId || invite.status !== "pending") return;
    setActionError(null);
    setActionOk(null);
    setBusyUserId(invite.id);
    try {
      await revokeOrgInvite(invite.id);
      setInvites((prev) =>
        prev.map((i) => (i.id === invite.id ? { ...i, status: "revoked", invite_url: null } : i))
      );
    } catch (e) {
      setActionError(memberApiErrorMessage(e, t));
    } finally {
      setBusyUserId(null);
    }
  }

  async function copyInviteUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedUrl(url);
      window.setTimeout(() => setCopiedUrl(null), 2000);
    } catch {
      setActionError(t("settings.members.copy_failed"));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <DashboardCard title={t("settings.members.invite_title")}>
        <p className="mb-4 text-sm" style={{ color: "var(--text-muted)" }}>
          {t("settings.members.invite_subtitle", { domain: orgDomain || "—" })}
        </p>

        <form onSubmit={(e) => void handleInvite(e)} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex flex-1 flex-col gap-1 text-sm">
            <span style={{ color: "var(--text-secondary)" }}>{t("settings.members.invite_email_label")}</span>
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder={
                orgDomain
                  ? t("settings.members.invite_email_placeholder_domain", { domain: orgDomain })
                  : t("settings.members.invite_email_placeholder")
              }
              required
              disabled={inviting}
              className="rounded-lg border px-3 py-2 text-sm outline-none"
              style={{
                borderColor: "var(--border-default)",
                backgroundColor: "var(--bg-input)",
                color: "var(--text-primary)",
              }}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm sm:w-44">
            <span style={{ color: "var(--text-secondary)" }}>{t("settings.members.col_role")}</span>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as "admin" | "user" | "viewer")}
              disabled={inviting}
              className="rounded-lg border px-2.5 py-2 text-sm outline-none"
              style={{
                borderColor: "var(--border-default)",
                backgroundColor: "var(--bg-input)",
                color: "var(--text-primary)",
              }}
            >
              {ASSIGNABLE_ROLES.map((role) => (
                <option key={role} value={role}>
                  {t(ROLE_LABEL_KEYS[role])}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={inviting || !inviteEmail.trim()}
            className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            style={{
              backgroundImage:
                "linear-gradient(135deg, var(--accent-from) 0%, var(--accent-to) 100%)",
            }}
          >
            {inviting ? t("settings.members.invite_sending") : t("settings.members.invite_button")}
          </button>
        </form>

        {invites.filter((i) => i.status === "pending" || i.status === "accepted").length > 0 ? (
          <ul className="mt-6 space-y-2">
            {invites
              .filter((i) => i.status === "pending" || i.status === "accepted")
              .map((invite) => (
                <li
                  key={invite.id}
                  className="flex flex-col gap-2 rounded-lg border px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between"
                  style={{ borderColor: "var(--border-default)" }}
                >
                  <div>
                    <span style={{ color: "var(--text-primary)" }}>{invite.email}</span>
                    <span className="ml-2 text-xs" style={{ color: "var(--text-subtle)" }}>
                      {t(ROLE_LABEL_KEYS[normalizeRole(invite.role)])} ·{" "}
                      {inviteStatusLabel(invite.status, t)}
                      {invite.joined_immediately ? ` · ${t("settings.members.joined_direct")}` : ""}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {invite.invite_url ? (
                      <button
                        type="button"
                        onClick={() => void copyInviteUrl(invite.invite_url!)}
                        className="text-xs font-medium underline"
                        style={{ color: "var(--accent-from)" }}
                      >
                        {copiedUrl === invite.invite_url
                          ? t("settings.members.copied")
                          : t("settings.members.copy_link")}
                      </button>
                    ) : null}
                    {invite.status === "pending" ? (
                      <button
                        type="button"
                        disabled={busyUserId === invite.id}
                        onClick={() => void handleRevokeInvite(invite)}
                        className="text-xs font-medium text-red-400 hover:text-red-300 disabled:opacity-50"
                      >
                        {t("settings.members.invite_revoke")}
                      </button>
                    ) : null}
                  </div>
                </li>
              ))}
          </ul>
        ) : null}
      </DashboardCard>

      <DashboardCard title={t("settings.members.title")}>
        <p className="mb-4 text-sm" style={{ color: "var(--text-muted)" }}>
          {t("settings.members.subtitle")}
        </p>

        {loadError ? (
          <p className="text-sm" style={{ color: "var(--accent-danger, #f87171)" }}>
            {loadError}
          </p>
        ) : null}
        {actionError ? (
          <p className="text-sm" style={{ color: "var(--accent-danger, #f87171)" }}>
            {actionError}
          </p>
        ) : null}
        {actionOk ? (
          <p className="mb-3 text-sm" style={{ color: "var(--accent-from)" }}>
            {actionOk}
          </p>
        ) : null}

        {loading && members.length === 0 && !loadError ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            {t("billing.loading")}
          </p>
        ) : null}

        {members.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--border-default)" }}>
                  <th className="pb-2 pr-3 font-medium" style={{ color: "var(--text-muted)" }}>
                    {t("settings.members.col_member")}
                  </th>
                  <th className="pb-2 pr-3 font-medium" style={{ color: "var(--text-muted)" }}>
                    {t("settings.members.col_role")}
                  </th>
                  <th className="pb-2 pr-3 font-medium" style={{ color: "var(--text-muted)" }}>
                    {t("settings.members.col_joined")}
                  </th>
                  <th className="pb-2 font-medium" style={{ color: "var(--text-muted)" }}>
                    {t("settings.members.col_actions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => {
                  const displayName = (member.full_name || member.email).trim();
                  const isBusy = busyUserId === member.user_id;
                  return (
                    <tr
                      key={member.user_id}
                      className="border-b last:border-b-0"
                      style={{ borderColor: "var(--border-default)" }}
                    >
                      <td className="py-3 pr-3">
                        <div className="font-medium" style={{ color: "var(--text-primary)" }}>
                          {displayName}
                          {member.is_self ? (
                            <span
                              className="ml-2 text-xs font-normal"
                              style={{ color: "var(--text-subtle)" }}
                            >
                              ({t("settings.members.you")})
                            </span>
                          ) : null}
                        </div>
                        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                          {member.email}
                        </div>
                      </td>
                      <td className="py-3 pr-3">
                        <select
                          value={member.role}
                          disabled={isBusy}
                          onChange={(e) =>
                            void handleRoleChange(member, e.target.value as OrgRole)
                          }
                          className="rounded-lg border px-2.5 py-1.5 text-sm outline-none disabled:opacity-50"
                          style={{
                            borderColor: "var(--border-default)",
                            backgroundColor: "var(--bg-input)",
                            color: "var(--text-primary)",
                          }}
                          aria-label={t("settings.members.col_role")}
                        >
                          {ASSIGNABLE_ROLES.map((role) => (
                            <option key={role} value={role}>
                              {t(ROLE_LABEL_KEYS[role])}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td
                        className="py-3 pr-3 tabular-nums text-xs"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {formatJoinedAt(member.joined_at)}
                      </td>
                      <td className="py-3">
                        {member.is_self ? (
                          <span className="text-xs" style={{ color: "var(--text-subtle)" }}>
                            —
                          </span>
                        ) : (
                          <button
                            type="button"
                            disabled={isBusy}
                            onClick={() => void handleRemove(member)}
                            className="text-xs font-medium text-red-400 hover:text-red-300 disabled:opacity-50"
                          >
                            {isBusy ? t("settings.members.removing") : t("settings.members.remove")}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        {!loading && members.length === 0 && !loadError ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            {t("settings.members.empty")}
          </p>
        ) : null}
      </DashboardCard>
    </div>
  );
}

function normalizeRole(role: string): OrgRole {
  const r = role.trim().toLowerCase();
  if (r === "admin" || r === "user" || r === "viewer" || r === "api_user") return r;
  return "user";
}
