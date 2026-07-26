import { useCallback, useEffect, useRef, useState } from "react";
import { Send, ArrowRight } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { motion, AnimatePresence } from "motion/react";
import { Seo, SEO_ROUTES } from "../lib/seo";
import {
  api,
  openWs,
  ApiError,
  type SessionCreateResponse,
  type QuestionOut,
  type InterviewServerMsg,
  type InterviewReportOut,
  type InterviewPhase,
} from "../lib/api";

type Stage = "idle" | "starting" | "connecting" | "active" | "complete";

export function Interview() {
  const { t, lang } = useI18n();
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState<QuestionOut | null>(null);
  const [phase, setPhase] = useState<InterviewPhase>("idle");
  const [answer, setAnswer] = useState("");
  const [report, setReport] = useState<InterviewReportOut | null>(null);
  const [reportError, setReportError] = useState<ApiError | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const questionCountRef = useRef(0);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  async function start() {
    setStage("starting");
    setError(null);
    try {
      const session = await api.post<SessionCreateResponse>("/interview/sessions", { mode: "text" });
      setSessionId(session.session_id);
      setQuestion(session.first_question);
      questionCountRef.current = 1;
      setStage("connecting");

      const ws = openWs(`/interview/sessions/${session.session_id}/ws`);
      wsRef.current = ws;
      ws.onopen = () => {
        setStage("active");
        setPhase("listening");
      };
      ws.onmessage = (ev) => {
        let msg: InterviewServerMsg;
        try {
          msg = JSON.parse(ev.data as string) as InterviewServerMsg;
        } catch {
          return;
        }
        handleServerMessage(msg);
      };
      ws.onerror = () => {
        setError(
          new ApiError({
            type: "about:blank",
            title: "Connection error",
            status: 0,
            detail_en: "The interview connection was interrupted.",
            detail_bn: "সাক্ষাৎকার সংযোগ বিচ্ছিন্ন হয়ে গেছে।",
          }),
        );
      };
      ws.onclose = () => {
        // no-op: session.complete already moves stage to "complete"
      };
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
      setStage("idle");
    }
  }

  const handleServerMessage = useCallback(
    (msg: InterviewServerMsg) => {
      switch (msg.type) {
        case "phase":
          setPhase(msg.phase);
          break;
        case "question":
          questionCountRef.current += 1;
          setQuestion({ ordinal: msg.ordinal, text_en: msg.text_en, text_bn: msg.text_bn, probes: msg.probes, audio_url: msg.audio_url });
          setAnswer("");
          break;
        case "session.complete":
          setStage("complete");
          setPhase("idle");
          void loadReport(msg.report_id);
          break;
        case "error":
          setError(
            new ApiError({
              type: "about:blank",
              title: "Error",
              status: 0,
              detail_en: msg.detail_en,
              detail_bn: msg.detail_bn,
            }),
          );
          break;
        default:
          break;
      }
    },
    [],
  );

  async function loadReport(reportSessionId: string) {
    setReportError(null);
    try {
      const result = await api.get<InterviewReportOut>(`/interview/sessions/${reportSessionId}/report`);
      setReport(result);
    } catch (err) {
      setReportError(err instanceof ApiError ? err : null);
    }
  }

  function submitAnswer() {
    if (!answer.trim() || phase !== "listening" || !wsRef.current) return;
    wsRef.current.send(JSON.stringify({ type: "answer_text", text: answer.trim() }));
  }

  const progress = Math.min(100, questionCountRef.current * 14);
  const meta = SEO_ROUTES["/interview"];

  return (
    <div className="relative min-h-[calc(100vh-4rem)]">
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />

      {/* progress thread along the page edge */}
      <div className="fixed left-0 top-16 z-30 h-[calc(100vh-4rem)] w-1">
        <motion.div
          className="w-full bg-primary"
          initial={{ height: 0 }}
          animate={{ height: `${stage === "active" ? progress : stage === "complete" ? 100 : 0}%` }}
          transition={{ type: "spring", stiffness: 80, damping: 20 }}
        />
      </div>

      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-2xl flex-col items-center justify-center px-6 py-20 text-center">
        {stage === "idle" || stage === "starting" ? (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
            <div className="mb-5 font-mono text-[0.7rem] uppercase tracking-[0.24em] text-muted-foreground">{t("interview.title")}</div>
            <h1 className="font-serif text-3xl leading-tight md:text-4xl">{t("interview.sub")}</h1>
            {error && (
              <p className="mt-5 text-sm text-destructive">{lang === "en" ? error.detail_en : error.detail_bn}</p>
            )}
            <button
              onClick={start}
              disabled={stage === "starting"}
              className="focus-ring mt-10 inline-flex h-12 items-center gap-2 rounded-[3px] bg-primary px-7 text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {t("interview.start")} <ArrowRight className="size-4" />
            </button>
          </motion.div>
        ) : stage === "connecting" ? (
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{t("interview.connecting")}</p>
        ) : stage === "active" ? (
          <div className="w-full">
            <div className="mb-8 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {t("interview.question")} {String(question?.ordinal ?? questionCountRef.current).padStart(2, "0")}
            </div>
            <AnimatePresence mode="wait">
              <motion.h2
                key={question?.ordinal ?? 0}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -16 }}
                className="mx-auto max-w-xl font-serif text-2xl leading-snug md:text-3xl"
              >
                {question ? (lang === "en" ? question.text_en : question.text_bn) : ""}
              </motion.h2>
            </AnimatePresence>

            <div className="mt-14 flex flex-col items-center gap-5">
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                disabled={phase !== "listening"}
                placeholder={t("interview.typeanswer")}
                rows={3}
                className="focus-ring w-full max-w-xl resize-none rounded-[4px] border border-border bg-input-background px-4 py-3 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
              />
              <button
                onClick={submitAnswer}
                disabled={phase !== "listening" || !answer.trim()}
                className="focus-ring relative flex size-16 items-center justify-center rounded-full border border-primary text-primary transition-colors hover:bg-primary/5 disabled:opacity-40"
                aria-label={t("interview.submit")}
              >
                <Send className="size-6" />
              </button>
              <div className="h-5 font-mono text-xs uppercase tracking-wider text-muted-foreground">
                {phase === "listening" && t("interview.listening")}
                {phase === "thinking" && t("interview.thinking")}
                {phase === "speaking" && t("interview.speaking")}
              </div>
              {error && <p className="text-xs text-destructive">{lang === "en" ? error.detail_en : error.detail_bn}</p>}
            </div>
          </div>
        ) : (
          <Report report={report} error={reportError} />
        )}
      </div>
    </div>
  );
}

