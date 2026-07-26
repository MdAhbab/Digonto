import { type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "../lib/auth";

/* Gate for agent / high-compute pages. Sends anonymous visitors to sign-in and
   remembers where they were headed so they land back there after logging in. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const loc = useLocation();

  if (!session) {
    return <Navigate to="/auth" replace state={{ from: loc.pathname }} />;
  }
  return <>{children}</>;
}
