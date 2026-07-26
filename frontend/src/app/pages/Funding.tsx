import { useEffect, useState } from "react";
import { Plus, ArrowUpDown, X } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { CitationStamp, motion } from "../components/primitives";
import { Seo, SEO_ROUTES } from "../lib/seo";
import {
  api,
  qs,
  ApiError,
  type CoverageType,
  type ScholarshipOut,
  type SortKey,
  type SortOrder,
  type FundingSourceOut,
  type SourceKind,
  type BudgetOut,
  type FeeCheckOut,
  type TargetOut,
} from "../lib/api";

const SOURCE_COLORS: Record<SourceKind, string> = {
  own_funds: "var(--chart-1)",
  awards: "var(--chart-2)",
  sponsorship: "var(--chart-3)",
  loan: "var(--chart-4)",
  other: "var(--chart-5)",
};

const SOURCE_KINDS: SourceKind[] = ["own_funds", "awards", "sponsorship", "loan", "other"];

function bdt(n: number): string {
  return `৳${n.toLocaleString("en-US")}`;
}

const SORT_COLUMNS: readonly [SortKey, string][] = [
  ["name", "funding.col.name"],
  ["country", "funding.col.country"],
  ["coverage", "funding.col.amount"],
  ["deadline", "funding.col.deadline"],
];

/** What an award is worth, formatted with the unit it is actually in.
 *
 * The previous version printed `${s.coverage}%`, where `coverage` was populated from
 * `scholarships.amount`, a money value. A 1,500,000 BDT award was therefore displayed
 * as "1500000%" while the awards with no recorded amount showed an em dash, which made
 * the column read as though most scholarships cover nothing and a few cover fifteen
 * thousand times the cost.
 *
 * `coverage_type` is what the column was reaching for and is shown when there is no
 * figure, because "full" or "tuition only" is more use to a student than a blank.
 */
function formatAward(
  s: { amount: number | null; currency: string | null; coverage_type: CoverageType | null },
  lang: string,
): string {
  const typeLabel: Record<CoverageType, { en: string; bn: string }> = {
    full: { en: "Full", bn: "সম্পূর্ণ" },
    partial: { en: "Partial", bn: "আংশিক" },
    tuition_only: { en: "Tuition only", bn: "শুধু টিউশন" },
    stipend_only: { en: "Stipend only", bn: "শুধু উপবৃত্তি" },
    travel: { en: "Travel", bn: "ভ্রমণ" },
  };
  const kind = s.coverage_type ? typeLabel[s.coverage_type][lang === "bn" ? "bn" : "en"] : null;

  if (s.amount === null || s.amount <= 0) return kind ?? "—";

  // `Intl` handles the grouping separators for both locales, and falls back to a
  // plain grouped number when the currency code is missing or not one it knows.
  const locale = lang === "bn" ? "bn-BD" : "en-GB";
  let money: string;
  try {
    money = s.currency
      ? new Intl.NumberFormat(locale, {
          style: "currency",
          currency: s.currency,
          maximumFractionDigits: 0,
        }).format(s.amount)
      : new Intl.NumberFormat(locale).format(s.amount);
  } catch {
    money = `${new Intl.NumberFormat(locale).format(s.amount)}${s.currency ? ` ${s.currency}` : ""}`;
  }
  return kind ? `${money} · ${kind}` : money;
}

