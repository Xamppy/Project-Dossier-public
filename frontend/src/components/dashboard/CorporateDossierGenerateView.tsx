"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import DashboardCard from "@/components/dashboard/DashboardCard";
import TopBar from "@/components/dashboard/TopBar";
import FormField from "@/components/FormField";
import PrimaryButton from "@/components/PrimaryButton";
import {
  DossierApiError,
  fetchAuthMe,
  fetchCorporateCompanySearch,
  getStoredAccessToken,
  type AuthUser,
  type CorporateCompanyResolutionPayload,
  type CorporateCompanySearchResponse,
  type CreateCorporateDossierPayload,
} from "@/lib/dossier-api";
import {
  allowedDepthsForPlan,
  defaultDepthForPlan,
  normalizePlanTier,
  planSummaryLabel,
  type PlanTier,
} from "@/lib/plans";
import { DEPTH_OPTIONS, type DossierDepth } from "@/lib/dossier-depth";
import { resolveDossierOutputLanguage } from "@/lib/resolve-output-language";
import { translateApiErrorMessage, translateDossierStatusMessage } from "@/lib/translate-backend-message";
import { useDossierJobs } from "@/providers/DossierJobsProvider";
import { usePreferences, useTranslation } from "@/providers/PreferencesProvider";
import type { TranslationKey } from "@/i18n/types";

export type CorporateDossierGenerateViewProps = {
  initialQuery: string;
  autoDisambiguate: boolean;
  backHref: string;
  backLabelKey: TranslationKey;
  titleKey: TranslationKey;
  subtitleKey: TranslationKey;
};

const SCOPE_KEY_BY_DEPTH: Record<DossierDepth, TranslationKey> = {
  basic: "generate.scope_basic",
  standard: "generate.scope_standard",
  deep: "generate.scope_deep",
};

const WARN_I18N: Partial<Record<string, TranslationKey>> = {
  missing_companies_house_api_key: "generate.warn_missing_ch",
  companies_house_request_failed: "generate.warn_ch_http",
  sec_request_failed: "generate.warn_sec_http",
  query_too_short: "generate.warn_query_short",
};

