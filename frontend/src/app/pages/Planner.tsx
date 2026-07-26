import { useEffect, useState } from "react";
import { AnimatePresence } from "motion/react";
import { Link } from "react-router";
import { CheckCircle2, Circle, Clock, Zap, X, FileText, Ban, RotateCcw, Undo2 } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { Seal, motion } from "../components/primitives";
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose } from "../components/ui/drawer";
import { Seo, SEO_ROUTES } from "../lib/seo";
import {
  api,
  ApiError,
  type PlanStepOut,
  type PlanChangeOut,
  type PlanTimelineOut,
  type SimulateResponse,
  type TargetOut,
} from "../lib/api";

/** The month heading, in the reader's language.
 *
 * `step.month` is an English label cached on the row when the plan was built
 * (see `_month_label` in planner_service.py); rendering it directly showed a
 * Bangla reader "Oct 2026". `due_at` is the same date without the language
 * baked in, so the heading follows the toggle. */
function monthHeading(step: PlanStepOut, lang: string): string {
  if (!step.due_at) return step.month;
  const parsed = new Date(step.due_at);
  if (Number.isNaN(parsed.getTime())) return step.month;
  return parsed.toLocaleDateString(lang === "bn" ? "bn-BD" : "en-GB", {
    month: "short",
    year: "numeric",
  });
}

