"use client";

/**
 * Who is signed in, for the authenticated shell.
 *
 * This is convenience, not security. The gate that matters is the backend: it
 * refuses every project, execution, repair and report request without a valid
 * session, so a user who defeats this guard sees an empty shell and a stream
 * of 401s — never another account's data.
 */

import { useRouter } from "next/navigation";
import * as React from "react";

import { ApiError } from "@/lib/api";
import { type AuthUser, getMe, logout as logoutRequest } from "@/lib/auth";

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = React.createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = React.useState<AuthUser | null>(null);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    try {
      setUser(await getMe());
    } catch (exc) {
      setUser(null);
      // 401 is the expected answer for a signed-out visitor, not a failure.
      if (!(exc instanceof ApiError) || exc.status !== 401) {
        console.error("could not load the current user", exc);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const signOut = React.useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      // Even if the request failed, stop showing signed-in state locally.
      setUser(null);
      router.replace("/login");
      router.refresh();
    }
  }, [router]);

  const value = React.useMemo(
    () => ({ user, loading, refresh, signOut }),
    [user, loading, refresh, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = React.useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}
