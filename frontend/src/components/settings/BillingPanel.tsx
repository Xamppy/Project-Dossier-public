"use client";

import { useCallback, useEffect, useState } from "react";
import DashboardCard from "@/components/dashboard/DashboardCard";
import { usePreferences } from "@/providers/PreferencesProvider";
import type { TranslationKey } from "@/i18n/types";
import {
  DossierApiError,
  fetchAuthMe,
  getStoredAccessToken,
  patchOrganizationPlan,
  type AuthUser,
} from "@/lib/dossier-api";
import { PLANS, type PlanTier } from "@/lib/plans";

const PLAN_NAME_KEYS: Record<PlanTier, TranslationKey> = {
  free: "billing.plan_free_name",
  pro: "billing.plan_pro_name",
  enterprise: "billing.plan_enterprise_name",
};

const PLAN_PRICE_KEYS: Record<PlanTier, TranslationKey> = {
  free: "billing.plan_free_price",
  pro: "billing.plan_pro_price",
  enterprise: "billing.plan_enterprise_price",
};

const PLAN_CREDITS_KEYS: Record<PlanTier, TranslationKey> = {
  free: "billing.plan_free_credits",
  pro: "billing.plan_pro_credits",
  enterprise: "billing.plan_enterprise_credits",
};

const PLAN_FEATURE_KEYS: Record<PlanTier, TranslationKey[]> = {
  free: [
    "billing.free_features_0",
    "billing.free_features_1",
    "billing.free_features_2",
  ],
  pro: [
    "billing.pro_features_0",
    "billing.pro_features_1",
    "billing.pro_features_2",
  ],
  enterprise: [
    "billing.enterprise_features_0",
    "billing.enterprise_features_1",
    "billing.enterprise_features_2",
  ],
};

function isUnlimitedMonthly(limit: number): boolean {
  return limit >= 999_999;
}