function dueLabel(step: PlanStepOut, lang: string): string | null {
  if (!step.due_at) return null;
  const parsed = new Date(step.due_at);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString(lang === "bn" ? "bn-BD" : "en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

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

  // A plan belongs to a target. Without this the page always asked for
  // `/planner/timeline` with no target, which the service resolves to the
  // student's most recently updated plan — an arbitrary one once they are
  // considering more than one programme.
  const [targets, setTargets] = useState<TargetOut[]>([]);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [targetsLoaded, setTargetsLoaded] = useState(false);
  const [pendingStep, setPendingStep] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await api.get<{ items: TargetOut[] }>("/me/targets");
        if (cancelled) return;
        setTargets(page.items);
        setTargetId(page.items[0]?.id ?? null);
      } catch {
        // A student with no targets still gets the generic timeline below.
      } finally {
        if (!cancelled) setTargetsLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!targetsLoaded) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      const qs = targetId ? `?target_id=${encodeURIComponent(targetId)}` : "";
      try {
        const [timeline, changesPage] = await Promise.all([
          api.get<PlanTimelineOut>(`/planner/timeline${qs}`),
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
  }, [targetId, targetsLoaded]);

  async function setStepStatus(step: PlanStepOut, done: boolean) {
    if (pendingStep) return;
    setPendingStep(step.id);
    // Optimistic: the row's seal should settle as the student clicks it, not a
    // round trip later. The response replaces the whole timeline anyway, since
    // completing a step can re-flow the ones that depend on it.
    setSteps((prev) =>
      prev.map((s) => (s.id === step.id ? { ...s, status: done ? "done" : "active" } : s)),
    );
    try {
      const action = done ? "complete" : "reopen";
      const timeline = await api.post<PlanTimelineOut>(
        `/planner/steps/${encodeURIComponent(step.id)}/${action}`,
      );
      setSteps(timeline.steps);
    } catch {
      setSteps((prev) =>
        prev.map((s) => (s.id === step.id ? { ...s, status: step.status } : s)),
      );
    } finally {
      setPendingStep(null);
    }
  }

  async function regenerate() {
    if (regenerating) return;
    setRegenerating(true);
    const qs = targetId ? `?target_id=${encodeURIComponent(targetId)}` : "";
    try {
      const timeline = await api.post<PlanTimelineOut>(`/planner/regenerate${qs}`);
      setSteps(timeline.steps);
    } catch {
      // Leaving the existing timeline on screen is better than replacing a
      // working plan with an error.
    } finally {
      setRegenerating(false);
    }
  }

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
  const activeTarget = targets.find((tg) => tg.id === targetId) ?? null;

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
            onClick={regenerate}
            disabled={regenerating}
            title={t("planner.regenerate.note")}
            className="focus-ring inline-flex h-11 items-center gap-2 rounded-[3px] border border-border px-5 transition-colors hover:border-primary disabled:opacity-60"
          >
            <RotateCcw className={`size-4 ${regenerating ? "animate-spin" : ""}`} />
            {regenerating ? t("planner.regenerating") : t("planner.regenerate")}
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
        {/* Which target this plan is for. A student considering three
            programmes has three timelines, and needs to know which one is on
            screen before reading a single date off it. */}
        {targetsLoaded && targets.length > 0 && (
          <div className="mb-10 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-[var(--hairline)] pb-6">
            <span className="font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
              {t("planner.target.label")}
            </span>
            {targets.length === 1 ? (
              <span className="font-serif text-lg">
                {activeTarget?.programme_name}
                <span className="ml-2 text-sm text-muted-foreground">
                  {activeTarget?.institution_name}
                </span>
              </span>
            ) : (
              <select
                value={targetId ?? ""}
                onChange={(e) => setTargetId(e.target.value || null)}
                className="focus-ring h-10 max-w-full rounded-[3px] border border-border bg-card px-3 text-sm"
              >
                {targets.map((tg) => (
                  <option key={tg.id} value={tg.id}>
                    {tg.programme_name} — {tg.institution_name}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {targetsLoaded && targets.length === 0 && (
          <div className="mb-10 rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-5">
            <p className="text-sm leading-relaxed text-muted-foreground">
              {t("planner.target.none")}
            </p>
            <Link
              to="/destinations"
              className="focus-ring mt-3 inline-flex h-9 items-center rounded-[3px] bg-primary px-4 text-xs text-primary-foreground"
            >
              {t("planner.target.choose")}
            </Link>
          </div>
        )}

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
                {steps.map((s) => {
                  const isDone = s.status === "done";
                  const busy = pendingStep === s.id;
                  const due = dueLabel(s, lang);
                  return (
                    <motion.li
                      key={s.id}
                      layout
                      transition={{ type: "spring", stiffness: 260, damping: 26 }}
                      className="relative grid grid-cols-[auto_1fr] gap-x-5 md:grid-cols-[112px_auto_1fr]"
                    >
                      {/* month (desktop fixed column) */}
                      <div className="hidden pt-1 text-right md:block">
                        <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                          {monthHeading(s, lang)}
                        </span>
                      </div>
                      {/* node */}
                      <div className="relative z-10 pt-1">
                        {isDone ? (
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
                          <h3 className={`font-serif text-lg ${isDone ? "text-muted-foreground line-through decoration-[var(--gold)]/50" : ""}`}>
                            {lang === "en" ? s.titleEn : s.titleBn}
                          </h3>
                          <span className="font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground md:hidden">
                            {monthHeading(s, lang)}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                          {lang === "en" ? s.descEn : s.descBn}
                        </p>

                        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--hairline)] pt-3">
                          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
                            {due && (
                              <span>
                                {t("planner.step.due")}: <span className="text-foreground">{due}</span>
                              </span>
                            )}
                            {/* A step derived from a country's published rule
                                shows where the rule came from. Template steps
                                carry no citation and show none. */}
                            {s.citation && (
                              <span className="text-[var(--gold)]">
                                {t("planner.step.source")}: {s.citation.portal ?? s.citation.snapshot_id}
                              </span>
                            )}
                          </div>
                          <button
                            onClick={() => setStepStatus(s, !isDone)}
                            disabled={busy}
                            className={`focus-ring inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[3px] px-3 text-xs transition-colors disabled:opacity-60 ${
                              isDone
                                ? "border border-border text-muted-foreground hover:border-primary"
                                : "border border-border hover:border-primary"
                            }`}
                          >
                            {isDone ? <Undo2 className="size-3.5" /> : <CheckCircle2 className="size-3.5" />}
                            {busy
                              ? t("planner.step.saving")
                              : isDone
                                ? t("planner.step.reopen")
                                : t("planner.step.complete")}
                          </button>
                        </div>
                      </motion.div>
                    </motion.li>
                  );
                })}
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
