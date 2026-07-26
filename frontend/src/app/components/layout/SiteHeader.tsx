import { useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router";
import { Menu, X, Lock, LogOut } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import { useAuth } from "../../lib/auth";
import { isGated } from "../../lib/auth-context";
import { ThemeToggle, LangToggle } from "./Toggles";
import { Sheet, SheetContent, SheetTrigger } from "../ui/sheet";
import { cn } from "../ui/utils";
import { Logo } from "../Logo";

const links = [
  { to: "/planner", key: "nav.planner" },
  { to: "/ask", key: "nav.ask" },
  { to: "/vault", key: "nav.vault" },
  { to: "/funding", key: "nav.funding" },
  { to: "/interview", key: "nav.interview" },
  { to: "/destinations", key: "nav.destinations" },
] as const;

export function SiteHeader() {
  const { t } = useI18n();
  const { session, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const locked = (to: string) => !session && isGated(to);
  const isModerator = session?.role === "moderator" || session?.role === "admin";
  const navLinks = isModerator ? [...links, { to: "/moderator", key: "nav.moderator" }] : links;

  return (
    <header className="sticky top-0 z-50 w-full border-b border-[var(--hairline)] bg-background/85 backdrop-blur-md">
      <div className="mx-auto flex h-[72px] max-w-[1280px] items-center justify-between px-6 md:px-10">
        <Link to="/" className="focus-ring flex items-center text-foreground" aria-label={t("brand.name")}>
          <Logo className="h-9 w-9" />
        </Link>

        <nav className="hidden items-center gap-1.5 lg:flex">
          {navLinks.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) =>
                cn(
                  "focus-ring rounded-[3px] px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground",
                  isActive && "text-foreground",
                )
              }
            >
              {({ isActive }) => (
                <span className="relative inline-flex items-center gap-1.5">
                  {t(l.key)}
                  {locked(l.to) && <Lock className="size-3 text-muted-foreground/70" aria-label={t("nav.gated")} />}
                  {isActive && <span className="absolute -bottom-1 left-0 h-px w-full bg-primary" />}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <LangToggle />
          <ThemeToggle />
          {session ? (
            <div className="hidden items-center gap-2 md:flex">
              <span
                className="inline-flex size-9 items-center justify-center rounded-full border border-primary/40 font-mono text-xs uppercase text-primary"
                title={session.email}
              >
                {session.email.slice(0, 1)}
              </span>
              <button
                onClick={() => { logout(); nav("/"); }}
                className="focus-ring inline-flex h-9 items-center gap-1.5 rounded-[3px] border border-border px-3 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                <LogOut className="size-4" />
                {t("nav.signout")}
              </button>
            </div>
          ) : (
            <Link
              to="/auth"
              className="focus-ring hidden h-9 items-center rounded-[3px] bg-primary px-4 text-sm text-primary-foreground transition-colors hover:opacity-90 md:inline-flex"
            >
              {t("nav.signin")}
            </Link>
          )}

          {/* Mobile menu */}
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <button
                className="focus-ring inline-flex size-9 items-center justify-center rounded-[3px] border border-border lg:hidden"
                aria-label={t("nav.menu")}
              >
                <Menu className="size-5" />
              </button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[85vw] max-w-sm border-l border-[var(--hairline)] bg-background p-0">
              <div className="flex h-[72px] items-center justify-between border-b border-[var(--hairline)] px-6">
                <Logo className="h-8 w-8 text-foreground" />
                <button onClick={() => setOpen(false)} aria-label={t("nav.close")} className="focus-ring">
                  <X className="size-5" />
                </button>
              </div>
              <nav className="flex flex-col p-3">
                {[{ to: "/", key: "nav.home" }, ...navLinks, { to: "/ledger", key: "nav.ledger" }, { to: "/security", key: "nav.security" }, { to: "/about", key: "nav.about" }].map((l) => (
                  <Link
                    key={l.to}
                    to={l.to}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "focus-ring flex items-center justify-between rounded-[3px] px-4 py-3 text-base text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
                      loc.pathname === l.to && "text-foreground",
                    )}
                  >
                    <span>{t(l.key)}</span>
                    {locked(l.to) && <Lock className="size-3.5 text-muted-foreground/70" aria-label={t("nav.gated")} />}
                  </Link>
                ))}
                {session ? (
                  <button
                    onClick={() => { logout(); setOpen(false); nav("/"); }}
                    className="focus-ring mt-3 inline-flex h-11 items-center justify-center gap-2 rounded-[3px] border border-border text-muted-foreground"
                  >
                    <LogOut className="size-4" />
                    {t("nav.signout")}
                  </button>
                ) : (
                  <Link
                    to="/auth"
                    onClick={() => setOpen(false)}
                    className="focus-ring mt-3 inline-flex h-11 items-center justify-center rounded-[3px] bg-primary text-primary-foreground"
                  >
                    {t("nav.signin")}
                  </Link>
                )}
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  );
}
