import { useState } from "react";
import { AnimatePresence } from "motion/react";
import { CheckCircle2, Circle, Clock, Zap, X, FileText } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { Seal, motion } from "../components/primitives";
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose } from "../components/ui/drawer";

type Status = "done" | "active" | "upcoming";
interface Step {
  id: string;
  month: string;
  titleEn: string;
  titleBn: string;
  descEn: string;
  descBn: string;
  status: Status;
}

const initialSteps: Step[] = [
  { id: "s1", month: "Aug 2026", titleEn: "Shortlist programmes", titleBn: "প্রোগ্রাম বাছাই", descEn: "Pick 6–8 programmes matched to your CGPA and budget.", descBn: "আপনার সিজিপিএ ও বাজেট অনুযায়ী ৬–৮টি প্রোগ্রাম বাছুন।", status: "done" },
  { id: "s2", month: "Sep 2026", titleEn: "Sit IELTS", titleBn: "আইইএলটিএস দিন", descEn: "Register early; band 6.5 overall required for the shortlist.", descBn: "আগে নিবন্ধন করুন; তালিকার জন্য সামগ্রিক ৬.৫ প্রয়োজন।", status: "done" },
  { id: "s3", month: "Oct 2026", titleEn: "Draft SOP & references", titleBn: "এসওপি ও সুপারিশপত্র", descEn: "Two academic references, one statement of purpose per school.", descBn: "প্রতি স্কুলে দুটি একাডেমিক সুপারিশ, একটি উদ্দেশ্য বিবৃতি।", status: "active" },
  { id: "s4", month: "Nov 2026", titleEn: "Submit applications", titleBn: "আবেদন জমা", descEn: "Portal deadlines cluster in mid-November. Submit ahead.", descBn: "পোর্টাল সময়সীমা নভেম্বরের মাঝামাঝি। আগে জমা দিন।", status: "upcoming" },
  { id: "s5", month: "Jan 2027", titleEn: "Arrange funding & solvency", titleBn: "তহবিল ও সচ্ছলতা", descEn: "Bank statement must show the required solvency for 28 days.", descBn: "ব্যাংক স্টেটমেন্টে ২৮ দিন সচ্ছলতা দেখাতে হবে।", status: "upcoming" },
  { id: "s6", month: "Mar 2027", titleEn: "Visa application", titleBn: "ভিসা আবেদন", descEn: "Book biometrics after the CAS/I-20 is issued.", descBn: "CAS/I-20 ইস্যুর পর বায়োমেট্রিক বুক করুন।", status: "upcoming" },
  { id: "s7", month: "Apr 2027", titleEn: "Interview rehearsal", titleBn: "সাক্ষাৎকার মহড়া", descEn: "Run three mock interviews with Shonchari before the real one.", descBn: "আসল সাক্ষাৎকারের আগে সঞ্চারীর সাথে তিনটি মহড়া করুন।", status: "upcoming" },
];

interface ChangeEntry {
  id: string;
  textEn: string;
  textBn: string;
  source: string;
}

