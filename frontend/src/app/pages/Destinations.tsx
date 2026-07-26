import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Plus, Check } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import { useAuth } from "../lib/auth";
import { PageHeader } from "../components/PageHeader";
import { Globe } from "../components/Globe";
import { Seo, SEO_ROUTES } from "../lib/seo";
import { api, ApiError, type DestinationOut } from "../lib/api";

const shortlistOpts = { skipAuthRedirect: true as const };

export function Destinations() {
  const { t, lang } = useI18n();
  const { theme } = useTheme();
  const { session } = useAuth();
  const [countries, setCountries] = useState<DestinationOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [signInPrompt, setSignInPrompt] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const page = await api.get<{ items: DestinationOut[] }>("/destinations");
        if (!cancelled) setCountries(page.items);
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err : null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (session?.id) setSignInPrompt(false);
  }, [session?.id]);

  async function toggle(code: string, shortlisted: boolean) {
    if (pending.has(code)) return;
    if (!session?.id) {
      setSignInPrompt(true);
      return;
    }
    setPending((p) => new Set(p).add(code));
    // optimistic update
    setCountries((prev) => prev.map((c) => (c.id === code ? { ...c, shortlisted: !shortlisted } : c)));
    try {
      if (shortlisted) {
        await api.del(`/me/shortlist/${encodeURIComponent(code)}`, undefined, shortlistOpts);
      } else {
        await api.put(`/me/shortlist/${encodeURIComponent(code)}`, undefined, shortlistOpts);
      }
    } catch (err) {
      setCountries((prev) => prev.map((c) => (c.id === code ? { ...c, shortlisted } : c)));
      if (err instanceof ApiError && err.status === 401) {
        setSignInPrompt(true);
      }
    } finally {
      setPending((p) => {
        const next = new Set(p);
        next.delete(code);
        return next;
      });
    }
  }

  const shortlistCount = countries.filter((c) => c.shortlisted).length;
  // Memoised because Globe keys its scene effect on this array. Built inline, a
  // fresh identity on every render of this page tore the canvas down and rebuilt
  // it each time — including on every `pending` change as a student clicks a
  // shortlist button, which is precisely when the globe should stay steady.
  const targets = useMemo(
    () => countries.map((c) => ({ lat: c.lat, lng: c.lng, active: c.shortlisted })),
    [countries],
  );
  const meta = SEO_ROUTES["/destinations"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("nav.destinations")} title={t("dest.title")} sub={t("dest.sub")} />

      <div className="mx-auto grid max-w-[1180px] gap-10 px-6 py-16 md:px-10 lg:grid-cols-[1fr_1fr]">
        <div className="lg:sticky lg:top-24 lg:self-start">
          <div className="aspect-square w-full rounded-[4px] border border-[var(--hairline)] bg-card">
            <Globe theme={theme} targets={targets} />
          </div>
          <p className="mt-4 font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground">
            {t("dest.shortlist")}: {shortlistCount || "—"}
          </p>
        </div>

        {signInPrompt && !session?.id && (
          <div
            className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-5 text-sm text-muted-foreground lg:col-span-2"
            role="status"
          >
            <p>{t("dest.signin.prompt")}</p>
            <Link
              to="/auth"
              state={{ from: "/destinations" }}
              className="focus-ring mt-3 inline-flex h-9 items-center rounded-[3px] bg-primary px-4 text-xs text-primary-foreground"
            >
              {t("dest.signin.action")}
            </Link>
          </div>
        )}

        {loading && (
          <div className="space-y-px overflow-hidden rounded-[4px] border border-[var(--hairline)]" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-start justify-between gap-4 border-b border-[var(--hairline)] bg-card p-5 last:border-0">
                <div className="flex-1 space-y-2">
                  <div className="h-5 w-1/3 animate-pulse rounded-[2px] bg-secondary" />
                  <div className="h-3 w-2/3 animate-pulse rounded-[2px] bg-secondary" />
                </div>
                <div className="h-9 w-24 shrink-0 animate-pulse rounded-[3px] bg-secondary" />
              </div>
            ))}
          </div>
        )}

        {!loading && error && (
          <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
            {lang === "en" ? error.detail_en : error.detail_bn}
          </div>
        )}

        {!loading && !error && (
          <div className="space-y-px overflow-hidden rounded-[4px] border border-[var(--hairline)]">
            {countries.map((c) => (
              <div key={c.id} className="flex items-start justify-between gap-4 border-b border-[var(--hairline)] bg-card p-5 last:border-0">
                <div className="flex-1">
                  <h3 className="font-serif text-lg">{lang === "en" ? c.name_en : c.name_bn}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{lang === "en" ? c.note_en : c.note_bn}</p>
                </div>
                <button
                  onClick={() => toggle(c.id, c.shortlisted)}
                  disabled={pending.has(c.id)}
                  className={`focus-ring inline-flex h-9 shrink-0 items-center gap-1.5 rounded-[3px] px-3 text-xs transition-colors disabled:opacity-60 ${
                    c.shortlisted ? "bg-primary text-primary-foreground" : "border border-border hover:border-primary"
                  }`}
                >
                  {c.shortlisted ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
                  {c.shortlisted ? t("dest.remove") : t("dest.add")}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
