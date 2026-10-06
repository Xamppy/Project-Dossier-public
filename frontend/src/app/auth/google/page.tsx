"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import {
  clearAuthSession,
  fetchAuthMe,
  persistAuthToken,
  writeDossierUserPreview,
} from "@/lib/dossier-api";
import { useTranslation } from "@/providers/PreferencesProvider";

const ERROR = "/login?error=google";

/** Vuelta del inicio de sesión con Google: la API deja el JWT en el fragmento `#token=`. */
export default function GoogleLoginReturnPage() {
  const router = useRouter();
  const { t } = useTranslation();
  // El efecto corre dos veces en modo estricto y el fragmento ya se borró en la primera.
  const procesado = useRef(false);

  useEffect(() => {
    if (procesado.current) return;
    procesado.current = true;

    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    // Fuera del historial: el token no debe quedar en la barra ni en «atrás».
    window.history.replaceState(null, "", window.location.pathname);
    if (!token) {
      router.replace(ERROR);
      return;
    }

    persistAuthToken(token, true);
    fetchAuthMe()
      .then((user) => {
        writeDossierUserPreview(
          {
            email: user.email,
            full_name: user.full_name,
            company_name: user.company_name,
            workspace_kind: user.workspace_kind,
            organization_plan: user.organization_plan,
            is_platform_admin: !!user.is_platform_admin,
          },
          "local",
        );
        router.replace("/dashboard");
      })
      .catch(() => {
        clearAuthSession();
        router.replace(ERROR);
      });
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center" style={{ backgroundColor: "var(--bg-page)" }}>
      <p className="text-sm" role="status" style={{ color: "var(--text-muted)" }}>
        {t("auth.google.signing_in")}
      </p>
    </main>
  );
}
