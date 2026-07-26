import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AuthContext, type Session } from "./auth-context";
import { api, setAccessToken, type AuthResponse, type User } from "./api";

// Re-export so consumers can import from "../lib/auth".
export { useAuth } from "./auth-context";
export type { Session } from "./auth-context";

function toSession(user: User): Session {
  return {
    id: user.id,
    email: user.email,
    display_name: user.display_name,
    role: user.role,
    status: user.status,
  };
}

/* Real session against the Digonto API (docs/api_contract.md section 3).
   The access token is held in memory only (see lib/api.ts); the refresh
   token is an HttpOnly cookie the browser sends automatically. On mount we
   probe GET /auth/session — the api client transparently attempts
   POST /auth/refresh first if no access token is in memory yet, so a page
   reload with a live refresh cookie restores the session without the user
   doing anything. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const user = await api.get<User>("/auth/session", { skipAuthRedirect: true });
        if (!cancelled) setSession(toSession(user));
      } catch {
        if (!cancelled) setSession(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.post<AuthResponse>("/auth/login", { email, password });
    setAccessToken(res.access_token);
    setSession(toSession(res.user));
  }, []);

  const signup = useCallback(async (email: string, password: string, displayName: string) => {
    const res = await api.post<AuthResponse>("/auth/signup", {
      email,
      password,
      display_name: displayName,
    });
    setAccessToken(res.access_token);
    setSession(toSession(res.user));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // best-effort: clear the local session regardless of network state
    }
    setAccessToken(null);
    setSession(null);
  }, []);

  return (
    <AuthContext.Provider value={{ session, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
