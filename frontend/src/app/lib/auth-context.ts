import { createContext, useContext } from "react";

export interface Session {
  email: string;
  since: number;
}

export interface AuthCtx {
  session: Session | null;
  login: (email: string) => void;
  logout: () => void;
}

/* Routes that run agents / high compute. These require a session.
   NOTE: this is client-side gating for UX only — real abuse prevention must be
   enforced on the backend (auth check + rate limiting) once it's wired up. */
export const GATED_PATHS = ["/planner", "/ask", "/vault", "/funding", "/interview"];

export const isGated = (path: string) => GATED_PATHS.some((p) => path === p || path.startsWith(p + "/"));

/* Context object isolated in its own module so identity is stable across HMR. */
export const AuthContext = createContext<AuthCtx | null>(null);

export function useAuth() {
  const c = useContext(AuthContext);
  if (!c) throw new Error("useAuth must be used within AuthProvider");
  return c;
}