function Report({ report, error }: { report: InterviewReportOut | null; error: ApiError | null }) {
  const { t, lang } = useI18n();

  if (error) {
    return (
      <div className="w-full text-left">
        <p className="text-center text-sm text-muted-foreground">{lang === "en" ? error.detail_en : error.detail_bn}</p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="w-full space-y-4" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="grid gap-3 border-b border-[var(--hairline)] pb-6 md:grid-cols-[1fr_2fr]">
            <div className="h-5 w-2/3 animate-pulse rounded-[2px] bg-secondary" />
            <div className="h-10 w-full animate-pulse rounded-[2px] bg-secondary" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full text-left">
      <div className="mb-8 text-center font-mono text-[0.7rem] uppercase tracking-[0.24em] text-muted-foreground">{t("interview.report")}</div>

      <div className="mb-8 flex items-center justify-center gap-2 font-mono text-sm">
        <span className="uppercase tracking-wider text-muted-foreground">{t("interview.overall")}</span>
        <span className="text-2xl text-[var(--gold)]">{Math.round(report.overall * 100)}%</span>
      </div>

      <p className="mb-8 text-center text-sm leading-relaxed text-muted-foreground">
        {lang === "en" ? report.summary_en : report.summary_bn}
      </p>

      <div className="space-y-6">
        {report.turns.map((turn, i) => (
          <motion.div
            key={turn.ordinal}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.1 }}
            className="grid gap-3 border-b border-[var(--hairline)] pb-6 md:grid-cols-[1fr_2fr]"
          >
            <div>
              <h3 className="font-serif text-lg">{lang === "en" ? turn.question_en : turn.question_bn}</h3>
              {turn.relevance !== null && (
                <span className="font-mono text-[0.66rem] uppercase tracking-wider text-[var(--gold)]">
                  {Math.round((turn.relevance ?? 0) * 100)}%
                </span>
              )}
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground md:border-l md:border-[var(--hairline)] md:pl-6">
              {(lang === "en" ? turn.feedback_en : turn.feedback_bn) ?? ""}
            </p>
          </motion.div>
        ))}
      </div>

      {(report.strengths.length > 0 || report.weaknesses.length > 0) && (
        <div className="mt-10 grid gap-8 md:grid-cols-2">
          {report.strengths.length > 0 && (
            <div>
              <h4 className="font-mono text-[0.66rem] uppercase tracking-wider text-[var(--gold)]">{t("interview.strengths")}</h4>
              <ul className="mt-2 space-y-1.5 text-sm text-muted-foreground">
                {report.strengths.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          {report.weaknesses.length > 0 && (
            <div>
              <h4 className="font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">{t("interview.weaknesses")}</h4>
              <ul className="mt-2 space-y-1.5 text-sm text-muted-foreground">
                {report.weaknesses.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
}
