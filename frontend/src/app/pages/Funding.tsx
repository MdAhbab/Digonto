import { useMemo, useState } from "react";
import { Plus, ArrowUpDown, X } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { CitationStamp, motion } from "../components/primitives";

interface Scholarship {
  id: string;
  name: string;
  country: string;
  coverage: number; // % of tuition
  deadline: string;
}

const scholarships: Scholarship[] = [
  { id: "sc1", name: "Commonwealth Master's", country: "UK", coverage: 100, deadline: "2026-10-18" },
  { id: "sc2", name: "Chevening", country: "UK", coverage: 100, deadline: "2026-11-05" },
  { id: "sc3", name: "DAAD EPOS", country: "Germany", coverage: 90, deadline: "2026-09-30" },
  { id: "sc4", name: "Vanier CGS", country: "Canada", coverage: 85, deadline: "2026-11-01" },
  { id: "sc5", name: "Erasmus Mundus JMD", country: "EU", coverage: 100, deadline: "2027-01-15" },
  { id: "sc6", name: "Fulbright Foreign Student", country: "USA", coverage: 95, deadline: "2026-05-31" },
];

interface Source { id: string; label: string; amount: number; color: string; }
const initialSources: Source[] = [
  { id: "f1", label: "Family contribution", amount: 12000, color: "var(--chart-1)" },
  { id: "f2", label: "Scholarship", amount: 18000, color: "var(--chart-2)" },
];
const SOLVENCY_REQUIRED = 34000;

const feeLines = [
  { item: "University application fees (×6)", fair: 420, src: "EXAMPLE-F1" },
  { item: "Credential assessment (WES)", fair: 220, src: "EXAMPLE-F2" },
  { item: "Visa fee + IHS surcharge", fair: 1180, src: "EXAMPLE-F3" },
  { item: "Document courier & attestation", fair: 90, src: "EXAMPLE-F4" },
];