export function Funding() {
  const { t, lang } = useI18n();

  const [scholarships, setScholarships] = useState<ScholarshipOut[]>([]);
  const [schLoading, setSchLoading] = useState(true);
  const [schError, setSchError] = useState<ApiError | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("deadline");
  const [order, setOrder] = useState<SortOrder>("asc");

  const [targetId, setTargetId] = useState<string | null>(null);
  const [targetsLoading, setTargetsLoading] = useState(true);

  const [sources, setSources] = useState<FundingSourceOut[]>([]);
  const [budget, setBudget] = useState<BudgetOut | null>(null);
  const [budgetLoading, setBudgetLoading] = useState(true);
  const [budgetError, setBudgetError] = useState<ApiError | null>(null);

  const [addingSource, setAddingSource] = useState(false);
  const [newKind, setNewKind] = useState<SourceKind>("own_funds");
  const [newAmount, setNewAmount] = useState("");

  const [quoted, setQuoted] = useState("");
  const [feeResult, setFeeResult] = useState<FeeCheckOut | null>(null);
  const [feeLoading, setFeeLoading] = useState(false);
  const [feeError, setFeeError] = useState<ApiError | null>(null);

  // Scholarships: server-side sort, refetched whenever sort/order changes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setSchLoading(true);
      setSchError(null);
      try {
        const page = await api.get<{ items: ScholarshipOut[] }>(`/funding/scholarships${qs({ sort: sortKey, order })}`);
        if (!cancelled) setScholarships(page.items);
      } catch (err) {
        if (!cancelled) setSchError(err instanceof ApiError ? err : null);
      } finally {
        if (!cancelled) setSchLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sortKey, order]);

  // Pick the student's first target as the budget/sources scope.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setTargetsLoading(true);
      try {
        const page = await api.get<{ items: TargetOut[] }>("/me/targets");
        if (!cancelled) setTargetId(page.items[0]?.id ?? null);
      } catch {
        if (!cancelled) setTargetId(null);
      } finally {
        if (!cancelled) setTargetsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadBudgetAndSources(id: string) {
    setBudgetLoading(true);
    setBudgetError(null);
    try {
      const [sourcesPage, budgetOut] = await Promise.all([
        api.get<{ items: FundingSourceOut[] }>(`/funding/sources${qs({ target_id: id })}`),
        api.get<BudgetOut>(`/funding/budget${qs({ target_id: id })}`),
      ]);
      setSources(sourcesPage.items);
      setBudget(budgetOut);
    } catch (err) {
      setBudgetError(err instanceof ApiError ? err : null);
    } finally {
      setBudgetLoading(false);
    }
  }

  useEffect(() => {
    if (targetsLoading) return;
    if (!targetId) {
      setBudgetLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      setBudgetLoading(true);
      setBudgetError(null);
      try {
        const [sourcesPage, budgetOut] = await Promise.all([
          api.get<{ items: FundingSourceOut[] }>(`/funding/sources${qs({ target_id: targetId })}`),
          api.get<BudgetOut>(`/funding/budget${qs({ target_id: targetId })}`),
        ]);
        if (!cancelled) {
          setSources(sourcesPage.items);
          setBudget(budgetOut);
        }
      } catch (err) {
        if (!cancelled) setBudgetError(err instanceof ApiError ? err : null);
      } finally {
        if (!cancelled) setBudgetLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [targetId, targetsLoading]);

  async function addSource() {
    if (!targetId) return;
    const amount = Number(newAmount);
    if (!Number.isFinite(amount) || amount <= 0) return;
    try {
      await api.post(`/funding/sources${qs({ target_id: targetId })}`, { kind: newKind, amount_bdt: amount });
      setNewAmount("");
      setAddingSource(false);
      await loadBudgetAndSources(targetId);
    } catch {
      // leave the mini-form open so the student can retry
    }
  }

  async function removeSource(kind: SourceKind) {
    if (!targetId) return;
    try {
      await api.del(`/funding/sources/${kind}${qs({ target_id: targetId })}`);
      await loadBudgetAndSources(targetId);
    } catch {
      // best-effort
    }
  }

  function sortBy(key: SortKey) {
    if (key === sortKey) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setOrder("asc");
    }
  }

  async function runFeeCheck(e: React.FormEvent) {
    e.preventDefault();
    const amount = Number(quoted);
    if (!Number.isFinite(amount) || amount <= 0) return;
    setFeeLoading(true);
    setFeeError(null);
    setFeeResult(null);
    try {
      const result = await api.post<FeeCheckOut>("/funding/fee-check", { quoted_bdt: amount });
      setFeeResult(result);
    } catch (err) {
      setFeeError(err instanceof ApiError ? err : null);
    } finally {
      setFeeLoading(false);
    }
  }

  const total = sources.reduce((s, x) => s + x.amount_bdt, 0);
  const threshold = budget?.solvency_required_bdt ?? null;
  const pct = threshold ? Math.min(100, (total / threshold) * 100) : 0;
  const fairTotal = feeResult?.fair_bdt ?? feeResult?.lines.reduce((s, l) => s + l.amount_bdt, 0) ?? 0;

  const meta = SEO_ROUTES["/funding"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("agents.khoji.t")} title={t("funding.title")} sub={t("funding.sub")} />

      <div className="mx-auto max-w-[1180px] space-y-16 px-6 py-16 md:px-10">
        {/* Budget composition */}
        <section>
          <h2 className="font-serif text-2xl">{t("funding.budget")}</h2>

          {(targetsLoading || budgetLoading) && (
            <div className="mt-6 rounded-[4px] border border-[var(--hairline)] bg-card p-6" aria-hidden="true">
              <div className="h-12 w-full animate-pulse rounded-[3px] bg-secondary" />
              <div className="mt-3 h-3 w-1/2 animate-pulse rounded-[2px] bg-secondary" />
            </div>
          )}

          {!targetsLoading && !targetId && (
            <div className="mt-6 rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
              {t("funding.notarget")}
            </div>
          )}

          {!targetsLoading && targetId && !budgetLoading && budgetError && (
            <div className="mt-6 rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
              {lang === "en" ? budgetError.detail_en : budgetError.detail_bn}
            </div>
          )}

          {!targetsLoading && targetId && !budgetLoading && !budgetError && (
            <div className="mt-6 rounded-[4px] border border-[var(--hairline)] bg-card p-6">
              <div className="relative h-12 w-full overflow-hidden rounded-[3px] bg-secondary">
                <div className="flex h-full">
                  {sources.map((s) => (
                    <motion.div
                      key={s.id}
                      layout
                      initial={{ width: 0 }}
                      animate={{ width: threshold ? `${(s.amount_bdt / threshold) * 100}%` : 0 }}
                      transition={{ type: "spring", stiffness: 120, damping: 22 }}
                      style={{ background: SOURCE_COLORS[s.kind] }}
                      className="h-full"
                      title={lang === "en" ? s.label_en : s.label_bn}
                    />
                  ))}
                </div>
                <div className="absolute inset-y-0 right-0 flex items-center">
                  <div className="h-full w-0.5 bg-foreground" />
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between font-mono text-xs">
                <span className="text-muted-foreground">
                  {t("funding.threshold")}: <span className="text-foreground">{threshold !== null ? bdt(threshold) : "—"}</span>
                </span>
                <span className={pct >= 100 ? "text-[var(--gold)]" : "text-[var(--amber-status)]"}>
                  {bdt(total)} · {Math.round(pct)}%
                </span>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-4">
                {sources.map((s) => (
                  <span key={s.id} className="group flex items-center gap-2 text-sm">
                    <span className="size-3 rounded-[2px]" style={{ background: SOURCE_COLORS[s.kind] }} />
                    {lang === "en" ? s.label_en : s.label_bn} <span className="font-mono text-muted-foreground">{bdt(s.amount_bdt)}</span>
                    <button
                      onClick={() => removeSource(s.kind)}
                      className="focus-ring text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                      aria-label={t("funding.remove")}
                    >
                      <X className="size-3.5" />
                    </button>
                  </span>
                ))}

                {!addingSource ? (
                  <button onClick={() => setAddingSource(true)} className="focus-ring inline-flex items-center gap-1.5 text-sm text-primary">
                    <Plus className="size-4" /> {t("funding.add")}
                  </button>
                ) : (
                  <div className="flex flex-wrap items-center gap-2 rounded-[3px] border border-[var(--hairline)] bg-secondary/30 p-2">
                    <select
                      value={newKind}
                      onChange={(e) => setNewKind(e.target.value as SourceKind)}
                      aria-label={t("funding.addsource.kind")}
                      className="focus-ring h-8 rounded-[3px] border border-border bg-input-background px-2 text-xs outline-none"
                    >
                      {SOURCE_KINDS.map((k) => (
                        <option key={k} value={k}>
                          {k.replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                    <input
                      value={newAmount}
                      onChange={(e) => setNewAmount(e.target.value)}
                      type="number"
                      min={1}
                      placeholder={t("funding.addsource.amount")}
                      aria-label={t("funding.addsource.amount")}
                      className="focus-ring h-8 w-32 rounded-[3px] border border-border bg-input-background px-2 text-xs outline-none"
                    />
                    <button onClick={addSource} className="focus-ring h-8 rounded-[3px] bg-primary px-3 text-xs text-primary-foreground">
                      {t("funding.addsource.submit")}
                    </button>
                    <button onClick={() => setAddingSource(false)} className="focus-ring h-8 rounded-[3px] px-2 text-xs text-muted-foreground">
                      {t("common.cancel")}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </section>

        {/* Scholarship broadsheet */}
        <section>
          <h2 className="font-serif text-2xl">{t("funding.scholarships")}</h2>

          {schLoading && (
            <div className="mt-6 space-y-px overflow-hidden rounded-[4px] border border-[var(--hairline)]" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-11 animate-pulse bg-card" />
              ))}
            </div>
          )}

          {!schLoading && schError && (
            <div className="mt-6 rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
              {lang === "en" ? schError.detail_en : schError.detail_bn}
            </div>
          )}

          {!schLoading && !schError && scholarships.length === 0 && (
            <div className="mt-6 rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-center text-sm text-muted-foreground">
              {t("funding.empty")}
            </div>
          )}

          {!schLoading && !schError && scholarships.length > 0 && (
            <div className="mt-6 overflow-x-auto rounded-[4px] border border-[var(--hairline)]">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-[var(--hairline)] bg-secondary/40 text-left">
                    {SORT_COLUMNS.map(([k, lbl]) => (
                      <th key={k} className="px-5 py-3">
                        <button onClick={() => sortBy(k)} className="focus-ring inline-flex items-center gap-1.5 font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground hover:text-foreground">
                          {t(lbl)} <ArrowUpDown className="size-3" />
                        </button>
                      </th>
                    ))}
                    <th className="px-5 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {scholarships.map((s) => (
                    <tr key={s.id} className="border-b border-[var(--hairline)] last:border-0 hover:bg-secondary/20">
                      <td className="px-5 py-3.5 font-serif">{s.name}</td>
                      <td className="px-5 py-3.5 text-muted-foreground">{s.country ?? "—"}</td>
                      <td className="px-5 py-3.5 font-mono">{formatAward(s, lang)}</td>
                      <td className="px-5 py-3.5 font-mono text-muted-foreground">{s.deadline ?? "—"}</td>
                      <td className="px-5 py-3.5">
                        {!s.verified && (
                          <span className="font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
                            {t("funding.unverified")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Agent fee reality check */}
        <section>
          <h2 className="font-serif text-2xl">{t("funding.feecheck")}</h2>
          <form onSubmit={runFeeCheck} className="mt-6 flex max-w-sm gap-2">
            <input
              value={quoted}
              onChange={(e) => setQuoted(e.target.value)}
              type="number"
              min={1}
              placeholder={t("funding.feecheck.quotedlabel")}
              className="focus-ring h-11 flex-1 rounded-[3px] border border-border bg-input-background px-3 text-sm outline-none"
            />
            <button disabled={feeLoading} className="focus-ring h-11 rounded-[3px] bg-primary px-5 text-sm text-primary-foreground disabled:opacity-60">
              {t("funding.feecheck.run")}
            </button>
          </form>

          {feeError && (
            <div className="mt-4 rounded-[3px] border border-destructive/40 bg-destructive/8 p-4 text-sm text-destructive">
              {lang === "en" ? feeError.detail_en : feeError.detail_bn}
            </div>
          )}

          {feeResult && (
            <div className="mt-6 grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] md:grid-cols-2">
              <div className="bg-card p-6">
                <div className="mb-4 flex items-center gap-2 text-destructive">
                  <X className="size-4" />
                  <span className="font-mono text-[0.68rem] uppercase tracking-wider">{t("funding.quoted")}</span>
                </div>
                <div className="font-mono text-4xl text-destructive">{bdt(feeResult.quoted_bdt)}</div>
              </div>
              <div className="bg-card p-6">
                <div className="mb-4 font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">{t("funding.fair")}</div>
                <ul className="space-y-2.5">
                  {feeResult.lines.map((l, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 border-b border-[var(--hairline)] pb-2 text-sm">
                      <span className="flex-1">
                        {lang === "en" ? l.label_en : l.label_bn}{" "}
                        {l.citation && <CitationStamp id={l.citation.snapshot_id} />}
                      </span>
                      <span className="font-mono">{bdt(l.amount_bdt)}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-4 flex items-center justify-between font-mono">
                  <span className="text-[0.68rem] uppercase tracking-wider text-muted-foreground">Fair total</span>
                  <span className="text-2xl text-[var(--gold)]">{bdt(fairTotal)}</span>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
