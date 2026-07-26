import { useState, useRef, useEffect } from "react";
import { CornerDownLeft, EyeOff } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { CitationStamp, motion } from "../components/primitives";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";

interface Citation {
  id: string;
  portal: string;
  captured: string;
  quoted: string;
}

interface QA {
  id: string;
  q: string;
  answerEn: string;
  answerBn: string;
  citations: Citation[];
  refusal?: boolean;
}

// Demo exchange showing the UI pattern. Content is illustrative, not a real
// verified fact — a live backend would stream cited answers from official portals.
const seed: QA[] = [
  {
    id: "qa1",
    q: "How does an answer from Digonto look?",
    answerEn:
      "Every answer reads like counsel and footnotes each requirement to the official portal it came from ‖1‖. Where two sources differ, both are shown so you can judge ‖2‖. Digonto never states a requirement it cannot link to a source.",
    answerBn:
      "প্রতিটি উত্তর পরামর্শের মতো পড়া যায় এবং প্রতিটি শর্তের পাদটীকা থাকে যে সরকারি পোর্টাল থেকে এসেছে ‖1‖। দুটি উৎস ভিন্ন হলে দুটোই দেখানো হয়, যাতে আপনি বিচার করতে পারেন ‖2‖। দিগন্ত এমন কোনো শর্ত বলে না যার উৎস দেখাতে পারে না।",
    citations: [
      { id: "EXAMPLE-1", portal: "official-portal.example", captured: "demo", quoted: "the exact requirement, quoted verbatim from the source page" },
      { id: "EXAMPLE-2", portal: "second-source.example", captured: "demo", quoted: "a differing requirement, shown side by side for comparison" },
    ],
  },
  {
    id: "qa2",
    q: "What if the answer isn't published anywhere official yet?",
    answerEn: "",
    answerBn: "",
    citations: [],
    refusal: true,
  },
];

export function Ask() {
  const { t, lang } = useI18n();
  const [items, setItems] = useState<QA[]>(seed);
  const [input, setInput] = useState("");
  const [active, setActive] = useState<Citation | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items.length]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    const q = input.trim();
    setInput("");
    // Mock: unknown questions become designed refusals.
    setItems((prev) => [
      ...prev,
      {
        id: `qa-${Date.now()}`,
        q,
        answerEn: "",
        answerBn: "",
        citations: [],
        refusal: true,
      },
    ]);
  }

  return (
    <div>
      <PageHeader eyebrow={t("brand.name")} title={t("ask.title")} sub={t("ask.sub")} />

      <div className="mx-auto max-w-3xl px-6 py-16 md:px-10">
        <div className="space-y-14">
          {items.map((qa) => (
            <Exchange key={qa.id} qa={qa} onCite={setActive} />
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
            className="focus-ring max-h-32 flex-1 resize-none rounded-[4px] border border-border bg-input-background px-4 py-3 text-sm outline-none placeholder:text-muted-foreground"
          />
          <button
            type="submit"
            className="focus-ring inline-flex h-11 items-center gap-2 rounded-[3px] bg-primary px-5 text-primary-foreground transition-opacity hover:opacity-90"
          >
            {t("ask.send")}
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
          {active && (
            <div className="mt-6 space-y-6 px-1">
              <dl className="space-y-3 font-mono text-xs">
                <Row label={t("common.snapshot")} value={active.id} accent />
                <Row label={t("sheet.portal")} value={active.portal} />
                <Row label={t("sheet.captured")} value={active.captured} />
              </dl>
              <div>
                <div className="mb-2 font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground">
                  {t("sheet.quoted")}
                </div>
                <blockquote className="rounded-[3px] border-l-2 border-[var(--gold)] bg-[var(--gold)]/8 p-4 text-sm leading-relaxed">
                  “…<mark className="bg-[var(--gold)]/25 px-0.5 text-foreground">{active.quoted}</mark>…”
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

function Exchange({ qa, onCite }: { qa: QA; onCite: (c: Citation) => void }) {
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
            <p className="text-sm leading-relaxed">{t("ask.refusal.body")}</p>
            <p className="mt-4 font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">
              {t("ask.watching")}
            </p>
          </div>
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
function TypesetAnswer({ text, citations, onCite }: { text: string; citations: Citation[]; onCite: (c: Citation) => void }) {
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
          return <CitationStamp key={i} id={c.id} onClick={() => onCite(c)} />;
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
