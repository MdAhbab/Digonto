import { useEffect, useState } from "react";
import { AnimatePresence } from "motion/react";
import { CheckCircle2, Circle, Clock, Zap, X, FileText, Ban } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { Seal, motion } from "../components/primitives";
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose } from "../components/ui/drawer";
import { Seo, SEO_ROUTES } from "../lib/seo";
import { api, ApiError, type PlanStepOut, type PlanChangeOut, type SimulateResponse } from "../lib/api";

export function Planner() {
  const { t, lang } = useI18n();
  const [steps, setSteps] = useState<PlanStepOut[]>([]);
  const [changes, setChanges] = useState<PlanChangeOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [lastSimulated, setLastSimulated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [timeline, changesPage] = await Promise.all([
          api.get<{ plan_id: string; intake_label: string | null; steps: PlanStepOut[]; unseen_changes: number }>(
            "/planner/timeline",
          ),
          api.get<{ items: PlanChangeOut[] }>("/planner/changes"),
        ]);
        if (cancelled) return;
        setSteps(timeline.steps);
        setChanges(changesPage.items);
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

  async function simulate() {
    if (simulating) return;
    setSimulating(true);
    try {
      const result = await api.post<SimulateResponse>("/planner/simulate");
      setSteps(result.plan.steps);
      setChanges((c) => [result.change, ...c]);
      setLastSimulated(true);
      if (result.change.step_key) {
        const changed = result.plan.steps.find((s) => s.step_key === result.change.step_key);
        if (changed) {
          setFlash(changed.id);
          setTimeout(() => setFlash(null), 1600);
        }
      }
      setOpen(true);
    } catch {
      // best-effort: the demonstration button failing silently is preferable
      // to an intrusive error over a working timeline
    } finally {
      setSimulating(false);
    }
  }

  const meta = SEO_ROUTES["/planner"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("brand.name")} title={t("planner.title")} sub={t("planner.sub")}>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={simulate}
            disabled={simulating}
            className="focus-ring inline-flex h-11 items-center gap-2 rounded-[3px] bg-primary px-5 text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            <Zap className="size-4" />
            {simulating ? t("planner.simulating") : t("planner.simulate")}
          </button>
          <button
            onClick={() => setOpen(true)}
            className="focus-ring inline-flex h-11 items-center gap-2 rounded-[3px] border border-border px-5 transition-colors hover:border-primary"
          >
            <FileText className="size-4" />
            {t("planner.whatchanged")}
            {changes.length > 0 && (
              <span className="ml-1 inline-flex size-5 items-center justify-center rounded-full bg-primary font-mono text-[0.62rem] text-primary-foreground">
                {changes.length}
              </span>
            )}
          </button>
        </div>
      </PageHeader>

      <div className="mx-auto max-w-[1180px] px-6 py-16 md:px-10">
        {/* Legend */}
        <div className="mb-10 flex flex-wrap gap-6 font-mono text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          <span className="flex items-center gap-2"><CheckCircle2 className="size-4 text-[var(--gold)]" />{t("planner.done")}</span>
          <span className="flex items-center gap-2"><Clock className="size-4 text-primary" />{t("planner.active")}</span>
          <span className="flex items-center gap-2"><Circle className="size-4" />{t("planner.upcoming")}</span>
          <span className="flex items-center gap-2"><Ban className="size-4" />{t("planner.blocked")}</span>
        </div>

        {loading && (
          <ul className="space-y-5" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <li key={i} className="grid grid-cols-[auto_1fr] gap-x-5 md:grid-cols-[112px_auto_1fr]">
                <div className="hidden md:block" />
                <div className="pt-1">
                  <span className="flex size-4 items-center justify-center rounded-full border border-[var(--hairline)] bg-background" />
                </div>
                <div className="rounded-[4px] border border-[var(--hairline)] bg-card p-5">
                  <div className="h-5 w-1/3 animate-pulse rounded-[2px] bg-secondary" />
                  <div className="mt-3 h-3 w-2/3 animate-pulse rounded-[2px] bg-secondary" />
                </div>
              </li>
            ))}
          </ul>
        )}

        {!loading && error && (
          <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
            {lang === "en" ? error.detail_en : error.detail_bn}
          </div>
        )}

        {!loading && !error && (
          <div className="relative">
            <div className="absolute bottom-0 left-[7px] top-2 w-px bg-[var(--hairline)] md:left-[128px]" />
            <ul className="space-y-5">
              <AnimatePresence>
                {steps.map((s) => (
                  <motion.li
                    key={s.id}
                    layout
                    transition={{ type: "spring", stiffness: 260, damping: 26 }}
                    className="relative grid grid-cols-[auto_1fr] gap-x-5 md:grid-cols-[112px_auto_1fr]"
                  >
                    {/* month (desktop fixed column) */}
                    <div className="hidden pt-1 text-right md:block">
                      <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{s.month}</span>
                    </div>
                    {/* node */}
                    <div className="relative z-10 pt-1">
                      {s.status === "done" ? (
                        <Seal className="size-4 shrink-0 !border-[var(--gold)]" />
                      ) : s.status === "active" ? (
                        <span className="flex size-4 items-center justify-center rounded-full border-2 border-primary bg-background">
                          <span className="size-1.5 rounded-full bg-primary" />
                        </span>
                      ) : s.status === "blocked" ? (
                        <Ban className="size-4 shrink-0 text-muted-foreground" />
                      ) : (
                        <span className="flex size-4 items-center justify-center rounded-full border border-[var(--hairline)] bg-background" />
                      )}
                    </div>
                    {/* entry */}
                    <motion.div
                      animate={flash === s.id ? { backgroundColor: ["var(--gold)", "var(--card)"] } : {}}
                      transition={{ duration: 1.6 }}
                      className={`rounded-[4px] border border-[var(--hairline)] bg-card p-5 ${s.status === "upcoming" ? "opacity-70" : ""}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <h3 className="font-serif text-lg">{lang === "en" ? s.titleEn : s.titleBn}</h3>
                        <span className="font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground md:hidden">{s.month}</span>
                      </div>
                      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{lang === "en" ? s.descEn : s.descBn}</p>
                    </motion.div>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          </div>
        )}
      </div>

      {/* What changed drawer */}
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerContent className="bg-card">
          <div className="mx-auto w-full max-w-2xl">
            <DrawerHeader className="flex flex-row items-center justify-between px-6">
              <DrawerTitle className="font-serif text-xl">{t("planner.drawer.title")}</DrawerTitle>
              <DrawerClose className="focus-ring rounded-[3px] p-1"><X className="size-5" /></DrawerClose>
            </DrawerHeader>
            <div className="max-h-[55vh] overflow-y-auto px-6 pb-10">
              {changes.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">{t("planner.drawer.empty")}</p>
              ) : (
                <ul className="space-y-4">
                  {changes.map((c, i) => (
                    <li key={c.id} className="rounded-[4px] border-l-2 border-primary bg-secondary/50 p-4">
                      <p className="text-sm leading-relaxed">{lang === "en" ? c.textEn : c.textBn}</p>
                      <div className="mt-3 flex items-center justify-between gap-3">
                        <p className="font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">{c.source}</p>
                        {i === 0 && lastSimulated && (
                          <span className="font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
                            {t("common.simulated")}
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  );
}
