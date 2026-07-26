import { useState } from "react";
import { useNavigate, useLocation } from "react-router";
import { Mail, Lock, User as UserIcon, ArrowRight } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useAuth } from "../lib/auth";
import { ApiError, AUTH_RETURN_PATH_KEY } from "../lib/api";
import { motion, AnimatePresence } from "motion/react";
import { Seo, SEO_ROUTES } from "../lib/seo";

type Mode = "signin" | "signup";

export function Auth() {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const loc = useLocation();
  const { login, signup } = useAuth();
  const storedReturn =
    typeof sessionStorage !== "undefined" ? sessionStorage.getItem(AUTH_RETURN_PATH_KEY) : null;
  const from = (loc.state as { from?: string } | null)?.from ?? storedReturn ?? "/planner";

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [touched, setTouched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  const passwordValid = password.length >= 8;
  const nameValid = mode === "signin" || displayName.trim().length > 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    setError(null);
    if (!emailValid || !passwordValid || !nameValid) return;

    setLoading(true);
    try {
      if (mode === "signin") {
        await login(email, password);
      } else {
        await signup(email, password, displayName.trim());
      }
      try {
        sessionStorage.removeItem(AUTH_RETURN_PATH_KEY);
      } catch {
        /* ignore */
      }
      nav(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
      if (!(err instanceof ApiError)) {
        setError(
          new ApiError({
            type: "about:blank",
            title: "Error",
            status: 0,
            detail_en: "Something went wrong. Please try again.",
            detail_bn: "কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।",
          }),
        );
      }
    } finally {
      setLoading(false);
    }
  }

  function switchMode() {
    setMode((m) => (m === "signin" ? "signup" : "signin"));
    setError(null);
    setTouched(false);
  }

  const meta = SEO_ROUTES["/auth"];

  return (
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-md flex-col justify-center px-6 py-20">
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />

      <div className="rounded-[4px] border border-[var(--hairline)] bg-card p-8 md:p-10">
        <div className="mb-8 text-center">
          <div className="font-serif text-3xl">{t("brand.name")}</div>
          <div className="mt-1 font-mono text-[0.62rem] uppercase tracking-[0.28em] text-muted-foreground">est. Dhaka</div>
        </div>

        <div className="mb-6 flex rounded-[3px] border border-border p-1">
          {(["signin", "signup"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                if (m !== mode) switchMode();
              }}
              className={`focus-ring flex-1 rounded-[2px] py-2 text-sm transition-colors ${
                mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {m === "signin" ? t("auth.mode.signin") : t("auth.mode.signup")}
            </button>
          ))}
        </div>

        <AnimatePresence mode="wait">
          <motion.form
            key={mode}
            initial={{ opacity: 0, x: mode === "signin" ? -12 : 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: mode === "signin" ? 12 : -12 }}
            onSubmit={submit}
            noValidate
          >
            <h1 className="font-serif text-2xl">{t("auth.title")}</h1>
            <p className="mt-2 text-sm text-muted-foreground">{t("auth.sub")}</p>

            {mode === "signup" && (
              <label className="mt-8 block">
                <span className="mb-2 block font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
                  {t("auth.displayname")}
                </span>
                <div className="relative">
                  <UserIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Tanha Islam"
                    className="focus-ring h-12 w-full rounded-[3px] border border-border bg-input-background pl-9 pr-3 text-sm outline-none"
                  />
                </div>
                {touched && !nameValid && (
                  <p className="mt-1.5 text-xs text-destructive">{t("auth.error.displayname")}</p>
                )}
              </label>
            )}

            <label className="mt-8 block">
              <span className="mb-2 block font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
                {t("auth.email")}
              </span>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="focus-ring h-12 w-full rounded-[3px] border border-border bg-input-background pl-9 pr-3 text-sm outline-none"
                />
              </div>
              {touched && !emailValid && <p className="mt-1.5 text-xs text-destructive">{t("auth.error.email")}</p>}
            </label>

            <label className="mt-5 block">
              <span className="mb-2 block font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
                {t("auth.password")}
              </span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  className="focus-ring h-12 w-full rounded-[3px] border border-border bg-input-background pl-9 pr-3 text-sm outline-none"
                />
              </div>
              {touched && !passwordValid && (
                <p className="mt-1.5 text-xs text-destructive">{t("auth.error.password")}</p>
              )}
            </label>

            {error && (
              <div className="mt-5 rounded-[3px] border border-destructive/40 bg-destructive/8 p-3 text-xs leading-relaxed text-destructive">
                <p>{lang === "en" ? error.detail_en : error.detail_bn}</p>
                {error.trace_id && (
                  <p className="mt-1 font-mono text-[0.62rem] text-destructive/70">trace: {error.trace_id}</p>
                )}
              </div>
            )}

            <button
              disabled={loading}
              className="focus-ring mt-6 inline-flex h-12 w-full items-center justify-center gap-2 rounded-[3px] bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {loading
                ? mode === "signin"
                  ? t("auth.loading.signin")
                  : t("auth.loading.signup")
                : mode === "signin"
                  ? t("auth.submit.signin")
                  : t("auth.submit.signup")}
              {!loading && <ArrowRight className="size-4" />}
            </button>

            <button type="button" onClick={switchMode} className="focus-ring mt-4 block w-full text-center text-xs text-muted-foreground hover:text-foreground">
              {mode === "signin" ? t("auth.switch.tosignup") : t("auth.switch.tosignin")}
            </button>
          </motion.form>
        </AnimatePresence>
      </div>
      <p className="mt-6 text-center font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">{t("common.free")}</p>
    </div>
  );
}
