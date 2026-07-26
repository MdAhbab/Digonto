/**
 * Shown on every page while a deletion request is inside its 30-day window.
 *
 * The point is that a student should not have to remember they asked. Scheduling
 * deletion signs every session out, so the most likely way back in is somebody
 * signing in weeks later with no memory of the request and no idea their documents
 * are about to go. This states the date and offers one button to stop it.
 *
 * Deliberately not dismissible. A notice that can be closed is a notice that gets
 * closed, and the consequence here is permanent.
 */

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { api } from "../lib/api";
import { useAuth } from "../lib/auth-context";
import { useI18n } from "../lib/i18n-context";

function formatDate(iso: string, lang: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString(lang === "bn" ? "bn-BD" : "en-GB", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default function DeletionBanner() {
  const { session, refreshSession } = useAuth();
  const { t, lang } = useI18n();
  const [cancelling, setCancelling] = useState(false);
  const [done, setDone] = useState(false);

  const scheduledFor = session?.deletion_scheduled_for;
  if (!scheduledFor && !done) return null;

  async function cancel() {
    setCancelling(true);
    try {
      await api.post("/me/deletion/cancel");
      setDone(true);
      // Re-read the account so `deletion_scheduled_for` clears everywhere at once
      // rather than only inside this component.
      await refreshSession();
    } finally {
      setCancelling(false);
    }
  }

  if (done) {
    return (
      <div role="status" className="border-b border-[var(--hairline)] bg-card px-4 py-3 text-center text-sm">
        {t("del.cancelled")}
      </div>
    );
  }

  return (
    <div
      role="alert"
      className="border-b border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
    >
      <div className="mx-auto flex max-w-5xl flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden="true" />
          <div>
            <p className="font-medium">{t("del.banner.title")}</p>
            <p className="text-muted-foreground">
              {t("del.banner.body").replace("{date}", formatDate(scheduledFor!, lang))}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={cancel}
          disabled={cancelling}
          className="focus-ring shrink-0 rounded-[4px] border border-destructive/50 px-4 py-1.5 disabled:opacity-50"
        >
          {cancelling ? t("del.banner.cancelling") : t("del.banner.cancel")}
        </button>
      </div>
    </div>
  );
}