function AutoFetchCompanySearch({
  query,
  onDone,
}: {
  query: string;
  onDone: (r: CorporateCompanySearchResponse) => void;
}) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchCorporateCompanySearch(query)
      .then((data) => {
        if (!cancelled) onDone(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [query, onDone]);

  if (failed) {
    return <p className="text-sm text-red-400">{t("generate.company_search_error")}</p>;
  }
  return (
    <p className="text-sm" style={{ color: "var(--text-muted)" }}>
      {t("generate.company_search_loading")}
    </p>
  );
}

export default function CorporateDossierGenerateView({
  initialQuery,
  autoDisambiguate,
  backHref,
  backLabelKey,
  titleKey,
  subtitleKey,
}: CorporateDossierGenerateViewProps) {
  const { t } = useTranslation();
  const { preferences } = usePreferences();
  const {
    enqueueCorporateDossierJob,
    cancelJob,
    getActiveCorporateJob,
    jobs,
  } = useDossierJobs();
  const [query, setQuery] = useState(initialQuery);
  const [email, setEmail] = useState("");
  const [me, setMe] = useState<AuthUser | null>(null);
  const plan: PlanTier = normalizePlanTier(me?.organization_plan);
  const allowedDepths = useMemo(() => allowedDepthsForPlan(plan), [plan]);
  const [depth, setDepth] = useState<DossierDepth>(defaultDepthForPlan("free"));
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const [searchResults, setSearchResults] = useState<CorporateCompanySearchResponse | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedResolution, setSelectedResolution] =
    useState<CorporateCompanyResolutionPayload | null>(null);
  const [companyConfirmed, setCompanyConfirmed] = useState(false);

  const handleAutoSearchDone = useCallback((r: CorporateCompanySearchResponse) => {
    setSearchResults(r);
    setSelectedResolution(null);
    setCompanyConfirmed(false);
  }, []);

  useEffect(() => {
    if (!getStoredAccessToken()) return;
    void fetchAuthMe()
      .then((u) => {
        setMe(u);
        const p = normalizePlanTier(u.organization_plan);
        setDepth((current) =>
          allowedDepthsForPlan(p).includes(current)
            ? current
            : defaultDepthForPlan(p),
        );
      })
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (!allowedDepths.includes(depth)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- corrige la profundidad seleccionada si dejo de ser valida para el plan actual.
      setDepth(defaultDepthForPlan(plan));
    }
  }, [allowedDepths, depth, plan]);

  async function runManualCompanySearch() {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setError(t("generate.error.query_min"));
      return;
    }
    if (!getStoredAccessToken()) {
      setError(t("generate.error.auth"));
      return;
    }
    setError("");
    setSearchLoading(true);
    setSelectedResolution(null);
    setCompanyConfirmed(false);
    try {
      const r = await fetchCorporateCompanySearch(trimmed);
      setSearchResults(r);
    } catch (e) {
      if (e instanceof DossierApiError) {
        setError(translateApiErrorMessage(e, t) || t("generate.error.api"));
      } else {
        setError(t("generate.error.api"));
      }
    } finally {
      setSearchLoading(false);
    }
  }

  const selectedDepth = DEPTH_OPTIONS.find((d) => d.id === depth)!;
  const activeJob =
    jobs.find((j) => j.id === activeJobId) ?? getActiveCorporateJob() ?? null;
  const isGenerating =
    activeJob?.status === "queued" || activeJob?.status === "running";

  useEffect(() => {
    if (!activeJobId) return;
    const job = jobs.find((j) => j.id === activeJobId);
    if (!job) return;
    if (job.status === "completed") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- sincroniza con el job rastreado por DossierJobsProvider (sistema externo).
      setActiveJobId(null);
    }
    if (job.status === "failed" || job.status === "cancelled") {
      setActiveJobId(null);
      if (job.status === "failed" && job.error_message) {
        setError(translateDossierStatusMessage(job.error_message, t) ?? job.error_message);
      }
    }
  }, [jobs, activeJobId, t]);

  function buildPayload(trimmed: string): CreateCorporateDossierPayload {
    return {
      subject_query: trimmed,
      subject_email: email.trim() || undefined,
      depth,
      resolution: selectedResolution ?? undefined,
      output_language: resolveDossierOutputLanguage(preferences),
    };
  }

  async function handleGenerate() {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setError(t("generate.error.query_min"));
      return;
    }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError(t("auth.error.email_invalid"));
      return;
    }
    if (!getStoredAccessToken()) {
      setError(t("generate.error.auth"));
      return;
    }
    if (isGenerating) {
      setError(t("corporate_page.already_generating"));
      return;
    }

    const totalHits =
      (searchResults?.uk.length ?? 0) + (searchResults?.us.length ?? 0);
    if (totalHits > 0) {
      if (!selectedResolution) {
        setError(t("generate.company_pick_required"));
        return;
      }
      if (!companyConfirmed) {
        setError(t("generate.company_confirm_required"));
        return;
      }
    }

    setError("");
    setSubmitting(true);
    try {
      const jobId = await enqueueCorporateDossierJob(
        buildPayload(trimmed),
        selectedResolution?.title?.trim() || trimmed,
        selectedDepth.credits,
      );
      setActiveJobId(jobId);
    } catch (e) {
      if (e instanceof DossierApiError) {
        if (e.status === 401) {
          setError(t("generate.error.auth"));
        } else {
          setError(translateApiErrorMessage(e, t) || t("generate.error.api"));
        }
      } else {
        setError(t("generate.error.api"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancelGeneration() {
    if (!activeJob?.id) return;
    setError("");
    try {
      await cancelJob(activeJob.id);
      setActiveJobId(null);
    } catch (err) {
      if (err instanceof DossierApiError) {
        setError(translateApiErrorMessage(err, t) || t("corporate_page.cancel_error"));
      } else {
        setError(t("corporate_page.cancel_error"));
      }
    }
  }

  return (
    <>
      <nav className="mb-6">
        <Link
          href={backHref}
          className="ui-person-back-link inline-flex items-center gap-1.5 text-sm"
          style={{ color: "var(--text-muted)" }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          {t(backLabelKey)}
        </Link>
      </nav>

      <TopBar title={t(titleKey)} subtitle={t(subtitleKey)} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5 lg:gap-5">
        <div className="lg:col-span-3">
          <DashboardCard title={t("generate.company_search_title")}>
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void handleGenerate();
              }}
            >
              <FormField
                label={t("generate.name_or_company")}
                name="query"
                placeholder={t("generate.name_placeholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                hint={t("generate.name_hint")}
                disabled={isGenerating}
              />

                <div className="flex justify-start">
                  <button
                    type="button"
                    aria-label={t("generate.company_search_btn_aria")}
                    className="ui-corporate-search-btn inline-flex max-w-full shrink-0 items-center justify-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                    style={{
                      borderColor: "var(--accent-from)",
                      color: "var(--accent-from)",
                      backgroundColor: "rgba(59, 130, 246, 0.08)",
                    }}
                    disabled={searchLoading || isGenerating || query.trim().length < 2}
                    onClick={() => void runManualCompanySearch()}
                  >
                    <svg
                      className="h-4 w-4 shrink-0 opacity-90"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <circle cx="11" cy="11" r="7" />
                      <path d="m21 21-4.3-4.3" />
                    </svg>
                    {searchLoading ? t("generate.company_search_loading") : t("generate.company_search_btn")}
                  </button>
                </div>

                {autoDisambiguate && query.trim().length >= 2 && searchResults === null && (
                  <AutoFetchCompanySearch query={query.trim()} onDone={handleAutoSearchDone} />
                )}

                {(searchLoading || searchResults) && (
                <div
                  className="flex flex-col gap-4 rounded-lg border p-5"
                  style={{ borderColor: "var(--border-default)" }}
                >
                  {!companyConfirmed ? (
                    <>
                      <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
                        {t("generate.company_pick_hint")}
                      </p>
                      {searchResults?.warnings?.length ? (
                        <ul className="ui-text-warning list-inside list-disc text-xs">
                          {searchResults.warnings.map((w) => {
                            const key = WARN_I18N[w];
                            return <li key={w}>{key ? t(key) : w}</li>;
                          })}
                        </ul>
                      ) : null}
                    </>
                  ) : null}
                  {searchResults && !companyConfirmed && (
                    <>
                      <div className="flex max-h-96 flex-col gap-4 overflow-y-auto pr-1 sm:max-h-[28rem]">
                        {searchResults.uk.length > 0 && (
                          <div>
                            <div
                              className="mb-3 flex items-center gap-2 border-b pb-2"
                              style={{ borderColor: "var(--border-default)" }}
                            >
                              <span
                                className="rounded-md px-2 py-1 text-xs font-bold uppercase tracking-wide text-white"
                                style={{ backgroundColor: "#1d4ed8" }}
                              >
                                {t("generate.country_tag_uk")}
                              </span>
                              <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                                {t("generate.company_search_uk")}
                              </span>
                            </div>
                            <ul className="flex flex-col gap-2">
                              {searchResults.uk.map((row) => {
                                const picked =
                                  selectedResolution?.source === "companies_house" &&
                                  selectedResolution.company_number === row.company_number;
                                return (
                                  <li key={row.company_number}>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setCompanyConfirmed(false);
                                        setSelectedResolution({
                                          source: "companies_house",
                                          title: row.title,
                                          company_number: row.company_number,
                                        });
                                      }}
                                      className={`ui-corporate-pick-btn w-full rounded-lg border p-3 text-left text-sm${picked ? " ui-corporate-pick-btn--picked" : ""}`}
                                      style={{
                                        borderColor: picked ? "var(--accent-from)" : "var(--border-default)",
                                        backgroundColor: picked ? "rgba(99,102,241,0.08)" : "transparent",
                                        color: "var(--text-primary)",
                                      }}
                                    >
                                      <div className="mb-2 flex items-center gap-2">
                                        <span
                                          className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase text-white"
                                          style={{ backgroundColor: "#2563eb" }}
                                        >
                                          {t("generate.country_tag_uk")}
                                        </span>
                                        <span
                                          className="text-[10px] font-medium uppercase tracking-wide"
                                          style={{ color: "var(--text-subtle)" }}
                                        >
                                          {t("generate.company_registry_ch")}
                                        </span>
                                      </div>
                                      <span className="font-medium">{row.title}</span>
                                      <span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>
                                        {row.company_number}
                                        {row.company_status ? ` · ${row.company_status}` : ""}
                                        {row.company_type ? ` · ${row.company_type}` : ""}
                                      </span>
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        )}
                        {searchResults.us.length > 0 && (
                          <div>
                            <div
                              className="mb-3 flex items-center gap-2 border-b pb-2"
                              style={{ borderColor: "var(--border-default)" }}
                            >
                              <span
                                className="rounded-md px-2 py-1 text-xs font-bold uppercase tracking-wide text-white"
                                style={{ backgroundColor: "#047857" }}
                              >
                                {t("generate.country_tag_usa")}
                              </span>
                              <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                                {t("generate.company_search_us")}
                              </span>
                            </div>
                            <ul className="flex flex-col gap-2">
                              {searchResults.us.map((row) => {
                                const picked =
                                  selectedResolution?.source === "sec_edgar" &&
                                  selectedResolution.ticker === row.ticker &&
                                  selectedResolution.cik === row.cik;
                                return (
                                  <li key={`${row.ticker}-${row.cik}`}>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setCompanyConfirmed(false);
                                        setSelectedResolution({
                                          source: "sec_edgar",
                                          title: row.title,
                                          ticker: row.ticker,
                                          cik: row.cik,
                                        });
                                      }}
                                      className={`ui-corporate-pick-btn w-full rounded-lg border p-3 text-left text-sm${picked ? " ui-corporate-pick-btn--picked" : ""}`}
                                      style={{
                                        borderColor: picked ? "var(--accent-from)" : "var(--border-default)",
                                        backgroundColor: picked ? "rgba(99,102,241,0.08)" : "transparent",
                                        color: "var(--text-primary)",
                                      }}
                                    >
                                      <div className="mb-2 flex items-center gap-2">
                                        <span
                                          className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase text-white"
                                          style={{ backgroundColor: "#059669" }}
                                        >
                                          {t("generate.country_tag_usa")}
                                        </span>
                                        <span
                                          className="text-[10px] font-medium uppercase tracking-wide"
                                          style={{ color: "var(--text-subtle)" }}
                                        >
                                          {t("generate.company_registry_sec")}
                                        </span>
                                      </div>
                                      <span className="font-medium">
                                        [{row.ticker}] {row.title}
                                      </span>
                                      <span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>
                                        CIK {row.cik}
                                      </span>
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        )}
                        {searchResults.uk.length === 0 && searchResults.us.length === 0 && (
                          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                            {t("generate.company_search_empty")}
                          </p>
                        )}
                      </div>
                      {selectedResolution && !companyConfirmed && (
                        <div
                          className="mt-3 flex flex-col gap-2 rounded-lg border p-3"
                          style={{ borderColor: "rgba(251,191,36,0.45)", backgroundColor: "rgba(251,191,36,0.06)" }}
                        >
                          <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
                            {t("generate.company_confirm_hint")}
                          </p>
                          <button
                            type="button"
                            className="ui-new-dossier-btn inline-flex items-center justify-center rounded-lg px-4 py-2.5 text-sm font-semibold text-white"
                            style={{
                              backgroundImage:
                                "linear-gradient(135deg, var(--accent-from) 0%, var(--accent-to) 100%)",
                              boxShadow: "0 10px 25px rgba(0, 183, 235, 0.22)",
                            }}
                            onClick={() => setCompanyConfirmed(true)}
                          >
                            {t("generate.company_confirm_btn")}
                          </button>
                        </div>
                      )}
                    </>
                  )}
                  {selectedResolution && companyConfirmed && (
                    <div
                      className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between"
                      style={{ borderColor: "rgba(52,211,153,0.45)", backgroundColor: "rgba(52,211,153,0.06)" }}
                    >
                      <div className="min-w-0">
                        <p className="ui-text-success text-xs font-semibold uppercase tracking-wide">
                          {t("generate.company_confirmed_title")}
                        </p>
                        <p className="truncate text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                          {selectedResolution.source === "companies_house" ? (
                            <span
                              className="mr-2 inline-flex rounded px-1.5 py-0.5 text-[10px] font-bold uppercase text-white"
                              style={{ backgroundColor: "#2563eb" }}
                            >
                              {t("generate.country_tag_uk")}
                            </span>
                          ) : (
                            <span
                              className="mr-2 inline-flex rounded px-1.5 py-0.5 text-[10px] font-bold uppercase text-white"
                              style={{ backgroundColor: "#059669" }}
                            >
                              {t("generate.country_tag_usa")}
                            </span>
                          )}
                          {selectedResolution.title}
                          {selectedResolution.source === "companies_house" && selectedResolution.company_number
                            ? ` · ${selectedResolution.company_number}`
                            : null}
                          {selectedResolution.source === "sec_edgar" && selectedResolution.ticker
                            ? ` · ${selectedResolution.ticker} · CIK ${selectedResolution.cik}`
                            : null}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="ui-person-outline-btn shrink-0 px-3 py-2 text-xs font-medium"
                        onClick={() => {
                          setCompanyConfirmed(false);
                          setSelectedResolution(null);
                        }}
                      >
                        {t("generate.company_change")}
                      </button>
                    </div>
                  )}
                </div>
                )}

                <FormField
                  label={t("generate.email_optional")}
                  name="email"
                  type="email"
                  placeholder={t("generate.email_placeholder")}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isGenerating}
                />

                {error && <p className="text-sm text-red-400">{error}</p>}

                {isGenerating ? (
                  <div
                    className="rounded-lg border px-4 py-3 text-sm"
                    style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
                  >
                    <p className="font-medium" style={{ color: "var(--text-primary)" }}>
                      {t("corporate_page.generating_title", {
                        name: activeJob?.meeting_label || query.trim(),
                      })}
                    </p>
                    <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
                      {t("corporate_page.generating_background")}
                    </p>
                    <div
                      className="mt-3 h-1 w-full overflow-hidden rounded-full"
                      style={{ backgroundColor: "var(--border-default)" }}
                    >
                      <div
                        className="h-full w-1/3 animate-pulse rounded-full"
                        style={{ backgroundColor: "var(--accent-primary)" }}
                      />
                    </div>
                    <button
                      type="button"
                      className="ui-hover-danger mt-3 rounded-md px-2 py-1 text-xs font-medium transition"
                      style={{ color: "var(--status-error)" }}
                      onClick={() => void handleCancelGeneration()}
                    >
                      {t("person_research.cancel")}
                    </button>
                  </div>
                ) : (
                  <PrimaryButton type="submit" loading={submitting} className="ui-new-dossier-btn w-full sm:w-auto">
                    {selectedDepth.credits === 1
                      ? t("generate.submit_one")
                      : t("generate.submit", { credits: selectedDepth.credits })}
                  </PrimaryButton>
                )}
              </form>
          </DashboardCard>
        </div>

        <div className="flex flex-col gap-4 lg:col-span-2">
          <DashboardCard title={t("generate.summary")}>
            <dl className="flex flex-col gap-3 text-sm">
              <div className="flex justify-between gap-4">
                <dt style={{ color: "var(--text-muted)" }}>{t("generate.plan")}</dt>
                <dd style={{ color: "var(--text-primary)" }}>
                  {planSummaryLabel(
                    t,
                    plan,
                    me?.credits_balance,
                    me?.credits_monthly_limit,
                  )}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt style={{ color: "var(--text-muted)" }}>{t("generate.credits_cost")}</dt>
                <dd style={{ color: "var(--accent-from)" }}>{selectedDepth.credits}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt style={{ color: "var(--text-muted)" }}>{t("generate.eta")}</dt>
                <dd style={{ color: "var(--text-primary)" }}>~{selectedDepth.etaSeconds}s</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt style={{ color: "var(--text-muted)" }}>{t("generate.modules")}</dt>
                <dd className="max-w-[65%] text-right text-xs leading-snug" style={{ color: "var(--text-primary)" }}>
                  {t(SCOPE_KEY_BY_DEPTH[selectedDepth.id])}
                </dd>
              </div>
            </dl>
          </DashboardCard>
        </div>
      </div>
    </>
  );
}
