"use client";

import StatCard from "@/components/dashboard/StatCard";
import { buildKpiCards, type KpiStatus } from "@/lib/dashboard-kpis";
import type { DashboardSummary } from "@/lib/dossier-api";
import { useTranslation } from "@/providers/PreferencesProvider";

type Props = {
  summary: DashboardSummary | null;
  status: KpiStatus;
  /** Saldo ya conocido por otra vía si la consulta del resumen falló. */
  fallbackCredits?: { balance?: number | null; limit?: number | null } | null;
};

/**
 * Las cuatro tarjetas de Resumen: reuniones por preparar, cobertura de próximas reuniones,
 * créditos para preparar y créditos disponibles. Solo informativas: sin enlaces ni acciones.
 */
export default function OverviewKpiCards({ summary, status, fallbackCredits }: Props) {
  const { t, locale } = useTranslation();
  const cards = buildKpiCards({
    summary,
    status,
    t,
    locale,
    fallbackCredits,
  });
  return (
    <section className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((c) => (
        <StatCard
          key={c.id}
          value={c.value}
          label={c.label}
          details={c.details}
          trend={c.trend}
          description={c.description}
          trendVariant={c.trendVariant}
          busy={c.busy}
        />
      ))}
    </section>
  );
}
