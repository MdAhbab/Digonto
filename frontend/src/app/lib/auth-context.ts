import { createContext, useContext } from "react";
import type { Role, UserStatus } from "./api";

/* Real session, restored from GET /auth/session (see auth.tsx). The access
   token itself never lives here — it is held in api.ts's module-private
   variable — this only carries what the UI needs to render. */
export interface Session {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  status: UserStatus;
}

export interface AuthCtx {
  session: Session | null;
  /** true while the initial GET /auth/session probe on app load is pending. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
}

/* Routes that run agents / high compute. These require a session.
   NOTE: this is client-side gating for UX only — the backend enforces the
   real check (auth + rate limiting) on every route. */
export const GATED_PATHS = ["/planner", "/ask", "/vault", "/funding", "/interview"];

export const isGated = (path: string) => GATED_PATHS.some((p) => path === p || path.startsWith(p + "/"));

/* Context object isolated in its own module so identity is stable across HMR. */
export const AuthContext = createContext<AuthCtx | null>(null);

export function useAuth() {
  const c = useContext(AuthContext);
  if (!c) throw new Error("useAuth must be used within AuthProvider");
  return c;
}
