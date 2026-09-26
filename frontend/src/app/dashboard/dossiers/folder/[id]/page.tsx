"use client";

import Link from "next/link";
import { notFound, useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import CalendarMeetingLabel from "@/components/dossier/CalendarMeetingLabel";
import DossierFolderCard from "@/components/dossier/DossierFolderCard";
import UiAlert from "@/components/ui/UiAlert";
import {
  DossierApiError,
  deleteDossierFolderFromApi,
  deleteDossierFromApi,
  fetchDossierFolderById,
  type DossierFolderDetailResponse,
  type DossierListItem,
} from "@/lib/dossier-api";
import { getCalendarMeetingSubject } from "@/lib/calendar-dossier-meta";
import { removeDossierFromFolder } from "@/lib/dossier-list-utils";
import { stripHtmlToPlainLine } from "@/lib/strip-html";
import { useAuthMe } from "@/hooks/useAuthMe";
import { useTranslation } from "@/providers/PreferencesProvider";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default function DossierFolderPage() {
  const params = useParams();
  const router = useRouter();
  const folderId = typeof params?.id === "string" ? params.id : "";
  const { t } = useTranslation();
  const { canMutate } = useAuthMe();
  const [folder, setFolder] = useState<DossierFolderDetailResponse | null>(null);
  const [load, setLoad] = useState<"loading" | "ok" | "err">("loading");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletingFolder, setDeletingFolder] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!folderId || !UUID_RE.test(folderId)) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marca el inicio de la carga antes de lanzar el fetch async que sigue en el mismo efecto.
    setLoad("loading");
    void fetchDossierFolderById(folderId)
      .then((data) => {
        if (cancelled) return;
        setFolder(data);
        setLoad("ok");
      })
      .catch((e) => {
        if (cancelled) return;
        setFolder(null);
        setLoad("err");
        setError(e instanceof DossierApiError ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [folderId]);

  if (!folderId || !UUID_RE.test(folderId)) {
    notFound();
  }

  async function handleDeleteDossier(row: DossierListItem) {
    if (deletingId) return;
    if (!window.confirm(t("dossiers.delete_confirm"))) return;
    setDeletingId(row.id);
    setError(null);
    try {
      await deleteDossierFromApi(row.id);
      setFolder((prev) => {
        if (!prev) return prev;
        return removeDossierFromFolder(prev, row.id);
      });
    } catch (e) {
      setError(e instanceof DossierApiError ? e.message : String(e));
    } finally {
      setDeletingId(null);
    }
  }

  async function handleDeleteFolder() {
    if (deletingFolder || deletingId) return;
    if (!window.confirm(t("dossiers.delete_folder_confirm"))) return;
    setDeletingFolder(true);
    setError(null);
    try {
      await deleteDossierFolderFromApi(folderId);
      router.replace("/dashboard/dossiers");
    } catch (e) {
      setError(e instanceof DossierApiError ? e.message : String(e));
    } finally {
      setDeletingFolder(false);
    }
  }

  useEffect(() => {
    if (load === "ok" && folder === null) {
      router.replace("/dashboard/dossiers");
    }
  }, [folder, load, router]);

  if (load === "loading") {
    return (
      <div className="p-8 text-sm" style={{ color: "var(--text-muted)" }}>
        {t("dossiers.folder_loading")}
      </div>
    );
  }

  if (load === "err" || !folder) {
    if (load === "ok" && folder === null) {
      return (
        <div className="p-8 text-sm" style={{ color: "var(--text-muted)" }}>
          {t("dossiers.folder_loading")}
        </div>
      );
    }
    return (
      <div className="mx-auto max-w-lg space-y-4 p-8">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          {error || t("dossiers.folder_not_found")}
        </p>
        <Link
          href="/dashboard/dossiers"
          className="text-sm font-medium underline"
          style={{ color: "var(--accent-from)" }}
        >
          {t("detail.back")}
        </Link>
      </div>
    );
  }

  const displayTitle = stripHtmlToPlainLine(
    getCalendarMeetingSubject({
      calendar_meeting: folder.calendar_meeting,
      dossier_data: folder.dossiers[0]?.dossier_data,
    }) || folder.title
  );

  return (
    <div className="mx-auto max-w-5xl p-6">
      <nav className="mb-6">
        <Link
          href="/dashboard/dossiers"
          className="inline-flex items-center gap-1.5 text-sm transition hover:opacity-80"
          style={{ color: "var(--text-muted)" }}
        >
          ← {t("detail.back")}
        </Link>
      </nav>

      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--accent-from)" }}>
          📁 {t("dossiers.folder_label")}
        </p>
        <h1 className="mt-1 text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          {displayTitle || "—"}
        </h1>
        <CalendarMeetingLabel
          trigger_source={folder.trigger_source}
          calendar_meeting={folder.calendar_meeting}
          dossier_data={folder.dossiers[0]?.dossier_data}
        />
        {canMutate ? (
          <div className="mt-4">
            <button
              type="button"
              onClick={() => void handleDeleteFolder()}
              disabled={deletingFolder || Boolean(deletingId)}
              className="rounded-lg border px-3 py-2 text-sm font-medium transition hover:opacity-90 disabled:opacity-50"
              style={{
                borderColor: "var(--border-default)",
                color: "var(--text-muted)",
              }}
            >
              {deletingFolder ? t("dossiers.deleting") : t("dossiers.delete_folder")}
            </button>
          </div>
        ) : null}
      </header>

      {error ? (
        <UiAlert variant="warning" className="mb-4">
          {error}
        </UiAlert>
      ) : null}

      <DossierFolderCard
        folder={folder}
        typeFilter="all"
        deletingId={deletingId}
        onDeleteDossier={handleDeleteDossier}
        showDelete={canMutate}
      />
    </div>
  );
}
