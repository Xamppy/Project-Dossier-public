"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DossierApiError,
  createDossierShare,
  deleteDossierShare,
  fetchOrgMembers,
  type DossierShareItem,
  type OrgMemberItem,
} from "@/lib/dossier-api";
import { useTranslation } from "@/providers/PreferencesProvider";

type Props = {
  dossierId: string;
  initialShares: DossierShareItem[];
  onSharesChange?: (shares: DossierShareItem[]) => void;
};

export default function ShareDossierPanel({ dossierId, initialShares, onSharesChange }: Props) {
  const { t } = useTranslation();
  const [shares, setShares] = useState(initialShares);
  const [members, setMembers] = useState<OrgMemberItem[]>([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [loadingMembers, setLoadingMembers] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sincroniza el estado local con el prop initialShares cuando el padre lo actualiza.
    setShares(initialShares);
  }, [initialShares]);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marca el inicio de la carga antes del fetch async que sigue en el mismo efecto.
    setLoadingMembers(true);
    void fetchOrgMembers()
      .then((res) => {
        if (!cancelled) setMembers(res.items);
      })
      .catch(() => {
        if (!cancelled) setMembers([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingMembers(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sharedIds = useMemo(() => new Set(shares.map((s) => s.user_id)), [shares]);

  const availableMembers = useMemo(
    () => members.filter((m) => !sharedIds.has(m.user_id)),
    [members, sharedIds]
  );

  const updateShares = useCallback(
    (next: DossierShareItem[]) => {
      setShares(next);
      onSharesChange?.(next);
    },
    [onSharesChange]
  );

  async function handleShare() {
    if (!selectedUserId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await createDossierShare(dossierId, selectedUserId);
      updateShares(res.items);
      setSelectedUserId("");
    } catch (e) {
      setError(e instanceof DossierApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleUnshare(userId: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteDossierShare(dossierId, userId);
      updateShares(shares.filter((s) => s.user_id !== userId));
    } catch (e) {
      setError(e instanceof DossierApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="rounded-xl border px-4 py-4"
      style={{
        borderColor: "var(--border-default)",
        backgroundColor: "var(--bg-surface)",
      }}
    >
      <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
        {t("dossiers.share_title")}
      </h3>
      <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
        {t("dossiers.share_hint")}
      </p>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-sm">
          <span style={{ color: "var(--text-secondary)" }}>{t("dossiers.share_add_label")}</span>
          <select
            value={selectedUserId}
            onChange={(e) => setSelectedUserId(e.target.value)}
            disabled={loadingMembers || busy || availableMembers.length === 0}
            className="rounded-lg border px-3 py-2 text-sm outline-none"
            style={{
              borderColor: "var(--border-default)",
              backgroundColor: "var(--bg-input)",
              color: "var(--text-primary)",
            }}
          >
            <option value="">
              {loadingMembers
                ? t("common.loading")
                : availableMembers.length === 0
                  ? t("dossiers.share_no_members")
                  : t("dossiers.share_select_member")}
            </option>
            {availableMembers.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {(m.full_name || m.email).trim()} ({m.role})
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!selectedUserId || busy}
          onClick={() => void handleShare()}
          className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          style={{
            backgroundImage:
              "linear-gradient(135deg, var(--accent-from) 0%, var(--accent-to) 100%)",
          }}
        >
          {busy ? t("dossiers.share_saving") : t("dossiers.share_add_button")}
        </button>
      </div>

      {shares.length > 0 ? (
        <ul className="mt-4 space-y-2">
          {shares.map((s) => (
            <li
              key={s.user_id}
              className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border-default)" }}
            >
              <span style={{ color: "var(--text-primary)" }}>
                {(s.full_name || s.email).trim()}
                <span className="ml-2 text-xs" style={{ color: "var(--text-subtle)" }}>
                  {s.email}
                </span>
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleUnshare(s.user_id)}
                className="text-xs font-medium text-red-400 hover:text-red-300 disabled:opacity-50"
              >
                {t("dossiers.share_remove")}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-xs" style={{ color: "var(--text-subtle)" }}>
          {t("dossiers.share_empty")}
        </p>
      )}

      {error ? (
        <p className="mt-3 text-xs text-red-400" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
