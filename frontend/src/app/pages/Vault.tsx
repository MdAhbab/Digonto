import { useEffect, useRef, useState } from "react";
import { Lock, FolderClosed, Upload, AlertTriangle, CheckCircle2, FileText } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { motion } from "../components/primitives";
import { Progress } from "../components/ui/progress";
import { Link } from "react-router";
import { Seo, SEO_ROUTES } from "../lib/seo";
import { api, uploadDocument, ApiError, type DocumentOut, type DocumentKind } from "../lib/api";

const sevColor = { ok: "var(--primary)", warn: "var(--amber-status)", error: "var(--destructive)" } as const;

/* Expiry thresholds, in days.
 *
 * The badge used to appear for every document that had an expiry date at all, so a
 * passport valid for another year and a half was labelled "EXPIRES · 550D" beside one
 * with 45 days left, and neither stood out. A date far enough away is not a warning,
 * it is just a date, and it belongs in the detail panel rather than on the shelf.
 *
 * Its colour also came from `severity`, which is the *audit* verdict on the document,
 * not its expiry. That is why 300 days showed red while 45 days showed gold: the
 * colours were describing something other than the number printed next to them. The
 * badge now derives its own colour from its own number. */
const EXPIRY_NOTICE_DAYS = 180;
const EXPIRY_URGENT_DAYS = 30;
const EXPIRY_WARN_DAYS = 90;

function expiryBadge(
  days: number | null,
): { label: (t: (k: string) => string) => string; colour: string } | null {
  if (days === null || days > EXPIRY_NOTICE_DAYS) return null;
  if (days < 0) {
    // Already expired. Previously rendered as a negative day count, which reads as a
    // rendering fault rather than as the most urgent thing on the page.
    return { label: (t) => t("vault.expired"), colour: "var(--destructive)" };
  }
  const colour =
    days <= EXPIRY_URGENT_DAYS
      ? "var(--destructive)"
      : days <= EXPIRY_WARN_DAYS
        ? "var(--amber-status)"
        : "var(--muted-foreground)";
  return { label: (t) => `${t("vault.expires")} · ${days}d`, colour };
}

const KIND_OPTIONS: DocumentKind[] = [
  "passport",
  "transcript",
  "certificate",
  "bank_statement",
  "solvency_letter",
  "english_test",
  "sop",
  "recommendation",
  "offer_letter",
  "visa_refusal",
  "consultancy_contract",
  "photo",
  "other",
];

interface InFlightUpload {
  id: string;
  name: string;
  progress: number;
  error: ApiError | null;
}

const POLL_MS = 2500;

