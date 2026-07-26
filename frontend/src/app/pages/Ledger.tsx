import { useState } from "react";
import { Search, ShieldCheck } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { motion } from "../components/primitives";
import { Seo, SEO_ROUTES } from "../lib/seo";
import { api, ApiError, type SnapshotDetail } from "../lib/api";

type Result = { kind: "ok"; data: SnapshotDetail } | { kind: "notfound"; id: string } | { kind: "error"; error: ApiError };

export function Ledger() {
  const { t, lang } = useI18n();
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    const id = q.trim().toUpperCase();
    if (!id || loading) return;
    setLoading(true);
    setResult(null);
    try {
      const data = await api.get<SnapshotDetail>(`/ledger/snapshots/${encodeURIComponent(id)}`);
      setResult({ kind: "ok", data });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setResult({ kind: "notfound", id });
      } else if (err instanceof ApiError) {
        setResult({ kind: "error", error: err });
      }
    } finally {
      setLoading(false);
    }
  }

  const meta = SEO_ROUTES["/ledger"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
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
          <button disabled={loading} className="focus-ring h-11 rounded-[3px] bg-primary px-5 text-sm text-primary-foreground disabled:opacity-60">
            {t("ledgerpage.verify")}
          </button>
        </form>
      </PageHeader>

      <div className="mx-auto max-w-3xl px-6 py-16 md:px-10">
        {result && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            {result.kind === "ok" ? (
              <div className="rounded-[4px] border border-[var(--gold)]/50 bg-[var(--gold)]/6 p-6">
                <div className="mb-4 flex items-center gap-2 text-[var(--gold)]">
                  <ShieldCheck className="size-5" />
                  <span className="font-mono text-xs uppercase tracking-wider">{t("common.verified")} · {result.data.id}</span>
                </div>
                <dl className="space-y-2.5 font-mono text-xs">
                  <div className="flex justify-between border-b border-[var(--hairline)] pb-2">
                    <dt className="uppercase tracking-wider text-muted-foreground">{t("sheet.portal")}</dt>
                    <dd>{result.data.portal}</dd>
                  </div>
                  <div className="flex justify-between border-b border-[var(--hairline)] pb-2">
                    <dt className="uppercase tracking-wider text-muted-foreground">{t("sheet.captured")}</dt>
                    <dd>{result.data.captured}</dd>
                  </div>
                </dl>
                {result.data.quoted && (
                  <blockquote className="mt-4 border-l-2 border-[var(--gold)] pl-4 text-sm leading-relaxed">
                    “…<mark className="bg-[var(--gold)]/25 px-0.5 text-foreground">{result.data.quoted}</mark>…”
                  </blockquote>
                )}
                {result.data.passages.length > 0 && (
                  <div className="mt-6 space-y-3 border-t border-[var(--gold)]/30 pt-4">
                    {result.data.passages.map((p) => (
                      <div key={p.ordinal} className="text-sm leading-relaxed text-muted-foreground">
                        {p.section_path && (
                          <p className="mb-1 font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground/80">{p.section_path}</p>
                        )}
                        <p>{p.text}</p>
                      </div>
                    ))}
                  </div>
                )}
                {result.data.retired && (
                  <p className="mt-4 font-mono text-[0.62rem] uppercase tracking-wider text-destructive">retired snapshot</p>
                )}
              </div>
            ) : result.kind === "notfound" ? (
              <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6">
                <p className="text-sm text-muted-foreground">
                  No snapshot found for <span className="font-mono text-foreground">{result.id}</span>. Check the ID and try again.
                </p>
              </div>
            ) : (
              <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6">
                <p className="text-sm text-muted-foreground">{lang === "en" ? result.error.detail_en : result.error.detail_bn}</p>
              </div>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}
