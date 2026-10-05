"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/dashboard/TopBar";
import AccountPanel from "@/components/settings/AccountPanel";
import AddressBookPanel from "@/components/settings/AddressBookPanel";
import BillingPanel from "@/components/settings/BillingPanel";
import CompanyContextPanel from "@/components/settings/CompanyContextPanel";
import GeneralPanel from "@/components/settings/GeneralPanel";
import LanguagePanel from "@/components/settings/LanguagePanel";
import NotificationsPanel from "@/components/settings/NotificationsPanel";
import OrganizationMembersPanel from "@/components/settings/OrganizationMembersPanel";
import PendingOrgInvitesPanel from "@/components/settings/PendingOrgInvitesPanel";
import SettingsNav, {
  type SettingsSection,
} from "@/components/settings/SettingsNav";
import { fetchAuthMe, getStoredAccessToken, readDossierUserPreview } from "@/lib/dossier-api";
import { isOrgAdmin } from "@/lib/org-role";
import { useTranslation } from "@/providers/PreferencesProvider";

export default function SettingsPage() {
  const { t } = useTranslation();
  const [section, setSection] = useState<SettingsSection>("billing");
  const [workspaceKind, setWorkspaceKind] = useState<"personal" | "work" | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const preview = readDossierUserPreview();
    if (preview?.workspace_kind === "personal" || preview?.workspace_kind === "work") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hidrata desde localStorage (sistema externo) al montar.
      setWorkspaceKind(preview.workspace_kind);
    }
    if (!getStoredAccessToken()) {
      return;
    }
    let cancelled = false;
    void fetchAuthMe()
      .then((me) => {
        if (cancelled) return;
        setWorkspaceKind(me.workspace_kind === "personal" ? "personal" : "work");
        setIsAdmin(isOrgAdmin(me.role));
      })
      .catch(() => {
        /* mantener preview o null */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (workspaceKind === "personal" && section === "company") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- corrige la seccion activa si dejo de ser valida para el tipo de workspace/rol.
      setSection("general");
    }
    if (!isAdmin && section === "members") {
      setSection("general");
    }
  }, [workspaceKind, section, isAdmin]);

  return (
    <>
      <TopBar
        title={t("settings.title")}
        subtitle={t("settings.subtitle")}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
        <SettingsNav
          active={section}
          onChange={setSection}
          workspaceKind={workspaceKind}
          showMembers={isAdmin && workspaceKind !== "personal"}
        />

        <div>
          <PendingOrgInvitesPanel />
          {section === "general" && <GeneralPanel />}
          {section === "account" && <AccountPanel />}
          {section === "company" && workspaceKind !== "personal" && <CompanyContextPanel />}
          {section === "members" && isAdmin && workspaceKind !== "personal" && (
            <OrganizationMembersPanel />
          )}
          {section === "language" && <LanguagePanel />}
          {section === "billing" && <BillingPanel />}
          {section === "addressbook" && <AddressBookPanel />}
          {section === "notifications" && <NotificationsPanel />}
        </div>
      </div>
    </>
  );
}
