"use client";

import { useEffect, useState } from "react";
import {
  DossierApiError,
  fetchAuthMe,
  getStoredAccessToken,
  type AuthUser,
} from "@/lib/dossier-api";
import { canMutateDossiers, isOrgAdmin, isViewer } from "@/lib/org-role";

type AuthMeState = {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  canMutate: boolean;
  isViewer: boolean;
  isAdmin: boolean;
};

let cachedUser: AuthUser | null = null;
let inflight: Promise<AuthUser | null> | null = null;

export const AUTH_ME_CHANGED_EVENT = "dossier:auth-me-changed";

export function setAuthMeCache(user: AuthUser | null) {
  cachedUser = user;
}

export function notifyAuthMeChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_ME_CHANGED_EVENT));
  }
}

async function loadAuthUser(): Promise<AuthUser | null> {
  if (!getStoredAccessToken()) return null;
  if (cachedUser) return cachedUser;
  if (inflight) return inflight;
  inflight = fetchAuthMe()
    .then((me) => {
      cachedUser = me;
      return me;
    })
    .catch(() => null)
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** Perfil autenticado con rol de organización (cache en memoria por sesión de pestaña). */
export function useAuthMe(): AuthMeState {
  const [user, setUser] = useState<AuthUser | null>(cachedUser);
  const [loading, setLoading] = useState(!cachedUser && Boolean(getStoredAccessToken()));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!getStoredAccessToken()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- corta segun el token de sesion (sistema externo: localStorage), sin trabajo async.
      setUser(null);
      setLoading(false);
      return;
    }

    function reload() {
      setLoading(true);
      cachedUser = null;
      void loadAuthUser()
        .then((me) => {
          if (cancelled) return;
          setUser(me);
          setError(me ? null : "auth");
        })
        .catch((e) => {
          if (cancelled) return;
          setUser(null);
          setError(e instanceof DossierApiError ? e.message : "auth");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }

    reload();
    window.addEventListener(AUTH_ME_CHANGED_EVENT, reload);
    return () => {
      cancelled = true;
      window.removeEventListener(AUTH_ME_CHANGED_EVENT, reload);
    };
  }, []);

  const role = user?.role;
  return {
    user,
    loading,
    error,
    canMutate: canMutateDossiers(role),
    isViewer: isViewer(role),
    isAdmin: isOrgAdmin(role),
  };
}

export function invalidateAuthMeCache() {
  cachedUser = null;
}
