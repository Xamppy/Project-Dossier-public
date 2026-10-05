"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import DashboardCard from "@/components/dashboard/DashboardCard";
import {
  acceptOrgInvite,
  DossierApiError,
  fetchMyPendingInvites,
  getStoredAccessToken,
  persistAuthToken,
  type OrgInvitePreview,
  writeDossierUserPreview,
} from "@/lib/dossier-api";
import { notifyAuthMeChanged, setAuthMeCache } from "@/hooks/useAuthMe";
import { useTranslation } from "@/providers/PreferencesProvider";

export default function PendingOrgInvitesPanel() {
  const { t } = useTranslation();
  const router = useRouter();
  const [items, setItems] = useState<OrgInvitePreview[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyToken, setBusyToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!getStoredAccessToken()) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await fetchMyPendingInvites();
      setItems(res.items.filter((i) => i.valid));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load() es async y hace sus propios setState tras el await; la llamada en si es sincrona pero solo dispara el trabajo, no cambia estado directamente.
    void load();
  }, [load]);

  if (loading || items.length === 0) return null;

  async function handleAccept(invite: OrgInvitePreview) {
    const token = invite.token;
    if (!token || busyToken) return;
    setError(null);
    setBusyToken(token);
    try {
      const data = await acceptOrgInvite(token);
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
      setAuthMeCache(data.user);
      notifyAuthMeChanged();
      router.refresh();
      router.push("/dashboard");
    } catch (e) {
      setError(e instanceof DossierApiError ? e.message : t("settings.members.load_error"));
    } finally {
      setBusyToken(null);
    }
  }

  return (
    <DashboardCard title={t("settings.members.pending_title")} className="mb-6">
      <p className="mb-4 text-sm" style={{ color: "var(--text-muted)" }}>
        {t("settings.members.pending_subtitle")}
      </p>
      {error ? (
        <p className="mb-3 text-sm" style={{ color: "var(--accent-danger, #f87171)" }}>
          {error}
        </p>
      ) : null}
      <ul className="space-y-3">
        {items.map((invite) => (
          <li
            key={invite.token || invite.organization_id}
            className="flex flex-col gap-2 rounded-lg border px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
            style={{ borderColor: "var(--border-default)" }}
          >
            <div>
              <p className="font-medium" style={{ color: "var(--text-primary)" }}>
                {invite.organization_name}
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {t("settings.members.pending_role", { role: invite.role })} · @{invite.email_domain}
              </p>
            </div>
            <button
              type="button"
              disabled={busyToken === invite.token}
              onClick={() => void handleAccept(invite)}
              className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              style={{
                backgroundImage:
                  "linear-gradient(135deg, var(--accent-from) 0%, var(--accent-to) 100%)",
              }}
            >
              {busyToken === invite.token
                ? t("settings.members.pending_accepting")
                : t("settings.members.pending_accept")}
            </button>
          </li>
        ))}
      </ul>
    </DashboardCard>
  );
}
