import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AuthContext, type Session } from "./auth-context";

// Re-export so consumers can import from "../lib/auth".
export { useAuth } from "./auth-context";
export type { Session } from "./auth-context";

const KEY = "digonto-session";

/* Client-side session, persisted to localStorage. This stands in for a real
   backend: swap `login`/`logout` for calls to your auth API + replace the
   stored value with a real token when you wire the server. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? (JSON.parse(raw) as Session) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (session) localStorage.setItem(KEY, JSON.stringify(session));
    else localStorage.removeItem(KEY);
  }, [session]);

  const login = useCallback((email: string) => {
    setSession({ email, since: Date.now() });
  }, []);

  const logout = useCallback(() => setSession(null), []);

  return <AuthContext.Provider value={{ session, login, logout }}>{children}</AuthContext.Provider>;
}
