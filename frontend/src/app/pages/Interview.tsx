import { useState, useEffect } from "react";
import { Mic, Square, ArrowRight } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { motion, AnimatePresence } from "motion/react";

interface Q { en: string; bn: string; }
const questions: Q[] = [
  { en: "Why did you choose this university over others that admitted you?", bn: "যারা আপনাকে ভর্তি নিয়েছে তাদের চেয়ে এই বিশ্ববিদ্যালয় কেন বেছে নিলেন?" },
  { en: "How will you fund your studies and living costs?", bn: "আপনার পড়াশোনা ও জীবনযাত্রার খরচ কীভাবে বহন করবেন?" },
  { en: "What are your plans after you complete the programme?", bn: "প্রোগ্রাম শেষ করার পর আপনার পরিকল্পনা কী?" },
  { en: "What ties you to Bangladesh and ensures your return?", bn: "কোন বন্ধন আপনাকে বাংলাদেশের সাথে যুক্ত রাখে ও ফেরত নিশ্চিত করে?" },
];

type Phase = "idle" | "listening" | "thinking" | "speaking";

export function Interview() {
  const { t, lang } = useI18n();
  const [started, setStarted] = useState(false);
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (phase !== "thinking") return;
    const to = setTimeout(() => setPhase("speaking"), 1400);
    return () => clearTimeout(to);
  }, [phase]);

  const progress = ((idx + (done ? 1 : 0)) / questions.length) * 100;

  function record() {
    setPhase(phase === "listening" ? "thinking" : "listening");
  }
  function next() {
    if (idx < questions.length - 1) {
      setIdx((i) => i + 1);
      setPhase("idle");
    } else {
      setDone(true);
      setPhase("idle");
    }
  }

  return (
    <div className="relative min-h-[calc(100vh-4rem)]">
      {/* progress thread along the page edge */}
      <div className="fixed left-0 top-16 z-30 h-[calc(100vh-4rem)] w-1">
        <motion.div
          className="w-full bg-primary"
          initial={{ height: 0 }}
          animate={{ height: `${progress}%` }}
          transition={{ type: "spring", stiffness: 80, damping: 20 }}
        />
      </div>

      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-2xl flex-col items-center justify-center px-6 py-20 text-center">
        {!started ? (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
            <div className="mb-5 font-mono text-[0.7rem] uppercase tracking-[0.24em] text-muted-foreground">{t("interview.title")}</div>
            <h1 className="font-serif text-3xl leading-tight md:text-4xl">{t("interview.sub")}</h1>
            <button
              onClick={() => setStarted(true)}
              className="focus-ring mt-10 inline-flex h-12 items-center gap-2 rounded-[3px] bg-primary px-7 text-primary-foreground transition-opacity hover:opacity-90"
            >
              {t("interview.start")} <ArrowRight className="size-4" />
            </button>
          </motion.div>
        ) : !done ? (
          <div className="w-full">
            <div className="mb-8 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {String(idx + 1).padStart(2, "0")} / {String(questions.length).padStart(2, "0")}
            </div>
            <AnimatePresence mode="wait">
              <motion.h2
                key={idx}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -16 }}
                className="mx-auto max-w-xl font-serif text-2xl leading-snug md:text-3xl"
              >
                {lang === "en" ? questions[idx].en : questions[idx].bn}
              </motion.h2>
            </AnimatePresence>

            {/* phase expressed through the recording control */}
            <div className="mt-14 flex flex-col items-center gap-5">
              <button
                onClick={record}
                className="focus-ring relative flex size-20 items-center justify-center rounded-full border border-primary text-primary transition-colors hover:bg-primary/5"
                aria-label={phase === "listening" ? t("interview.stop") : t("interview.record")}
              >
                {phase === "listening" ? <Square className="size-6 fill-current" /> : <Mic className="size-7" />}
                {phase === "listening" && (
                  <motion.span
                    className="absolute inset-0 rounded-full border border-primary"
                    animate={{ scale: [1, 1.4], opacity: [0.6, 0] }}
                    transition={{ duration: 1.4, repeat: Infinity }}
                  />
                )}
              </button>
              <div className="h-5 font-mono text-xs uppercase tracking-wider text-muted-foreground">
                {phase === "listening" && t("interview.listening")}
                {phase === "thinking" && t("interview.thinking")}
                {phase === "speaking" && t("interview.speaking")}
              </div>
              {phase === "speaking" && (
                <button onClick={next} className="focus-ring inline-flex items-center gap-2 text-primary">
                  {idx < questions.length - 1 ? t("interview.next") : t("interview.report")} <ArrowRight className="size-4" />
                </button>
              )}
            </div>
          </div>
        ) : (
          <Report />
        )}
      </div>
    </div>
  );
}

function Report() {
  const { t } = useI18n();
  const lines = [
    { q: "Funding clarity", note: "Answer relied on 'family will manage'. Name the exact figures and sources — a visa officer expects specifics.", grade: "Needs work" },
    { q: "Ties to home", note: "Strong: you named a concrete job offer and family business. Keep this.", grade: "Strong" },
    { q: "Programme fit", note: "Good, but connect two named modules to your career goal for a sharper story.", grade: "Fair" },
  ];
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full text-left">
      <div className="mb-8 text-center font-mono text-[0.7rem] uppercase tracking-[0.24em] text-muted-foreground">{t("interview.report")}</div>
      <div className="space-y-6">
        {lines.map((l, i) => (
          <motion.div
            key={l.q}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.15 }}
            className="grid gap-3 border-b border-[var(--hairline)] pb-6 md:grid-cols-[1fr_2fr]"
          >
            <div>
              <h3 className="font-serif text-lg">{l.q}</h3>
              <span className="font-mono text-[0.66rem] uppercase tracking-wider text-[var(--gold)]">{l.grade}</span>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground md:border-l md:border-[var(--hairline)] md:pl-6">{l.note}</p>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}
