import { useEffect, useState } from "react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { Reveal, Counter, HorizonRule } from "../components/primitives";
import { Seo, SEO_ROUTES } from "../lib/seo";
import { api, ApiError, type MetaStatsOut } from "../lib/api";

export function About() {
  const { t, lang } = useI18n();
  const [stats, setStats] = useState<MetaStatsOut | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await api.get<MetaStatsOut>("/meta/stats");
        if (!cancelled) setStats(result);
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err : null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const boxes = stats
    ? [
        { s: "% commission taken", to: stats.commission_taken_pct },
        { s: "% claims cited", to: Math.round(stats.citation_rate * 100) },
        { s: "UN SDG aligned", to: stats.sdg_aligned },
      ]
    : null;

  const meta = SEO_ROUTES["/about"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("nav.about")} title={t("about.title")} sub={t("about.sub")} />

      <div className="mx-auto max-w-3xl px-6 py-16 md:px-10">
        <Reveal>
          <p className="font-serif text-2xl leading-relaxed md:text-[1.75rem]">
            Digonto exists because the distance between a Bangladeshi student and a fair chance abroad is not talent — it is information, and who controls it.
          </p>
        </Reveal>

        <HorizonRule className="my-12" />

        <div className="space-y-6 text-base leading-relaxed text-muted-foreground">
          <Reveal delay={0.05}><p>Every year tens of thousands leave for study, and a market of consultancies grows around their hope. Most are honest. Enough are not. The rules that decide a visa are public, but scattered across dozens of portals in language built to intimidate.</p></Reveal>
          <Reveal delay={0.1}><p>We built a quiet office that reads those portals so you don't have to, translates them into plain Bangla and English, and — crucially — proves every word with a timestamped snapshot of the source. No claim without a citation. No fee without an itemised, fair comparison.</p></Reveal>
          <Reveal delay={0.15}><p>Digonto is free, and it will stay free. It takes no commission and no referral fee. It is a public-interest instrument, aligned with UN Sustainable Development Goal 4 — Quality Education for all.</p></Reveal>
        </div>

        {error && !stats && (
          <div className="mt-16 rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-center text-sm text-muted-foreground">
            {lang === "en" ? error.detail_en : error.detail_bn}
          </div>
        )}

        <div className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-3">
          {boxes
            ? boxes.map((x) => (
                <div key={x.s} className="bg-card p-6 text-center">
                  <div className="font-mono text-3xl text-primary"><Counter to={x.to} /></div>
                  <p className="mt-2 text-xs text-muted-foreground">{x.s}</p>
                </div>
              ))
            : [0, 1, 2].map((i) => (
                <div key={i} className="bg-card p-6 text-center" aria-hidden="true">
                  <div className="mx-auto h-8 w-12 animate-pulse rounded-[2px] bg-secondary" />
                  <div className="mx-auto mt-3 h-3 w-20 animate-pulse rounded-[2px] bg-secondary" />
                </div>
              ))}
        </div>

        <blockquote className="mt-16 border-l-2 border-primary pl-6 font-serif text-xl italic leading-relaxed">
          {t("brand.tagline")}
        </blockquote>
      </div>
    </div>
  );
}
