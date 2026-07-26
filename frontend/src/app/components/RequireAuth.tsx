import { type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";

/* Gate for agent / high-compute pages. Sends anonymous visitors to sign-in and
   remembers where they were headed so they land back there after logging in.
   Waits for the initial GET /auth/session probe (see lib/auth.tsx) before
   deciding — otherwise a signed-in user refreshing a gated page would be
   bounced to /auth for the instant before the session restore resolves. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const loc = useLocation();

  if (loading) {
    return <div className="min-h-[calc(100vh-4rem)]" aria-hidden="true" />;
  }

  if (!session) {
    return <Navigate to="/auth" replace state={{ from: loc.pathname }} />;
  }
  return <>{children}</>;
}

/* Gate for the moderator console: requires a session AND role in
   (moderator, admin), mirroring app/deps.py's require_role hierarchy on the
   backend (an admin passes a moderator-only gate too). Anonymous visitors
   go to /auth; a signed-in student sees the console's own bilingual
   forbidden message rather than being redirected, since that message is
   itself part of the moderator-console requirement. */
export function RequireRole({ role, children }: { role: "moderator" | "admin"; children: ReactNode }) {
  const { session, loading } = useAuth();
  const { t } = useI18n();
  const loc = useLocation();

  if (loading) {
    return <div className="min-h-[calc(100vh-4rem)]" aria-hidden="true" />;
  }

  if (!session) {
    return <Navigate to="/auth" replace state={{ from: loc.pathname }} />;
  }

  const rank: Record<string, number> = { student: 0, moderator: 1, admin: 2 };
  const allowed = (rank[session.role] ?? -1) >= (rank[role] ?? 99);
  if (!allowed) {
    return (
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-md flex-col items-center justify-center px-6 text-center">
        <div className="rounded-[4px] border border-[var(--hairline)] bg-card p-8">
          <p className="text-sm text-muted-foreground">{t("mod.forbidden")}</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
