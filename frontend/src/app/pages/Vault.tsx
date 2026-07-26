import { useState } from "react";
import { Lock, FolderClosed, Upload, AlertTriangle, CheckCircle2, FileText } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { motion } from "../components/primitives";
import { Link } from "react-router";

interface Doc {
  id: string;
  nameEn: string;
  nameBn: string;
  count: number;
  expiresDays: number | null; // null = no expiry
  severity: "ok" | "warn" | "error";
  findingEn: string;
  findingBn: string;
  actionEn: string;
  actionBn: string;
}

const docs: Doc[] = [
  { id: "d1", nameEn: "Passport", nameBn: "পাসপোর্ট", count: 1, expiresDays: 190, severity: "warn", findingEn: "Validity is under 12 months at your intended travel date.", findingBn: "আপনার ভ্রমণের তারিখে মেয়াদ ১২ মাসের কম।", actionEn: "Renew before submitting the visa application.", actionBn: "ভিসা আবেদনের আগে নবায়ন করুন।" },
  { id: "d2", nameEn: "Academic transcripts", nameBn: "একাডেমিক ট্রান্সক্রিপ্ট", count: 3, expiresDays: null, severity: "ok", findingEn: "All transcripts attested and legible.", findingBn: "সব ট্রান্সক্রিপ্ট সত্যায়িত ও স্পষ্ট।", actionEn: "No action needed.", actionBn: "কোনো পদক্ষেপ প্রয়োজন নেই।" },
  { id: "d3", nameEn: "IELTS TRF", nameBn: "আইইএলটিএস টিআরএফ", count: 1, expiresDays: 40, severity: "error", findingEn: "Test Report Form expires within your application window.", findingBn: "টেস্ট রিপোর্ট ফর্ম আবেদনের সময়ের মধ্যে মেয়াদোত্তীর্ণ।", actionEn: "Book a retake or request an urgent TRF copy now.", actionBn: "পুনরায় পরীক্ষা বুক করুন বা জরুরি টিআরএফ কপি নিন।" },
  { id: "d4", nameEn: "Bank solvency letter", nameBn: "ব্যাংক সচ্ছলতা পত্র", count: 1, expiresDays: 90, severity: "warn", findingEn: "Dated 45 days ago; some portals want it within 30 days of submission.", findingBn: "৪৫ দিন আগের; কিছু পোর্টাল জমার ৩০ দিনের মধ্যে চায়।", actionEn: "Request a fresh letter closer to submission.", actionBn: "জমার কাছাকাছি নতুন পত্র নিন।" },
];

const sevColor = { ok: "var(--gold)", warn: "var(--amber-status)", error: "var(--destructive)" } as const;

export function Vault() {
  const { t, lang } = useI18n();
  const [dragOver, setDragOver] = useState(false);
  const [settled, setSettled] = useState<string[]>([]);
  const [selected, setSelected] = useState<Doc>(docs[2]);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const id = `drop-${Date.now()}`;
    setSettled((s) => [...s, id]);
  }

  return (
    <div>
      <PageHeader eyebrow={t("agents.prohori.t")} title={t("vault.title")} sub={t("vault.sub")} />

      <div className="mx-auto grid max-w-[1180px] gap-10 px-6 py-16 md:px-10 lg:grid-cols-[1.4fr_1fr]">
        <div>
          {/* Drop desk */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`mb-10 flex flex-col items-center justify-center rounded-[4px] border border-dashed p-10 text-center transition-colors ${
              dragOver ? "border-primary bg-primary/5" : "border-[var(--hairline)]"
            }`}
          >
            <Upload className="mb-3 size-6 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">{t("vault.drop")}</p>
            {settled.length > 0 && (
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {settled.map((s) => (
                  <motion.span
                    key={s}
                    initial={{ y: -14, opacity: 0, rotate: -4 }}
                    animate={{ y: 0, opacity: 1, rotate: 0 }}
                    transition={{ type: "spring", stiffness: 240, damping: 18 }}
                    className="inline-flex items-center gap-1.5 rounded-[3px] border border-[var(--hairline)] bg-card px-3 py-1.5 text-xs"
                  >
                    <FileText className="size-3.5 text-primary" /> new-upload.pdf
                  </motion.span>
                ))}
              </div>
            )}
          </div>

          {/* Folder shelf */}
          <div className="grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-2">
            {docs.map((d) => {
              const tilt = d.expiresDays !== null ? Math.max(0, (120 - d.expiresDays) / 30) : 0;
              return (
                <button
                  key={d.id}
                  onClick={() => setSelected(d)}
                  className={`focus-ring group flex flex-col bg-card p-5 text-left transition-colors hover:bg-secondary/40 ${
                    selected.id === d.id ? "bg-secondary/40" : ""
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <FolderClosed className="size-6 text-primary" />
                    {d.expiresDays !== null && (
                      <span
                        className="inline-flex items-center gap-1 font-mono text-[0.62rem] uppercase tracking-wider"
                        style={{ color: sevColor[d.severity], transform: `rotate(${tilt * 3}deg)` }}
                      >
                        {t("vault.expires")} · {d.expiresDays}d
                      </span>
                    )}
                  </div>
                  <h3 className="mt-4 font-serif text-lg">{lang === "en" ? d.nameEn : d.nameBn}</h3>
                  <div className="mt-2 flex items-center justify-between">
                    <span className="font-mono text-xs text-muted-foreground">{d.count} file{d.count > 1 ? "s" : ""}</span>
                    <span className="inline-flex items-center gap-1 font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                      <Lock className="size-3" /> {t("vault.encrypted")}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Prohori's audit memo */}
        <aside className="lg:sticky lg:top-24 lg:self-start">
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
        </aside>
      </div>
    </div>
  );
}
