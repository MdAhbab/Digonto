import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Plus, Check, ChevronDown, ArrowUpRight } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import { useAuth } from "../lib/auth";
import { PageHeader } from "../components/PageHeader";
import { Globe } from "../components/Globe";
import { Seo, SEO_ROUTES } from "../lib/seo";
import {
  api,
  ApiError,
  type DestinationOut,
  type ProgrammeOut,
  type TargetOut,
  type SolvencySummary,
} from "../lib/api";

const shortlistOpts = { skipAuthRedirect: true as const };

/** Programme tuition is stored in minor units (see `ProgrammeOut`); solvency
 * amounts are not (see migration 026). Both reach this formatter as a major
 * unit, so the division happens at the one call site that needs it. */
function money(amount: number, currency: string, lang: string): string {
  return new Intl.NumberFormat(lang === "bn" ? "bn-BD" : "en-GB", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

function monthsLabel(months: number | null, lang: string): string | null {
  if (!months) return null;
  return `${months.toLocaleString(lang === "bn" ? "bn-BD" : "en-GB")}`;
}

function SolvencyLine({ s, lang, t }: { s: SolvencySummary; lang: string; t: (k: string) => string }) {
  return (
    <div className="mt-3 border-t border-[var(--hairline)] pt-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
          {t("dest.solvency.label")}
        </span>
        <span className="font-mono text-sm">{money(s.amount, s.currency, lang)}</span>
        {s.hold_days > 0 && (
          <span className="text-xs text-muted-foreground">
            {t("dest.solvency.hold").replace(
              "{days}",
              s.hold_days.toLocaleString(lang === "bn" ? "bn-BD" : "en-GB"),
            )}
          </span>
        )}
        {/* An unverified figure says so, every time it is shown. It is seeded
            from published guidance and no snapshot has confirmed it yet; the
            product's whole claim is that it does not assert what it cannot
            back, so the label is not optional decoration. */}
        <span
          title={s.verified ? t("dest.solvency.verified") : t("dest.solvency.provisional.why")}
          className={`rounded-[2px] border px-1.5 py-0.5 font-mono text-[0.6rem] uppercase tracking-wider ${
            s.verified
              ? "border-[var(--gold)]/40 text-[var(--gold)]"
              : "border-[var(--hairline)] text-muted-foreground"
          }`}
        >
          {s.verified ? t("dest.solvency.verified") : t("dest.solvency.provisional")}
        </span>
      </div>
      {(lang === "en" ? s.note_en : s.note_bn) && (
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {lang === "en" ? s.note_en : s.note_bn}
        </p>
      )}
      {s.source_url && (
        <a
          href={s.source_url}
          target="_blank"
          rel="noreferrer noopener"
          className="focus-ring mt-2 inline-flex items-center gap-1 font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground underline decoration-[var(--hairline)] underline-offset-4 hover:text-foreground"
        >
          {t("dest.solvency.source")}: {s.source_label ?? s.source_url}
          <ArrowUpRight className="size-3" />
        </a>
      )}
    </div>
  );
}

export function Destinations() {
  const { t, lang } = useI18n();
  const { theme } = useTheme();
  const { session } = useAuth();
  const [countries, setCountries] = useState<DestinationOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [signInPrompt, setSignInPrompt] = useState(false);

  // Programme browse, lazily loaded per country. Fetching all eight countries'
  // catalogues on mount would pull ~47 rows nobody has asked to see; the
  // disclosure fetches once and the result is kept for the rest of the visit.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [programmes, setProgrammes] = useState<Record<string, ProgrammeOut[]>>({});
  const [progLoading, setProgLoading] = useState<Set<string>>(new Set());
  const [progError, setProgError] = useState<Set<string>>(new Set());

  // Programmes already on the student's plan, so the button reads "Tracked"
  // rather than offering a duplicate the API would reject.
  const [tracked, setTracked] = useState<Set<string>>(new Set());
  const [tracking, setTracking] = useState<Set<string>>(new Set());
  const [justTracked, setJustTracked] = useState<string | null>(null);

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

  useEffect(() => {
    if (!session?.id) {
      setTracked(new Set());
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const page = await api.get<{ items: TargetOut[] }>("/me/targets");
        if (!cancelled) setTracked(new Set(page.items.map((tg) => tg.programme_id)));
      } catch {
        // A missing target list only costs the "Tracked" affordance; the page
        // and the browse below it still work, so this stays silent.
      }
    })();
    return () => {
      cancelled = true;
    };
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

  const loadProgrammes = useCallback(async (code: string) => {
    setProgLoading((p) => new Set(p).add(code));
    setProgError((p) => {
      const next = new Set(p);
      next.delete(code);
      return next;
    });
    try {
      const page = await api.get<{ items: ProgrammeOut[] }>(
        `/programmes?country=${encodeURIComponent(code)}`,
      );
      setProgrammes((prev) => ({ ...prev, [code]: page.items }));
    } catch {
      setProgError((p) => new Set(p).add(code));
    } finally {
      setProgLoading((p) => {
        const next = new Set(p);
        next.delete(code);
        return next;
      });
    }
  }, []);

  function toggleExpand(code: string) {
    const isOpen = expanded.has(code);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (isOpen) next.delete(code);
      else next.add(code);
      return next;
    });
    if (!isOpen && !programmes[code] && session?.id) void loadProgrammes(code);
  }

  async function track(programme: ProgrammeOut, country: DestinationOut) {
    if (tracking.has(programme.id) || tracked.has(programme.id)) return;
    if (!session?.id) {
      setSignInPrompt(true);
      return;
    }
    setTracking((p) => new Set(p).add(programme.id));
    try {
      // The country's primary route, not left null. `compose_budget` resolves
      // the solvency rule on (country, visa_type) and skips it entirely when
      // the target has no visa type, which silently drops the bank-balance
      // line from the budget — the one figure a student most needs from it.
      await api.post<TargetOut>("/me/targets", {
        programme_id: programme.id,
        visa_type: country.visa_types[0] ?? null,
      });
      setTracked((p) => new Set(p).add(programme.id));
      setJustTracked(programme.id);
    } catch (err) {
      // 409 means it is already a target — the end state the student wanted,
      // so reflect that rather than reporting a failure.
      if (err instanceof ApiError && err.status === 409) {
        setTracked((p) => new Set(p).add(programme.id));
      } else if (err instanceof ApiError && err.status === 401) {
        setSignInPrompt(true);
      }
    } finally {
      setTracking((p) => {
        const next = new Set(p);
        next.delete(programme.id);
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
  const numLocale = lang === "bn" ? "bn-BD" : "en-GB";

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
            {countries.map((c) => {
              const isOpen = expanded.has(c.id);
              const rows = programmes[c.id];
              return (
                <div key={c.id} className="border-b border-[var(--hairline)] bg-card last:border-0">
                  <div className="flex items-start justify-between gap-4 p-5">
                    <div className="flex-1">
                      <h3 className="font-serif text-lg">{lang === "en" ? c.name_en : c.name_bn}</h3>
                      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                        {lang === "en" ? c.note_en : c.note_bn}
                      </p>

                      <p className="mt-3 font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
                        {c.programme_count.toLocaleString(numLocale)} {t("dest.programmes.count")}
                        <span className="px-2 text-[var(--hairline)]">·</span>
                        {c.scholarship_count.toLocaleString(numLocale)} {t("dest.scholarships.count")}
                      </p>

                      {c.solvency && <SolvencyLine s={c.solvency} lang={lang} t={t} />}
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

                  {c.programme_count > 0 && (
                    <div className="border-t border-[var(--hairline)]">
                      <button
                        onClick={() => toggleExpand(c.id)}
                        aria-expanded={isOpen}
                        className="focus-ring flex w-full items-center justify-between gap-2 px-5 py-3 text-left font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {isOpen ? t("dest.programmes.hide") : t("dest.programmes.show")}
                        <ChevronDown
                          className={`size-4 transition-transform duration-300 ${isOpen ? "rotate-180" : ""}`}
                        />
                      </button>

                      {isOpen && (
                        <div className="px-5 pb-5">
                          {!session?.id && (
                            <div className="rounded-[3px] border border-[var(--hairline)] bg-secondary/40 p-4 text-sm text-muted-foreground">
                              <p>{t("dest.programmes.signin")}</p>
                              <Link
                                to="/auth"
                                state={{ from: "/destinations" }}
                                className="focus-ring mt-3 inline-flex h-9 items-center rounded-[3px] bg-primary px-4 text-xs text-primary-foreground"
                              >
                                {t("dest.signin.action")}
                              </Link>
                            </div>
                          )}

                          {session?.id && progLoading.has(c.id) && (
                            <ul className="space-y-px" aria-hidden="true">
                              {[0, 1].map((i) => (
                                <li key={i} className="rounded-[3px] border border-[var(--hairline)] p-4">
                                  <div className="h-4 w-2/5 animate-pulse rounded-[2px] bg-secondary" />
                                  <div className="mt-2.5 h-3 w-3/5 animate-pulse rounded-[2px] bg-secondary" />
                                </li>
                              ))}
                            </ul>
                          )}

                          {session?.id && progError.has(c.id) && (
                            <p className="text-sm text-muted-foreground">{t("dest.programmes.error")}</p>
                          )}

                          {session?.id && rows && rows.length === 0 && (
                            <p className="text-sm text-muted-foreground">{t("dest.programmes.empty")}</p>
                          )}

                          {session?.id && rows && rows.length > 0 && (
                            <ul className="space-y-3">
                              {rows.map((p) => {
                                const isTracked = tracked.has(p.id);
                                const isTracking = tracking.has(p.id);
                                return (
                                  <li
                                    key={p.id}
                                    className="rounded-[3px] border border-[var(--hairline)] p-4"
                                  >
                                    <div className="flex flex-wrap items-start justify-between gap-3">
                                      <div className="min-w-0 flex-1">
                                        <h4 className="font-serif text-base leading-snug">{p.name}</h4>
                                        <p className="mt-1 text-sm text-muted-foreground">
                                          {p.institution_name}
                                        </p>
                                      </div>
                                      <button
                                        onClick={() => track(p, c)}
                                        disabled={isTracking || isTracked}
                                        className={`focus-ring inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[3px] px-3 text-xs transition-colors disabled:opacity-100 ${
                                          isTracked
                                            ? "border border-[var(--gold)]/40 text-[var(--gold)]"
                                            : "border border-border hover:border-primary"
                                        }`}
                                      >
                                        {isTracked ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
                                        {isTracked
                                          ? t("dest.prog.tracked")
                                          : isTracking
                                            ? t("dest.prog.tracking")
                                            : t("dest.prog.track")}
                                      </button>
                                    </div>

                                    <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5 font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
                                      {p.tuition_currency && (
                                        <div className="flex items-baseline gap-1.5">
                                          <dt>{t("dest.prog.tuition")}</dt>
                                          <dd className="text-foreground">
                                            {p.tuition_amount
                                              ? money(p.tuition_amount / 100, p.tuition_currency, lang)
                                              : t("dest.prog.notuition")}
                                          </dd>
                                        </div>
                                      )}
                                      {monthsLabel(p.duration_months, lang) && (
                                        <div className="flex items-baseline gap-1.5">
                                          <dt>{t("dest.prog.duration")}</dt>
                                          <dd className="text-foreground">
                                            {monthsLabel(p.duration_months, lang)} {t("dest.prog.months")}
                                          </dd>
                                        </div>
                                      )}
                                      {p.deadline_at && (
                                        <div className="flex items-baseline gap-1.5">
                                          <dt>{t("dest.prog.deadline")}</dt>
                                          <dd className="text-foreground">
                                            {new Date(p.deadline_at).toLocaleDateString(numLocale, {
                                              day: "numeric",
                                              month: "short",
                                              year: "numeric",
                                            })}
                                          </dd>
                                        </div>
                                      )}
                                      {p.min_english != null && (
                                        <div className="flex items-baseline gap-1.5">
                                          <dt>{t("dest.prog.minenglish")}</dt>
                                          <dd className="text-foreground">
                                            {p.min_english.toLocaleString(numLocale)}
                                          </dd>
                                        </div>
                                      )}
                                    </dl>

                                    {justTracked === p.id && (
                                      <div
                                        role="status"
                                        className="mt-3 border-t border-[var(--hairline)] pt-3"
                                      >
                                        <p className="text-xs leading-relaxed text-muted-foreground">
                                          {t("dest.prog.tracked.note")}
                                        </p>
                                        <div className="mt-2.5 flex flex-wrap gap-4">
                                          <Link
                                            to="/planner"
                                            className="focus-ring inline-flex items-center gap-1 font-mono text-[0.62rem] uppercase tracking-wider text-primary underline decoration-[var(--hairline)] underline-offset-4"
                                          >
                                            {t("dest.prog.goplan")}
                                            <ArrowUpRight className="size-3" />
                                          </Link>
                                          <Link
                                            to="/funding"
                                            className="focus-ring inline-flex items-center gap-1 font-mono text-[0.62rem] uppercase tracking-wider text-primary underline decoration-[var(--hairline)] underline-offset-4"
                                          >
                                            {t("dest.prog.gofunding")}
                                            <ArrowUpRight className="size-3" />
                                          </Link>
                                        </div>
                                      </div>
                                    )}
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
