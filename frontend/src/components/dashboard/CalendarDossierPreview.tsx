"use client";

import Link from "next/link";
import { useTranslation } from "@/providers/PreferencesProvider";
import type { CalendarSavedDossierRef } from "@/lib/dossier-api";

type CalendarPersonPreview = {
  name: string;
  body: string | null;
  saved?: CalendarSavedDossierRef;
};

type CalendarDossierPreviewProps = {
  eventKey: string;
  activeEventKey: string;
  tema: string;
  corporate?: string | null;
  person?: string | null;
  persons?: CalendarPersonPreview[];
  lushaWarnings?: string[];
  savedCorporate?: CalendarSavedDossierRef;
  savedPerson?: CalendarSavedDossierRef;
  savedFolder?: { id: string; title: string };
  corporateSkippedFreePlan?: boolean;
};

function DossierBlock({
  label,
  body,
  emptyLabel,
  saved,
  viewLabel,
}: {
  label: string;
  body: string | null | undefined;
  emptyLabel: string;
  saved?: CalendarSavedDossierRef;
  viewLabel: string;
}) {
  if (!body?.trim()) {
    return (
      <p className="mt-2 text-xs italic" style={{ color: "var(--text-subtle)" }}>
        {emptyLabel}
      </p>
    );
  }
  return (
    <details
      className="mt-2 rounded-md border px-2 py-2"
      style={{ borderColor: "var(--border-default)" }}
      open
    >
      <summary className="cursor-pointer text-xs font-medium" style={{ color: "var(--accent-from)" }}>
        {label}
        {saved?.id ? (
          <span className="ml-2 font-normal" style={{ color: "var(--text-muted)" }}>
            — {viewLabel}
          </span>
        ) : null}
      </summary>
      {saved?.id ? (
        <Link
          href={`/dashboard/dossiers/${saved.id}`}
          className="mt-2 inline-block text-xs font-semibold underline-offset-2 hover:underline"
          style={{ color: "var(--accent-from)" }}
        >
          {viewLabel}
        </Link>
      ) : null}
      <pre
        className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded p-2 text-xs leading-relaxed"
        style={{
          backgroundColor: "var(--bg-surface-strong)",
          color: "var(--text-muted)",
        }}
      >
        {body}
      </pre>
    </details>
  );
}

/** Vista previa separada: dossier empresa y dossier persona. */
export default function CalendarDossierPreview({
  eventKey,
  activeEventKey,
  tema,
  corporate,
  person,
  persons,
  lushaWarnings,
  savedCorporate,
  savedPerson,
  savedFolder,
  corporateSkippedFreePlan,
}: CalendarDossierPreviewProps) {
  const { t } = useTranslation();
  if (activeEventKey !== eventKey) return null;

  const personBlocks: CalendarPersonPreview[] =
    persons && persons.length > 0
      ? persons
      : person?.trim()
        ? [{ name: t("overview.calendar_dossier_person"), body: person, saved: savedPerson }]
        : [];

  const hasSaved =
    savedCorporate?.id || savedPerson?.id || personBlocks.some((p) => p.saved?.id);

  return (
    <div className="mt-3 space-y-1">
      <p className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>
        {t("overview.calendar_dossiers_title")} — {tema}
      </p>
      {hasSaved ? (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {t("overview.calendar_dossiers_saved")}{" "}
          {savedFolder?.id ? (
            <Link
              href={`/dashboard/dossiers/folder/${savedFolder.id}`}
              className="font-semibold underline-offset-2 hover:underline"
              style={{ color: "var(--accent-from)" }}
            >
              {t("dossiers.folder_open")}
            </Link>
          ) : (
            <Link
              href="/dashboard/dossiers"
              className="font-semibold underline-offset-2 hover:underline"
              style={{ color: "var(--accent-from)" }}
            >
              {t("overview.calendar_dossiers_open_list")}
            </Link>
          )}
        </p>
      ) : null}
      {lushaWarnings && lushaWarnings.length > 0 ? (
        <div
          className="mt-2 rounded-md border px-2 py-2 text-xs leading-relaxed"
          style={{
            borderColor: "var(--border-default)",
            backgroundColor: "var(--bg-surface-strong)",
            color: "var(--text-muted)",
          }}
        >
          <p className="font-medium" style={{ color: "var(--text-primary)" }}>
            {t("overview.calendar_enrichment_diagnostics")}
          </p>
          <ul className="mt-1 list-disc pl-4">
            {lushaWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <DossierBlock
        label={t("overview.calendar_dossier_corporate")}
        body={corporate}
        emptyLabel={
          corporateSkippedFreePlan
            ? t("overview.calendar_dossier_corporate_free_plan")
            : t("overview.calendar_dossier_corporate_empty")
        }
        saved={savedCorporate}
        viewLabel={t("overview.calendar_dossier_view_saved")}
      />
      {personBlocks.length > 0 ? (
        personBlocks.map((p, i) => (
          <DossierBlock
            key={`${p.name}-${i}`}
            label={p.name}
            body={p.body}
            emptyLabel={persons?.length ? `${p.name}: ${t("overview.calendar_dossier_person_empty")}` : t("overview.calendar_dossier_person_empty")}
            saved={p.saved}
            viewLabel={t("overview.calendar_dossier_view_saved")}
          />
        ))
      ) : (
        <DossierBlock
          label={t("overview.calendar_dossier_person")}
          body={null}
          emptyLabel={t("overview.calendar_dossier_person_empty")}
          saved={savedPerson}
          viewLabel={t("overview.calendar_dossier_view_saved")}
        />
      )}
    </div>
  );
}