export function Planner() {
  const { t, lang } = useI18n();
  const [steps, setSteps] = useState(initialSteps);
  const [changes, setChanges] = useState<ChangeEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  function simulate() {
    // A portal moves the solvency window; the affected step re-flows.
    setSteps((prev) =>
      prev.map((s) =>
        s.id === "s5"
          ? { ...s, month: "Dec 2026", descEn: "Updated: solvency now required for 28 days ending before submission.", descBn: "হালনাগাদ: জমার আগে শেষ হওয়া ২৮ দিনের সচ্ছলতা এখন আবশ্যক।" }
          : s,
      ),
    );
    const entry: ChangeEntry = {
      id: `chg-${Date.now()}`,
      textEn: "A portal moved the solvency window earlier by 30 days. 'Arrange funding' shifted to December.",
      textBn: "একটি পোর্টাল সচ্ছলতার সময়সীমা ৩০ দিন এগিয়ে দিয়েছে। 'তহবিল' ডিসেম্বরে সরেছে।",
      source: "official-portal.example · EXAMPLE-C4",
    };
    setChanges((c) => [entry, ...c]);
    setFlash("s5");
    setTimeout(() => setFlash(null), 1600);
    setOpen(true);
  }

  return (
    <div>
      <PageHeader eyebrow={t("brand.name")} title={t("planner.title")} sub={t("planner.sub")}>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={simulate}
            className="focus-ring inline-flex h-11 items-center gap-2 rounded-[3px] bg-primary px-5 text-primary-foreground transition-opacity hover:opacity-90"
          >
            <Zap className="size-4" />
            {t("planner.simulate")}
          </button>
          <button
            onClick={() => setOpen(true)}
            className="focus-ring inline-flex h-11 items-center gap-2 rounded-[3px] border border-border px-5 transition-colors hover:border-primary"
          >
            <FileText className="size-4" />
            {t("planner.whatchanged")}
            {changes.length > 0 && (
              <span className="ml-1 inline-flex size-5 items-center justify-center rounded-full bg-primary font-mono text-[0.62rem] text-primary-foreground">
                {changes.length}
              </span>
            )}
          </button>
        </div>
      </PageHeader>

      <div className="mx-auto max-w-[1180px] px-6 py-16 md:px-10">
        {/* Legend */}
        <div className="mb-10 flex flex-wrap gap-6 font-mono text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          <span className="flex items-center gap-2"><CheckCircle2 className="size-4 text-[var(--gold)]" />{t("planner.done")}</span>
          <span className="flex items-center gap-2"><Clock className="size-4 text-primary" />{t("planner.active")}</span>
          <span className="flex items-center gap-2"><Circle className="size-4" />{t("planner.upcoming")}</span>
        </div>

        {/* Ledger: fixed month column (desktop) + entries */}
        <div className="relative">
          <div className="absolute bottom-0 left-[7px] top-2 w-px bg-[var(--hairline)] md:left-[128px]" />
          <ul className="space-y-5">
            <AnimatePresence>
              {steps.map((s) => (
                <motion.li
                  key={s.id}
                  layout
                  transition={{ type: "spring", stiffness: 260, damping: 26 }}
                  className="relative grid grid-cols-[auto_1fr] gap-x-5 md:grid-cols-[112px_auto_1fr]"
                >
                  {/* month (desktop fixed column) */}
                  <div className="hidden pt-1 text-right md:block">
                    <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{s.month}</span>
                  </div>
                  {/* node */}
                  <div className="relative z-10 pt-1">
                    {s.status === "done" ? (
                      <Seal className="size-4 shrink-0 !border-[var(--gold)]" />
                    ) : s.status === "active" ? (
                      <span className="flex size-4 items-center justify-center rounded-full border-2 border-primary bg-background">
                        <span className="size-1.5 rounded-full bg-primary" />
                      </span>
                    ) : (
                      <span className="flex size-4 items-center justify-center rounded-full border border-[var(--hairline)] bg-background" />
                    )}
                  </div>
                  {/* entry */}
                  <motion.div
                    animate={flash === s.id ? { backgroundColor: ["var(--gold)", "var(--card)"] } : {}}
                    transition={{ duration: 1.6 }}
                    className={`rounded-[4px] border border-[var(--hairline)] bg-card p-5 ${s.status === "upcoming" ? "opacity-70" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="font-serif text-lg">{lang === "en" ? s.titleEn : s.titleBn}</h3>
                      <span className="font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground md:hidden">{s.month}</span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{lang === "en" ? s.descEn : s.descBn}</p>
                  </motion.div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </div>
      </div>

      {/* What changed drawer */}
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerContent className="bg-card">
          <div className="mx-auto w-full max-w-2xl">
            <DrawerHeader className="flex flex-row items-center justify-between px-6">
              <DrawerTitle className="font-serif text-xl">{t("planner.drawer.title")}</DrawerTitle>
              <DrawerClose className="focus-ring rounded-[3px] p-1"><X className="size-5" /></DrawerClose>
            </DrawerHeader>
            <div className="max-h-[55vh] overflow-y-auto px-6 pb-10">
              {changes.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">{t("planner.drawer.empty")}</p>
              ) : (
                <ul className="space-y-4">
                  {changes.map((c) => (
                    <li key={c.id} className="rounded-[4px] border-l-2 border-primary bg-secondary/50 p-4">
                      <p className="text-sm leading-relaxed">{lang === "en" ? c.textEn : c.textBn}</p>
                      <p className="mt-3 font-mono text-[0.68rem] uppercase tracking-wider text-[var(--gold)]">{c.source}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  );
}
