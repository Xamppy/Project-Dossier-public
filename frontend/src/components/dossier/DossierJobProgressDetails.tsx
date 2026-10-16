"use client";

/**
 * Avance de un job por scopes (S5.4): las búsquedas de la empresa y, por
 * separado, cada persona investigada (un scope por asistente en Calendario).
 * Lo usan el detalle de la reunión (variante completa) y sus avisos (compacta).
 * Sin progreso (jobs anteriores a S5.4) no pinta nada: se ven como antes.
 */
import type { DossierJobProgressSnapshot } from "@/lib/dossier-api";
import { useTranslation } from "@/providers/PreferencesProvider";
import DossierAgentProgress from "@/components/dossier/DossierAgentProgress";
import PersonResearchProgress from "@/components/person-research/PersonResearchProgress";
import PersonResearchPartialResults from "@/components/person-research/PersonResearchPartialResults";

type Props = {
  progress: DossierJobProgressSnapshot | null | undefined;
  variant?: "full" | "compact";
  /** Vistas previas provisionales; al terminar las reemplaza el dossier guardado. */
  showPreviews?: boolean;
};

export default function DossierJobProgressDetails({ progress, variant = "full", showPreviews = false }: Props) {
  const { t } = useTranslation();
  if (!progress || progress.scopes.length === 0) return null;
  const compact = variant === "compact";
  const corporate = progress.scopes.filter((s) => s.kind === "corporate");
  const people = progress.scopes.filter((s) => s.kind === "person");

  return (
    <div className={compact ? "" : "space-y-3"}>
      {corporate.map((scope) =>
        scope.kind === "corporate" ? (
          <DossierAgentProgress key={scope.scope_id} scope={scope} variant={variant} showPreviews={showPreviews} />
        ) : null,
      )}
      {people.length > 0 ? (
        <section aria-label={t("progress.people_title")} className={compact ? "mt-1.5" : ""}>
          {compact ? null : (
            <h4 className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
              {t("progress.people_title")}
            </h4>
          )}
          {people.map((scope, index) => {
            if (scope.kind !== "person") return null;
            if (compact) return <PersonResearchProgress key={scope.scope_id} scope={scope} variant="compact" />;
            const name = scope.label ?? t("progress.unnamed_person", { index: index + 1 });
            return (
              <article
                key={scope.scope_id}
                aria-label={name}
                className="mt-2 rounded-md border p-2.5"
                style={{ borderColor: "var(--border-default)" }}
              >
                <p className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                  {name}
                </p>
                <PersonResearchProgress scope={scope} />
                {showPreviews ? <PersonResearchPartialResults scope={scope} /> : null}
              </article>
            );
          })}
        </section>
      ) : null}
    </div>
  );
}