export default function BillingPanel() {
  const { t } = usePreferences();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingPlan, setSavingPlan] = useState<PlanTier | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!getStoredAccessToken()) {
      setLoading(false);
      setLoadError(t("billing.load_error"));
      return;
    }
    setLoadError(null);
    setLoading(true);
    try {
      const u = await fetchAuthMe();
      setMe(u);
    } catch (e) {
      setMe(null);
      setLoadError(e instanceof DossierApiError ? e.message : t("billing.load_error"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load() es async y hace sus propios setState tras el await; la llamada en si es sincrona pero solo dispara el trabajo, no cambia estado directamente.
    void load();
  }, [load]);

  async function handleSelectPlan(plan: PlanTier) {
    const active = (me?.organization_plan as PlanTier | undefined) ?? "free";
    if (!me || me.role !== "admin" || plan === active) return;
    setActionError(null);
    setSavingPlan(plan);
    try {
      const updated = await patchOrganizationPlan({ plan });
      setMe(updated);
    } catch (e) {
      setActionError(e instanceof DossierApiError ? e.message : t("billing.load_error"));
    } finally {
      setSavingPlan(null);
    }
  }

  const currentPlan = (me?.organization_plan as PlanTier | undefined) ?? "free";
  const isAdmin = me?.role === "admin";
  const balance = me?.credits_balance ?? 0;
  const monthly = me?.credits_monthly_limit ?? 0;
  const capLabel = isUnlimitedMonthly(monthly) ? t("billing.unlimited") : String(monthly);
  const usagePercent =
    monthly > 0 && !isUnlimitedMonthly(monthly)
      ? Math.min(100, Math.round((balance / monthly) * 100))
      : 0;

  return (
    <div className="flex flex-col gap-6">
      <DashboardCard title={t("billing.usage_title")}>
        <div className="flex flex-col gap-4">
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

          {loading && !me && !loadError ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              {t("billing.loading")}
            </p>
          ) : null}

          {me ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                    {t("billing.current_plan")}
                  </p>
                  <p
                    className="text-xl font-bold capitalize"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {t(PLAN_NAME_KEYS[currentPlan])}
                  </p>
                </div>
              </div>

              <div>
                <div className="mb-2 flex justify-between text-sm">
                  <span style={{ color: "var(--text-muted)" }}>{t("billing.wallet_balance")}</span>
                  <span style={{ color: "var(--text-primary)" }} className="tabular-nums font-medium">
                    {balance}
                  </span>
                </div>
                <div className="mb-2 flex justify-between text-sm">
                  <span style={{ color: "var(--text-muted)" }}>{t("billing.monthly_cap")}</span>
                  <span style={{ color: "var(--text-primary)" }} className="tabular-nums font-medium">
                    {capLabel}
                  </span>
                </div>
                {!isUnlimitedMonthly(monthly) ? (
                  <div
                    className="h-2 overflow-hidden rounded-full"
                    style={{ backgroundColor: "var(--bg-surface-strong)" }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${usagePercent}%`,
                        backgroundImage:
                          usagePercent < 20
                            ? "linear-gradient(90deg, #fbbf24, #ef4444)"
                            : "linear-gradient(90deg, var(--accent-from), var(--accent-to))",
                      }}
                    />
                  </div>
                ) : null}
                <p className="mt-2 text-xs" style={{ color: "var(--text-subtle)" }}>
                  {t("billing.credits_hint")}
                </p>
                <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
                  {isAdmin ? t("billing.plan_note") : t("billing.org_plan_member_note")}
                </p>
              </div>
            </>
          ) : null}
        </div>
      </DashboardCard>

      {!isAdmin && me ? (
        <p
          className="rounded-lg border px-4 py-3 text-sm"
          style={{
            borderColor: "var(--border-default)",
            color: "var(--text-muted)",
            backgroundColor: "var(--bg-surface)",
          }}
        >
          {t("billing.not_admin")}
        </p>
      ) : null}

      {isAdmin ? (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {PLANS.map((plan) => {
          const isCurrentPlan = plan.id === currentPlan;
          return (
          <div
            key={plan.id}
            className="flex flex-col gap-4 rounded-xl border p-5"
            style={{
              borderColor: isCurrentPlan ? "var(--accent-from)" : "var(--border-default)",
              backgroundImage:
                "linear-gradient(180deg, var(--bg-card-start) 0%, var(--bg-card-end) 100%)",
              boxShadow: isCurrentPlan ? "0 0 0 1px rgba(59, 130, 246, 0.25)" : undefined,
            }}
          >
            <div>
              <h4 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                {t(PLAN_NAME_KEYS[plan.id])}
              </h4>
              <p className="text-sm" style={{ color: "var(--accent-from)" }}>
                {t(PLAN_PRICE_KEYS[plan.id])}
              </p>
              <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
                {t(PLAN_CREDITS_KEYS[plan.id])}
              </p>
            </div>
            <ul className="flex flex-1 flex-col gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
              {PLAN_FEATURE_KEYS[plan.id].map((key) => (
                <li key={key} className="flex items-start gap-2">
                  <span style={{ color: "#34d399" }}>✓</span>
                  {t(key)}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="rounded-lg px-4 py-2 text-sm font-semibold transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
              style={
                plan.id === currentPlan
                  ? {
                      border: "1px solid var(--border-default)",
                      color: "var(--text-muted)",
                      backgroundColor: "var(--bg-surface)",
                    }
                  : {
                      color: "white",
                      backgroundImage:
                        "linear-gradient(135deg, var(--accent-from) 0%, var(--accent-to) 100%)",
                    }
              }
              disabled={plan.id === currentPlan || savingPlan !== null || !me}
              onClick={() => void handleSelectPlan(plan.id)}
            >
              {savingPlan === plan.id
                ? t("billing.saving")
                : plan.id === currentPlan
                  ? t("billing.current_plan_btn")
                  : t("billing.upgrade")}
            </button>
          </div>
          );
        })}
      </div>
      ) : null}
    </div>
  );
}