export function Funding() {
  const { t } = useI18n();
  const [sortKey, setSortKey] = useState<keyof Scholarship>("deadline");
  const [asc, setAsc] = useState(true);
  const [sources, setSources] = useState(initialSources);

  const sorted = useMemo(() => {
    return [...scholarships].sort((a, b) => {
      const va = a[sortKey]; const vb = b[sortKey];
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return asc ? cmp : -cmp;
    });
  }, [sortKey, asc]);

  const total = sources.reduce((s, x) => s + x.amount, 0);
  const pct = Math.min(100, (total / SOLVENCY_REQUIRED) * 100);
  const fairTotal = feeLines.reduce((s, l) => s + l.fair, 0);
  const quotedTotal = 4800;

  function addSource() {
    setSources((s) => [...s, { id: `f-${Date.now()}`, label: "Part-time earnings", amount: 4000, color: "var(--chart-3)" }]);
  }

  function sortBy(key: keyof Scholarship) {
    if (key === sortKey) setAsc((a) => !a);
    else { setSortKey(key); setAsc(true); }
  }

  return (
    <div>
      <PageHeader eyebrow={t("agents.khoji.t")} title={t("funding.title")} sub={t("funding.sub")} />

      <div className="mx-auto max-w-[1180px] space-y-16 px-6 py-16 md:px-10">
        {/* Budget composition */}
        <section>
          <h2 className="font-serif text-2xl">{t("funding.budget")}</h2>
          <div className="mt-6 rounded-[4px] border border-[var(--hairline)] bg-card p-6">
            <div className="relative h-12 w-full overflow-hidden rounded-[3px] bg-secondary">
              <div className="flex h-full">
                {sources.map((s) => (
                  <motion.div
                    key={s.id}
                    layout
                    initial={{ width: 0 }}
                    animate={{ width: `${(s.amount / SOLVENCY_REQUIRED) * 100}%` }}
                    transition={{ type: "spring", stiffness: 120, damping: 22 }}
                    style={{ background: s.color }}
                    className="h-full"
                    title={s.label}
                  />
                ))}
              </div>
              {/* solvency threshold */}
              <div className="absolute inset-y-0" style={{ left: "100%" }} />
              <div className="absolute inset-y-0 right-0 flex items-center">
                <div className="h-full w-0.5 bg-foreground" />
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between font-mono text-xs">
              <span className="text-muted-foreground">
                {t("funding.threshold")}: <span className="text-foreground">${SOLVENCY_REQUIRED.toLocaleString()}</span>
              </span>
              <span className={pct >= 100 ? "text-[var(--gold)]" : "text-[var(--amber-status)]"}>
                ${total.toLocaleString()} · {Math.round(pct)}%
              </span>
            </div>
            <div className="mt-5 flex flex-wrap gap-4">
              {sources.map((s) => (
                <span key={s.id} className="flex items-center gap-2 text-sm">
                  <span className="size-3 rounded-[2px]" style={{ background: s.color }} />
                  {s.label} <span className="font-mono text-muted-foreground">${s.amount.toLocaleString()}</span>
                </span>
              ))}
              <button onClick={addSource} className="focus-ring inline-flex items-center gap-1.5 text-sm text-primary">
                <Plus className="size-4" /> {t("funding.add")}
              </button>
            </div>
          </div>
        </section>

        {/* Scholarship broadsheet */}
        <section>
          <h2 className="font-serif text-2xl">{t("funding.scholarships")}</h2>
          <div className="mt-6 overflow-x-auto rounded-[4px] border border-[var(--hairline)]">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--hairline)] bg-secondary/40 text-left">
                  {([["name","funding.col.name"],["country","funding.col.country"],["coverage","funding.col.amount"],["deadline","funding.col.deadline"]] as const).map(([k, lbl]) => (
                    <th key={k} className="px-5 py-3">
                      <button onClick={() => sortBy(k as keyof Scholarship)} className="focus-ring inline-flex items-center gap-1.5 font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground hover:text-foreground">
                        {t(lbl)} <ArrowUpDown className="size-3" />
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((s) => (
                  <tr key={s.id} className="border-b border-[var(--hairline)] last:border-0 hover:bg-secondary/20">
                    <td className="px-5 py-3.5 font-serif">{s.name}</td>
                    <td className="px-5 py-3.5 text-muted-foreground">{s.country}</td>
                    <td className="px-5 py-3.5 font-mono">{s.coverage}%</td>
                    <td className="px-5 py-3.5 font-mono text-muted-foreground">{s.deadline}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Agent fee reality check */}
        <section>
          <h2 className="font-serif text-2xl">{t("funding.feecheck")}</h2>
          <div className="mt-6 grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] md:grid-cols-2">
            <div className="bg-card p-6">
              <div className="mb-4 flex items-center gap-2 text-destructive">
                <X className="size-4" />
                <span className="font-mono text-[0.68rem] uppercase tracking-wider">{t("funding.quoted")}</span>
              </div>
              <div className="font-mono text-4xl text-destructive">${quotedTotal.toLocaleString()}</div>
              <p className="mt-4 text-sm text-muted-foreground">A single opaque “processing package”, no itemisation, no receipts.</p>
            </div>
            <div className="bg-card p-6">
              <div className="mb-4 font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">{t("funding.fair")}</div>
              <ul className="space-y-2.5">
                {feeLines.map((l) => (
                  <li key={l.src} className="flex items-center justify-between gap-3 border-b border-[var(--hairline)] pb-2 text-sm">
                    <span className="flex-1">{l.item} <CitationStamp id={l.src} /></span>
                    <span className="font-mono">${l.fair.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-4 flex items-center justify-between font-mono">
                <span className="text-[0.68rem] uppercase tracking-wider text-muted-foreground">Fair total</span>
                <span className="text-2xl text-[var(--gold)]">${fairTotal.toLocaleString()}</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
