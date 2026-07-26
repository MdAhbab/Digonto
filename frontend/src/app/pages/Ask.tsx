import { useState, useRef, useEffect, useCallback } from "react";
import { CornerDownLeft, EyeOff } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useAuth } from "../lib/auth";
import { PageHeader } from "../components/PageHeader";
import { CitationStamp, motion } from "../components/primitives";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { Seo, SEO_ROUTES } from "../lib/seo";
import {
  api,
  sse,
  ApiError,
  type Citation,
  type QAItem,
  type AskMetaEvent,
  type AskCitationEvent,
  type AskAltEvent,
  type AskRefusalEvent,
  type AskDoneEvent,
  type SnapshotDetail,
} from "../lib/api";

interface Refusal {
  reason_en: string;
  reason_bn: string;
  watching_portal_ids: string[];
}

interface Exchange {
  id: string;
  q: string;
  answerEn: string;
  answerBn: string;
  citations: Citation[];
  refusal: Refusal | null;
  streaming: boolean;
  error: ApiError | null;
}

function fromHistory(item: QAItem): Exchange {
  return {
    id: item.id,
    q: item.q,
    answerEn: item.answerEn,
    answerBn: item.answerBn,
    citations: item.citations,
    refusal: item.refusal ? { reason_en: "", reason_bn: "", watching_portal_ids: [] } : null,
    streaming: false,
    error: null,
  };
}

