import { useState } from "react";
import { Search, ShieldCheck } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { motion } from "../components/primitives";

// Demo verifier. In production each ID resolves to a hashed snapshot of an
// official portal; these entries are illustrative examples only.
const known: Record<string, { portal: string; captured: string; quoted: string }> = {
  "EXAMPLE-2026-DEMO": { portal: "official-portal.example", captured: "demo capture", quoted: "the exact requirement, quoted verbatim from the captured source page" },
};

export function Ledger() {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [result, setResult] = useState<null | { ok: boolean; id: string; data?: typeof known[string] }>(null);

  function verify(e: React.FormEvent) {
    e.preventDefault();
    const id = q.trim().toUpperCase();
    if (!id) return;
    const data = known[id];
    setResult({ ok: !!data, id, data });
  }

  return (
    <div>
      <PageHeader eyebrow={t("nav.ledger")} title={t("ledgerpage.title")} sub={t("ledgerpage.sub")}>
        <form onSubmit={verify} className="flex max-w-md gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("ledgerpage.placeholder")}
              className="focus-ring h-11 w-full rounded-[3px] border border-border bg-input-background pl-9 pr-3 font-mono text-sm outline-none"
            />
          </div>
          <button className="focus-ring h-11 rounded-[3px] bg-primary px-5 text-sm text-primary-foreground">{t("ledgerpage.verify")}</button>
        </form>
      </PageHeader>

      <div className="mx-auto max-w-3xl px-6 py-16 md:px-10">
        {result && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            {result.ok && result.data ? (
              <div className="rounded-[4px] border border-[var(--gold)]/50 bg-[var(--gold)]/6 p-6">
                <div className="mb-4 flex items-center gap-2 text-[var(--gold)]">
                  <ShieldCheck className="size-5" />
                  <span className="font-mono text-xs uppercase tracking-wider">{t("common.verified")} · {result.id}</span>
                </div>
                <dl className="space-y-2.5 font-mono text-xs">
                  <div className="flex justify-between border-b border-[var(--hairline)] pb-2"><dt className="text-muted-foreground uppercase tracking-wider">{t("sheet.portal")}</dt><dd>{result.data.portal}</dd></div>
                  <div className="flex justify-between border-b border-[var(--hairline)] pb-2"><dt className="text-muted-foreground uppercase tracking-wider">{t("sheet.captured")}</dt><dd>{result.data.captured}</dd></div>
                </dl>
                <blockquote className="mt-4 border-l-2 border-[var(--gold)] pl-4 text-sm leading-relaxed">
                  “…<mark className="bg-[var(--gold)]/25 px-0.5 text-foreground">{result.data.quoted}</mark>…”
                </blockquote>
              </div>
            ) : (
              <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6">
                <p className="text-sm text-muted-foreground">No snapshot found for <span className="font-mono text-foreground">{result.id}</span>. Check the ID and try again.</p>
              </div>
            )}
          </motion.div>
        )}
        <div className="mt-10 font-mono text-xs text-muted-foreground">
          Try: <button onClick={() => setQ("EXAMPLE-2026-DEMO")} className="text-[var(--gold)] underline-offset-2 hover:underline">EXAMPLE-2026-DEMO</button>
        </div>
      </div>
    </div>
  );
}
