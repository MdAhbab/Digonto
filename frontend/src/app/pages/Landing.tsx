import { Link } from "react-router";
import { ArrowRight, FileSearch, ShieldCheck, BookOpenText, Radar, Quote, HandCoins, Languages } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import { EarthScene } from "../components/EarthScene";
import { Section, Reveal, Counter, CitationStamp, motion } from "../components/primitives";
import { useEffect, useState, useRef } from "react";
import { useInView, useScroll, useTransform } from "motion/react";
import { Seo, SEO_ROUTES } from "../lib/seo";
import { api, type MetaStatsOut } from "../lib/api";

export function Landing() {
  const { t, lang } = useI18n();
  const { theme } = useTheme();
  const [stats, setStats] = useState<MetaStatsOut | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await api.get<MetaStatsOut>("/meta/stats");
        if (!cancelled) setStats(result);
      } catch {
        // headline stats are a supporting proof-point, not critical path —
        // the hero and marketing copy render fine without them
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // fade the hero copy out as the earth zooms
  const stageRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: stageRef, offset: ["start start", "end end"] });
  const heroOpacity = useTransform(scrollYProgress, [0, 0.55, 0.8], [1, 1, 0]);
  const heroY = useTransform(scrollYProgress, [0, 0.8], [0, -60]);
  const cueOpacity = useTransform(scrollYProgress, [0, 0.15], [1, 0]);

  const meta = SEO_ROUTES["/"];

  return (
    <div className="relative">
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      {/* Fixed Three.js Earth behind the hero; content below scrolls over it */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <EarthScene theme={theme} />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-background/40 via-transparent to-background" />
      </div>

      {/* Tall stage drives the scroll-zoom */}
      <section id="earth-stage" ref={stageRef} className="relative z-10 h-[220vh]">
        <div className="sticky top-0 flex h-screen items-center">
          <motion.div style={{ opacity: heroOpacity, y: heroY }} className="mx-auto w-full max-w-[1280px] px-6 md:px-10">
            <div className="max-w-2xl">
              <div className="mb-6 flex items-center gap-3">
                <span className="h-px w-10 bg-primary" />
                <span className="font-mono text-[0.7rem] uppercase tracking-[0.24em] text-muted-foreground">
                  {t("hero.eyebrow")}
                </span>
              </div>
              <h1 className="font-serif text-[2.4rem] leading-[1.08] md:text-[3.7rem]">{t("hero.title")}</h1>
              <p className="mt-6 max-w-xl text-base text-muted-foreground md:text-lg">{t("hero.sub")}</p>
              <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
                <Link
                  to="/planner"
                  className="focus-ring group inline-flex h-12 items-center justify-center gap-2 rounded-[3px] bg-primary px-7 text-primary-foreground transition-all hover:gap-3"
                >
                  {t("cta.start")}
                  <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
                <a
                  href="#how"
                  className="focus-ring inline-flex h-12 items-center justify-center rounded-[3px] border border-border bg-background/40 px-7 backdrop-blur-sm transition-colors hover:border-primary hover:text-primary"
                >
                  {t("cta.explore")}
                </a>
              </div>
            </div>
          </motion.div>

          {/* scroll cue */}
          <motion.div
            style={{ opacity: cueOpacity }}
            className="pointer-events-none absolute bottom-8 left-1/2 flex -translate-x-1/2 flex-col items-center gap-2 font-mono text-[0.62rem] uppercase tracking-[0.24em] text-muted-foreground"
          >
            <span>{t("cta.explore")}</span>
            <motion.span animate={{ y: [0, 6, 0] }} transition={{ duration: 1.8, repeat: Infinity }} className="h-6 w-px bg-primary/60" />
          </motion.div>
        </div>
      </section>

      {/* Reveal band — transparent so the zoomed Earth stays visible mid-page */}
      <section className="relative z-10 flex min-h-[70vh] items-center justify-center px-6 text-center">
        <Reveal>
          <div className="mx-auto max-w-2xl">
            <span className="font-mono text-[0.7rem] uppercase tracking-[0.24em] text-primary">
              {t("brand.name")} · {t("hero.eyebrow")}
            </span>
            <p className="mt-6 font-serif text-2xl leading-snug md:text-4xl">
              {t("brand.tagline")}
            </p>
          </div>
        </Reveal>
      </section>

      {/* Everything below covers the fixed Earth */}
      <div className="relative z-10 bg-background">
        {/* ---------------- HEADLINE STATS (GET /meta/stats) ---------------- */}
        {stats && (
          <Section eyebrow={t("stats.eyebrow")} className="py-16">
            <div className="grid grid-cols-1 gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-3">
              {[
                { s: t("stats.portals"), to: stats.portals_watched },
                { s: t("stats.snapshots"), to: stats.snapshots_archived },
                { s: t("stats.questions"), to: stats.questions_answered },
              ].map((x) => (
                <Reveal key={x.s}>
                  <div className="bg-card p-8 text-center">
                    <div className="font-mono text-3xl text-primary"><Counter to={x.to} /></div>
                    <p className="mt-2 text-xs text-muted-foreground">{x.s}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </Section>
        )}

        {/* ---------------- PRINCIPLES ---------------- */}
        <Section eyebrow={t("principle.eyebrow")} className="py-24">
          <Reveal>
            <h2 className="max-w-3xl font-serif text-3xl leading-tight md:text-[2.6rem]">{t("principle.title")}</h2>
          </Reveal>
          <div className="mt-14 grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] md:grid-cols-3">
            {[
              { i: <Quote className="size-5" />, t: "principle.cited.t", d: "principle.cited.d" },
              { i: <HandCoins className="size-5" />, t: "principle.free.t", d: "principle.free.d" },
              { i: <Languages className="size-5" />, t: "principle.bangla.t", d: "principle.bangla.d" },
            ].map((s, idx) => (
              <Reveal key={s.t} delay={idx * 0.08}>
                <div className="flex h-full flex-col bg-card p-8">
                  <span className="text-primary">{s.i}</span>
                  <h3 className="mt-6 font-serif text-xl">{t(s.t)}</h3>
                  <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{t(s.d)}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </Section>

        {/* ---------------- HOW IT WORKS ---------------- */}
        <div id="how" className="scroll-mt-24">
          <Section eyebrow={t("how.eyebrow")} className="py-24">
            <Reveal>
              <h2 className="max-w-2xl font-serif text-3xl leading-tight md:text-4xl">{t("how.title")}</h2>
            </Reveal>
            <div className="mt-16 grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] md:grid-cols-2 lg:grid-cols-4">
              {[
                { i: <FileSearch className="size-5" />, t: "how.crawl.t", d: "how.crawl.d", n: "01" },
                { i: <ShieldCheck className="size-5" />, t: "how.verify.t", d: "how.verify.d", n: "02" },
                { i: <BookOpenText className="size-5" />, t: "how.explain.t", d: "how.explain.d", n: "03" },
                { i: <Radar className="size-5" />, t: "how.watch.t", d: "how.watch.d", n: "04" },
              ].map((s, idx) => (
                <Reveal key={s.t} delay={idx * 0.08}>
                  <div className="flex h-full flex-col bg-card p-7">
                    <div className="mb-6 flex items-center justify-between">
                      <span className="text-primary">{s.i}</span>
                      <span className="font-mono text-xs text-muted-foreground">{s.n}</span>
                    </div>
                    <h3 className="font-serif text-xl">{t(s.t)}</h3>
                    <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{t(s.d)}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </Section>
        </div>

        {/* ---------------- TRUTH LEDGER TEASER ---------------- */}
        <Section eyebrow={t("ledger.eyebrow")} className="py-24">
          <div className="grid items-center gap-14 lg:grid-cols-2">
            <LedgerTeaser />
            <Reveal delay={0.15}>
              <div>
                <p className="font-serif text-2xl leading-snug md:text-3xl">{t("ledger.reveal")}</p>
                <Link to="/ledger" className="focus-ring group mt-8 inline-flex items-center gap-2 text-primary">
                  {t("nav.ledger")}
                  <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </Reveal>
          </div>
        </Section>

        {/* ---------------- AGENTS ---------------- */}
        <Section eyebrow={t("agents.eyebrow")} className="py-24">
          <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-4">
            {[
              { t: "agents.porter.t", d: "agents.porter.d", m: "P" },
              { t: "agents.prohori.t", d: "agents.prohori.d", m: "প" },
              { t: "agents.khoji.t", d: "agents.khoji.d", m: "খ" },
              { t: "agents.shonchari.t", d: "agents.shonchari.d", m: "স" },
            ].map((a, idx) => (
              <AgentColumn key={a.t} title={t(a.t)} desc={t(a.d)} monogram={a.m} delay={idx * 0.1} />
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}

function LedgerTeaser() {
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-20%" });
  const [lifted, setLifted] = useState(false);
  const words = t("ledger.claim").split(" ");

  return (
    <div ref={ref} className="relative rounded-[4px] border border-[var(--hairline)] bg-card p-8 md:p-10">
      <div className="mb-4 font-mono text-[0.62rem] uppercase tracking-[0.2em] text-muted-foreground">
        {t("ledger.example")}
      </div>
      <p className="font-serif text-xl leading-relaxed md:text-2xl">
        {words.map((w, i) => (
          <motion.span
            key={i}
            initial={{ opacity: 0 }}
            animate={inView ? { opacity: 1 } : {}}
            transition={{ delay: 0.2 + i * 0.05 }}
            className="mr-[0.28em] inline-block"
          >
            {w}
          </motion.span>
        ))}
        <motion.span
          initial={{ scale: 1.6, opacity: 0 }}
          animate={inView ? { scale: 1, opacity: 1 } : {}}
          transition={{ delay: 0.2 + words.length * 0.05 + 0.1, type: "spring", stiffness: 200, damping: 14 }}
          className="ml-1 inline-block"
        >
          <CitationStamp id="EXAMPLE" onClick={() => setLifted((l) => !l)} />
        </motion.span>
      </p>

      <motion.div initial={false} animate={{ height: lifted ? "auto" : 0, opacity: lifted ? 1 : 0 }} className="overflow-hidden">
        <div className="mt-6 rounded-[3px] border border-[var(--gold)]/40 bg-[var(--gold)]/6 p-4">
          <div className="mb-2 flex items-center justify-between font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">
            <span>{t("sheet.portal")}: official-portal.example</span>
            <span>{t("common.snapshot")}</span>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            This is where the captured snapshot of the source page appears, with the exact quoted requirement highlighted — so you can verify it yourself instead of trusting a middleman.
          </p>
        </div>
      </motion.div>
      {!lifted && (
        <p className="mt-4 font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground">
          ↑ {t("common.viewsource")}
        </p>
      )}
    </div>
  );
}

function AgentColumn({ title, desc, monogram, delay }: { title: string; desc: string; monogram: string; delay: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-15%" });
  return (
    <div ref={ref} className="relative pt-6">
      <motion.span
        className="absolute left-0 top-0 w-px bg-primary"
        initial={{ height: 0 }}
        animate={inView ? { height: "100%" } : {}}
        transition={{ duration: 0.8, delay }}
      />
      <div className="pl-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={inView ? { opacity: 1, scale: 1 } : {}}
          transition={{ delay: delay + 0.3 }}
          className="mb-5 flex size-12 items-center justify-center rounded-full border border-primary/40 font-serif text-2xl text-primary"
        >
          {monogram}
        </motion.div>
        <h3 className="font-serif text-2xl">{title}</h3>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{desc}</p>
      </div>
    </div>
  );
}