export function Ask() {
  const { t, lang } = useI18n();
  const { session } = useAuth();
  const [items, setItems] = useState<Exchange[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<ApiError | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [active, setActive] = useState<{ id: string; loading: boolean; data: SnapshotDetail | null; error: ApiError | null } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const conversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await api.get<{ items: QAItem[] }>("/ask/history");
        if (!cancelled) setItems(page.items.map(fromHistory));
      } catch (err) {
        if (!cancelled) setHistoryError(err instanceof ApiError ? err : null);
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items.length]);

  const onCite = useCallback((snapshotId: string) => {
    setActive({ id: snapshotId, loading: true, data: null, error: null });
    api
      .get<SnapshotDetail>(`/ledger/snapshots/${encodeURIComponent(snapshotId)}`)
      .then((data) => setActive({ id: snapshotId, loading: false, data, error: null }))
      .catch((err) => setActive({ id: snapshotId, loading: false, data: null, error: err instanceof ApiError ? err : null }));
  }, []);

  async function ensureConversation(): Promise<string | undefined> {
    if (conversationIdRef.current) return conversationIdRef.current;
    try {
      const conv = await api.post<{ id: string }>("/ask/conversations", {});
      conversationIdRef.current = conv.id;
      return conv.id;
    } catch {
      return undefined;
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || sending) return;
    const q = input.trim();
    setInput("");
    setSending(true);

    const localId = `qa-${Date.now()}`;
    const citationsByOrdinal: Citation[] = [];
    setItems((prev) => [
      ...prev,
      { id: localId, q, answerEn: "", answerBn: "", citations: [], refusal: null, streaming: true, error: null },
    ]);

    const patch = (fn: (ex: Exchange) => Exchange) => {
      setItems((prev) => prev.map((ex) => (ex.id === localId ? fn(ex) : ex)));
    };

    const conversationId = await ensureConversation();

    try {
      await sse(
        "/ask",
        { question: q, conversation_id: conversationId, lang },
        {
          meta: (_data: AskMetaEvent) => {
            /* answer_id/question_id noted server-side; nothing to render yet */
          },
          token: (data: { t: string }) => {
            patch((ex) =>
              lang === "bn" ? { ...ex, answerBn: ex.answerBn + data.t } : { ...ex, answerEn: ex.answerEn + data.t },
            );
          },
          citation: (data: AskCitationEvent) => {
            citationsByOrdinal[data.ordinal - 1] = {
              id: data.snapshot_id,
              portal: data.portal,
              captured: data.captured,
              quoted: data.quoted,
            };
            patch((ex) => ({ ...ex, citations: [...citationsByOrdinal] }));
          },
          alt: (data: AskAltEvent) => {
            patch((ex) => (data.lang === "bn" ? { ...ex, answerBn: data.text } : { ...ex, answerEn: data.text }));
          },
          refusal: (data: AskRefusalEvent) => {
            patch((ex) => ({
              ...ex,
              streaming: false,
              refusal: { reason_en: data.reason_en, reason_bn: data.reason_bn, watching_portal_ids: data.watching_portal_ids },
            }));
          },
          done: (_data: AskDoneEvent) => {
            patch((ex) => ({ ...ex, streaming: false }));
          },
          error: (data: { detail_en?: string; detail_bn?: string }) => {
            patch((ex) => ({
              ...ex,
              streaming: false,
              error: new ApiError({
                type: "about:blank",
                title: "Error",
                status: 500,
                detail_en: data.detail_en || "Something went wrong while generating the answer.",
                detail_bn: data.detail_bn || "উত্তর তৈরির সময় সমস্যা হয়েছে।",
              }),
            }));
          },
        },
      );
    } catch (err) {
      patch((ex) => ({ ...ex, streaming: false, error: err instanceof ApiError ? err : null }));
    } finally {
      setSending(false);
    }
  }

  const meta = SEO_ROUTES["/ask"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("brand.name")} title={t("ask.title")} sub={t("ask.sub")} />

      <div className="mx-auto max-w-3xl px-6 py-16 md:px-10">
        <div className="space-y-14">
          {historyLoading && (
            <div className="space-y-4" aria-hidden="true">
              {[0, 1].map((i) => (
                <div key={i} className="grid gap-4 md:grid-cols-[1fr_2.4fr]">
                  <div className="md:text-right">
                    <div className="ml-auto h-3 w-24 animate-pulse rounded-[2px] bg-secondary md:ml-auto" />
                  </div>
                  <div className="space-y-2 border-l border-[var(--hairline)] pl-6">
                    <div className="h-3 w-full animate-pulse rounded-[2px] bg-secondary" />
                    <div className="h-3 w-4/5 animate-pulse rounded-[2px] bg-secondary" />
                    <div className="h-3 w-2/3 animate-pulse rounded-[2px] bg-secondary" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {!historyLoading && historyError && (
            <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
              {lang === "en" ? historyError.detail_en : historyError.detail_bn}
            </div>
          )}

          {items.map((qa) => (
            <Exchange key={qa.id} qa={qa} onCite={onCite} />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Composer */}
      <div className="sticky bottom-0 border-t border-[var(--hairline)] bg-background/90 backdrop-blur-md">
        <form onSubmit={submit} className="mx-auto flex max-w-3xl items-end gap-3 px-6 py-4 md:px-10">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) submit(e as unknown as React.FormEvent);
            }}
            rows={1}
            placeholder={t("ask.placeholder")}
            disabled={sending}
            className="focus-ring max-h-32 flex-1 resize-none rounded-[4px] border border-border bg-input-background px-4 py-3 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={sending}
            className="focus-ring inline-flex h-11 items-center gap-2 rounded-[3px] bg-primary px-5 text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {sending ? t("ask.sending") : t("ask.send")}
            <CornerDownLeft className="size-4" />
          </button>
        </form>
      </div>

      {/* Truth Ledger side sheet */}
      <Sheet open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <SheetContent side="right" className="w-[92vw] max-w-md border-l border-[var(--hairline)] bg-card">
          <SheetHeader>
            <SheetTitle className="font-serif text-xl">{t("sheet.title")}</SheetTitle>
          </SheetHeader>
          {active?.loading && (
            <div className="mt-6 space-y-3 px-1" aria-hidden="true">
              <div className="h-3 w-full animate-pulse rounded-[2px] bg-secondary" />
              <div className="h-3 w-3/4 animate-pulse rounded-[2px] bg-secondary" />
              <div className="h-20 w-full animate-pulse rounded-[3px] bg-secondary" />
            </div>
          )}
          {active && !active.loading && active.error && (
            <div className="mt-6 rounded-[3px] border border-[var(--hairline)] p-4 text-sm text-muted-foreground">
              {lang === "en" ? active.error.detail_en : active.error.detail_bn}
            </div>
          )}
          {active && !active.loading && active.data && (
            <div className="mt-6 space-y-6 px-1">
              <dl className="space-y-3 font-mono text-xs">
                <Row label={t("common.snapshot")} value={active.data.id} accent />
                <Row label={t("sheet.portal")} value={active.data.portal} />
                <Row label={t("sheet.captured")} value={active.data.captured} />
              </dl>
              <div>
                <div className="mb-2 font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground">
                  {t("sheet.quoted")}
                </div>
                <blockquote className="rounded-[3px] border-l-2 border-[var(--gold)] bg-[var(--gold)]/8 p-4 text-sm leading-relaxed">
                  “…<mark className="bg-[var(--gold)]/25 px-0.5 text-foreground">{active.data.quoted}</mark>…”
                </blockquote>
              </div>
              <div className="rounded-[3px] border border-[var(--hairline)] p-4 text-xs text-muted-foreground">
                <span className="text-[var(--gold)]">✓ {t("common.verified")}</span> — captured from the official portal and hashed. Anyone can re-verify this snapshot ID on the public Truth Ledger.
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function Row({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--hairline)] pb-2">
      <dt className="uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className={accent ? "text-[var(--gold)]" : ""}>{value}</dd>
    </div>
  );
}

function Exchange({ qa, onCite }: { qa: Exchange; onCite: (snapshotId: string) => void }) {
  const { t, lang } = useI18n();
  const [answerLang, setAnswerLang] = useState(lang);
  const raw = answerLang === "en" ? qa.answerEn : qa.answerBn;

  return (
    <article className="grid gap-4 md:grid-cols-[1fr_2.4fr]">
      {/* margin note = question */}
      <div className="md:text-right">
        <div className="mb-1 font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
          {t("ask.you")}
        </div>
        <p className="font-serif text-base italic leading-relaxed text-foreground/80">{qa.q}</p>
      </div>

      {/* typeset answer */}
      <div className="border-l border-[var(--hairline)] pl-6">
        {qa.refusal ? (
          <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6">
            <div className="mb-3 flex items-center gap-2 text-muted-foreground">
              <EyeOff className="size-4" />
              <span className="font-mono text-[0.7rem] uppercase tracking-wider">{t("ask.refusal.title")}</span>
            </div>
            <p className="text-sm leading-relaxed">
              {qa.refusal.reason_en || qa.refusal.reason_bn
                ? lang === "en"
                  ? qa.refusal.reason_en || qa.refusal.reason_bn
                  : qa.refusal.reason_bn || qa.refusal.reason_en
                : t("ask.refusal.body")}
            </p>
            <p className="mt-4 font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">
              {t("ask.watching")}
            </p>
          </div>
        ) : qa.error ? (
          <div className="rounded-[4px] border border-destructive/40 bg-destructive/8 p-6 text-sm text-destructive">
            {lang === "en" ? qa.error.detail_en : qa.error.detail_bn}
          </div>
        ) : qa.streaming && !raw ? (
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{t("ask.sending")}</p>
        ) : (
          <>
            <div className="mb-3 flex items-center gap-1 text-xs">
              {(["en", "bn"] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => setAnswerLang(l)}
                  className={`focus-ring rounded-[3px] px-2 py-0.5 font-mono uppercase tracking-wider transition-colors ${
                    answerLang === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
            <TypesetAnswer text={raw} citations={qa.citations} onCite={onCite} />
          </>
        )}
      </div>
    </article>
  );
}

/* Renders body text line by line (typeset feel), with ‖n‖ markers becoming citation stamps. */
function TypesetAnswer({ text, citations, onCite }: { text: string; citations: Citation[]; onCite: (snapshotId: string) => void }) {
  const parts = text.split(/(‖\d+‖)/g);
  return (
    <motion.p
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.015 } } }}
      className="text-[0.95rem] leading-[1.85]"
    >
      {parts.map((part, i) => {
        const m = part.match(/‖(\d+)‖/);
        if (m) {
          const c = citations[Number(m[1]) - 1];
          if (!c) return null;
          return <CitationStamp key={i} id={c.id} onClick={() => onCite(c.id)} />;
        }
        return part.split(" ").map((word, j) => (
          <motion.span
            key={`${i}-${j}`}
            variants={{ hidden: { opacity: 0 }, show: { opacity: 1 } }}
            className="mr-[0.26em] inline-block"
          >
            {word}
          </motion.span>
        ));
      })}
    </motion.p>
  );
}