export function Vault() {
  const { t, lang } = useI18n();
  const [docs, setDocs] = useState<DocumentOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [selected, setSelected] = useState<DocumentOut | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [kind, setKind] = useState<DocumentKind>("passport");
  const [uploads, setUploads] = useState<InFlightUpload[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function loadDocuments(): Promise<DocumentOut[]> {
    const page = await api.get<{ items: DocumentOut[] }>("/vault/documents");
    return page.items;
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const items = await loadDocuments();
        if (cancelled) return;
        setDocs(items);
        setSelected((prev) => prev ?? items[0] ?? null);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err : null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Poll while any document is still being scanned by Prohori, so the card
  // moves from "scanning" to a finished audit result without a manual refresh.
  useEffect(() => {
    const anyScanning = docs.some((d) => d.status === "scanning" || d.status === "uploaded");
    if (!anyScanning) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const items = await loadDocuments();
        setDocs(items);
        setSelected((prev) => (prev ? items.find((d) => d.id === prev.id) ?? prev : items[0] ?? null));
      } catch {
        // transient poll failure: try again on the next tick
      }
    }, POLL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [docs]);

  function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    for (const file of Array.from(files)) uploadOne(file);
  }

  function uploadOne(file: File) {
    const uploadId = `up-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setUploads((u) => [...u, { id: uploadId, name: file.name, progress: 0, error: null }]);

    uploadDocument<DocumentOut>("/vault/documents", file, { kind }, (pct) => {
      setUploads((u) => u.map((x) => (x.id === uploadId ? { ...x, progress: pct } : x)));
    })
      .then((doc) => {
        setUploads((u) => u.filter((x) => x.id !== uploadId));
        setDocs((prev) => {
          const withoutDup = prev.filter((d) => d.id !== doc.id);
          return [doc, ...withoutDup];
        });
        setSelected(doc);
      })
      .catch((err: unknown) => {
        setUploads((u) =>
          u.map((x) => (x.id === uploadId ? { ...x, error: err instanceof ApiError ? err : null } : x)),
        );
      });
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  }

  const meta = SEO_ROUTES["/vault"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("agents.prohori.t")} title={t("vault.title")} sub={t("vault.sub")} />

      <div className="mx-auto grid max-w-[1180px] gap-10 px-6 py-16 md:px-10 lg:grid-cols-[1.4fr_1fr]">
        <div>
          {/* Document kind selector */}
          <label className="mb-3 block">
            <span className="mb-1.5 block font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">
              {t("vault.selectkind")}
            </span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as DocumentKind)}
              className="focus-ring h-10 w-full max-w-xs rounded-[3px] border border-border bg-input-background px-3 text-sm outline-none"
            >
              {KIND_OPTIONS.map((k) => (
                <option key={k} value={k}>
                  {k.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>

          {/* Drop desk */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            className={`mb-10 flex cursor-pointer flex-col items-center justify-center rounded-[4px] border border-dashed p-10 text-center transition-colors ${
              dragOver ? "border-primary bg-primary/5" : "border-[var(--hairline)]"
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.jpg,.jpeg,.png,.heic"
              onChange={(e) => {
                handleFiles(e.target.files);
                e.target.value = "";
              }}
            />
            <Upload className="mb-3 size-6 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">{t("vault.drop")}</p>

            {uploads.length > 0 && (
              <div className="mt-5 w-full max-w-sm space-y-3">
                {uploads.map((u) => (
                  <motion.div
                    key={u.id}
                    initial={{ y: -14, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    className="rounded-[3px] border border-[var(--hairline)] bg-card px-3 py-2 text-left"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="flex items-center gap-1.5 text-xs">
                      <FileText className="size-3.5 shrink-0 text-primary" />
                      <span className="truncate">{u.name}</span>
                    </div>
                    {u.error ? (
                      <p className="mt-1.5 text-xs text-destructive">
                        {lang === "en" ? u.error.detail_en : u.error.detail_bn}
                      </p>
                    ) : (
                      <>
                        <Progress value={u.progress} className="mt-2 h-1.5" />
                        <p className="mt-1 font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                          {t("vault.uploading")} {u.progress}%
                        </p>
                      </>
                    )}
                  </motion.div>
                ))}
              </div>
            )}
          </div>

          {loading && (
            <div className="grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-2" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex flex-col bg-card p-5">
                  <div className="h-6 w-6 animate-pulse rounded-[2px] bg-secondary" />
                  <div className="mt-4 h-5 w-2/3 animate-pulse rounded-[2px] bg-secondary" />
                  <div className="mt-3 h-3 w-1/2 animate-pulse rounded-[2px] bg-secondary" />
                </div>
              ))}
            </div>
          )}

          {!loading && loadError && (
            <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
              {lang === "en" ? loadError.detail_en : loadError.detail_bn}
            </div>
          )}

          {!loading && !loadError && docs.length === 0 && (
            <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-center text-sm text-muted-foreground">
              {t("vault.empty")}
            </div>
          )}

          {/* Folder shelf */}
          {!loading && !loadError && docs.length > 0 && (
            <div className="grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-2">
              {docs.map((d) => {
                const badge = expiryBadge(d.expiresDays);
                const scanning = d.status === "scanning" || d.status === "uploaded";
                return (
                  <button
                    key={d.id}
                    onClick={() => setSelected(d)}
                    className={`focus-ring group flex flex-col bg-card p-5 text-left transition-colors hover:bg-secondary/40 ${
                      selected?.id === d.id ? "bg-secondary/40" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <FolderClosed className="size-6 text-primary" />
                      {badge && (
                        <span
                          className="inline-flex items-center gap-1 font-mono text-[0.62rem] uppercase tracking-wider"
                          style={{ color: badge.colour }}
                        >
                          {badge.label(t)}
                        </span>
                      )}
                    </div>
                    <h3 className="mt-4 font-serif text-lg">{lang === "en" ? d.nameEn : d.nameBn}</h3>
                    <div className="mt-2 flex items-center justify-between">
                      <span className="font-mono text-xs text-muted-foreground">
                        {scanning ? t("vault.scanning") : `${d.count} file${d.count > 1 ? "s" : ""}`}
                      </span>
                      <span className="inline-flex items-center gap-1 font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        <Lock className="size-3" /> {t("vault.encrypted")}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Prohori's audit memo */}
        <aside className="lg:sticky lg:top-24 lg:self-start">
          {selected && (
            <div className="rounded-[4px] border border-[var(--hairline)] bg-card">
              <div className="border-b border-[var(--hairline)] px-6 py-4">
                <div className="font-mono text-[0.68rem] uppercase tracking-[0.2em] text-muted-foreground">{t("vault.audit")}</div>
                <h3 className="mt-1 font-serif text-xl">{lang === "en" ? selected.nameEn : selected.nameBn}</h3>
              </div>
              <div className="space-y-5 p-6">
                <div className="flex items-center gap-2" style={{ color: sevColor[selected.severity] }}>
                  {selected.severity === "ok" ? <CheckCircle2 className="size-5" /> : <AlertTriangle className="size-5" />}
                  <span className="font-mono text-xs uppercase tracking-wider">
                    {selected.severity === "ok" ? "Clear" : selected.severity === "warn" ? "Attention" : "Urgent"}
                  </span>
                </div>
                <div>
                  <div className="mb-1 font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">{t("vault.finding")}</div>
                  <p className="text-sm leading-relaxed">{lang === "en" ? selected.findingEn : selected.findingBn}</p>
                </div>
                <div>
                  <div className="mb-1 font-mono text-[0.66rem] uppercase tracking-wider text-muted-foreground">{t("vault.action")}</div>
                  <p className="text-sm leading-relaxed">{lang === "en" ? selected.actionEn : selected.actionBn}</p>
                </div>
                <Link to="/security" className="focus-ring inline-flex items-center gap-1.5 border-t border-[var(--hairline)] pt-4 font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">
                  <Lock className="size-3" /> {t("vault.encrypted")} →
                </Link>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
