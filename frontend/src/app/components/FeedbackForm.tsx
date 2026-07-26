/**
 * Feedback form. Works signed out, and asks for nothing it does not need.
 *
 * Three deliberate choices, all of them about not collecting things:
 *
 * The email field is optional and never pre-filled from the signed-in account. A
 * student who leaves it blank has chosen not to be contacted about this message, and
 * quietly filling it in from their profile would overrule that.
 *
 * The current route is sent, because "the number on this page is wrong" is only
 * actionable if we know which page. Nothing else about the session is sent: no
 * screen size, no user agent string, no referrer, no timing.
 *
 * The message box has a visible character budget rather than silently truncating at
 * the server, so a student writing a long careful report in Bangla can see the limit
 * before they lose the end of it. Bangla conjuncts cost more bytes than Latin
 * letters, which makes a silent cut more likely and more annoying.
 */

import { useState } from "react";
import { useLocation } from "react-router";
import { Check, Send } from "lucide-react";

import { api } from "../lib/api";
import { useI18n } from "../lib/i18n-context";

const MAX_MESSAGE = 4000;

const KINDS = [
  { value: "confusing", key: "feedback.kind.confusing" },
  { value: "wrong_answer", key: "feedback.kind.wrong" },
  { value: "bug", key: "feedback.kind.bug" },
  { value: "idea", key: "feedback.kind.idea" },
  { value: "praise", key: "feedback.kind.praise" },
  { value: "other", key: "feedback.kind.other" },
] as const;

type State = "idle" | "sending" | "sent" | "error";

export default function FeedbackForm({ compact = false }: { compact?: boolean }) {
  const { t, lang } = useI18n();
  const location = useLocation();
  const [kind, setKind] = useState<string>("confusing");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);

  const remaining = MAX_MESSAGE - message.length;
  const tooLong = remaining < 0;
  const canSend = message.trim().length >= 4 && !tooLong && state !== "sending";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSend) return;
    setState("sending");
    setError(null);
    try {
      await api.post("/feedback", {
        kind,
        message: message.trim(),
        page: location.pathname,
        lang,
        // Sent only when the student typed something. An empty string would be
        // stored as an empty string rather than as "no contact wanted".
        contact_email: email.trim() || null,
      });
      setState("sent");
      setMessage("");
      setEmail("");
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : t("feedback.error"));
    }
  }

  if (state === "sent") {
    return (
      <div
        className="flex items-start gap-3 rounded-[4px] border border-[var(--hairline)] bg-card p-6"
        role="status"
      >
        <Check className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
        <div>
          <p className="font-medium">{t("feedback.thanks")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t("feedback.thanks.detail")}</p>
          <button
            type="button"
            onClick={() => setState("idle")}
            className="focus-ring mt-4 text-sm text-primary underline underline-offset-4"
          >
            {t("feedback.again")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {!compact && (
        <p className="text-sm text-muted-foreground">{t("feedback.intro")}</p>
      )}

      <fieldset>
        <legend className="mb-2 text-xs uppercase tracking-[0.14em] text-muted-foreground">
          {t("feedback.kind.label")}
        </legend>
        <div className="flex flex-wrap gap-2">
          {KINDS.map((k) => (
            <button
              key={k.value}
              type="button"
              onClick={() => setKind(k.value)}
              aria-pressed={kind === k.value}
              className={`focus-ring rounded-[4px] border px-3 py-1.5 text-sm transition-colors ${
                kind === k.value
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-[var(--hairline)] text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(k.key)}
            </button>
          ))}
        </div>
      </fieldset>

      <div>
        <label htmlFor="feedback-message" className="mb-2 block text-xs uppercase tracking-[0.14em] text-muted-foreground">
          {t("feedback.message.label")}
        </label>
        <textarea
          id="feedback-message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={compact ? 3 : 5}
          placeholder={t("feedback.message.placeholder")}
          className="focus-ring w-full rounded-[4px] border border-[var(--hairline)] bg-background p-3 text-sm"
          aria-describedby="feedback-remaining"
        />
        <p
          id="feedback-remaining"
          className={`mt-1 text-right font-mono text-[0.7rem] ${
            tooLong ? "text-destructive" : "text-muted-foreground"
          }`}
        >
          {remaining}
        </p>
      </div>

      <div>
        <label htmlFor="feedback-email" className="mb-2 block text-xs uppercase tracking-[0.14em] text-muted-foreground">
          {t("feedback.email.label")}
        </label>
        <input
          id="feedback-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t("feedback.email.placeholder")}
          autoComplete="email"
          className="focus-ring w-full rounded-[4px] border border-[var(--hairline)] bg-background p-3 text-sm"
          aria-describedby="feedback-email-note"
        />
        <p id="feedback-email-note" className="mt-1 text-xs text-muted-foreground">
          {t("feedback.email.note")}
        </p>
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!canSend}
        className="focus-ring inline-flex items-center gap-2 rounded-[4px] bg-primary px-5 py-2.5 text-sm text-primary-foreground disabled:opacity-40"
      >
        <Send className="size-4" aria-hidden="true" />
        {state === "sending" ? t("feedback.sending") : t("feedback.send")}
      </button>
    </form>
  );
}
