import { useState } from "react";
import { Plus, Check } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import { PageHeader } from "../components/PageHeader";
import { Globe } from "../components/Globe";

interface Country { id: string; name: string; lat: number; lng: number; note: string; }
const countries: Country[] = [
  { id: "uk", name: "United Kingdom", lat: 54, lng: -2, note: "1-year master's, post-study Graduate Route (2 yrs)." },
  { id: "ca", name: "Canada", lat: 56, lng: -106, note: "PGWP up to 3 yrs; strong PR pathway." },
  { id: "de", name: "Germany", lat: 51, lng: 10, note: "Low/no tuition at public universities; 18-mo job seeker visa." },
  { id: "au", name: "Australia", lat: -25, lng: 133, note: "485 Temporary Graduate visa; high living costs." },
  { id: "us", name: "United States", lat: 38, lng: -97, note: "OPT + STEM extension (up to 3 yrs)." },
  { id: "nl", name: "Netherlands", lat: 52, lng: 5, note: "English-taught programmes; orientation year visa." },
];

export function Destinations() {
  const { t } = useI18n();
  const { theme } = useTheme();
  const [shortlist, setShortlist] = useState<string[]>(["uk", "ca"]);

  const toggle = (id: string) =>
    setShortlist((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const targets = countries.map((c) => ({ lat: c.lat, lng: c.lng, active: shortlist.includes(c.id) }));

  return (
    <div>
      <PageHeader eyebrow={t("nav.destinations")} title={t("dest.title")} sub={t("dest.sub")} />

      <div className="mx-auto grid max-w-[1180px] gap-10 px-6 py-16 md:px-10 lg:grid-cols-[1fr_1fr]">
        <div className="lg:sticky lg:top-24 lg:self-start">
          <div className="aspect-square w-full rounded-[4px] border border-[var(--hairline)] bg-card">
            <Globe theme={theme} targets={targets} />
          </div>
          <p className="mt-4 font-mono text-[0.68rem] uppercase tracking-wider text-muted-foreground">
            {t("dest.shortlist")}: {shortlist.length || "—"}
          </p>
        </div>

        <div className="space-y-px overflow-hidden rounded-[4px] border border-[var(--hairline)]">
          {countries.map((c) => {
            const on = shortlist.includes(c.id);
            return (
              <div key={c.id} className="flex items-start justify-between gap-4 border-b border-[var(--hairline)] bg-card p-5 last:border-0">
                <div className="flex-1">
                  <h3 className="font-serif text-lg">{c.name}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{c.note}</p>
                </div>
                <button
                  onClick={() => toggle(c.id)}
                  className={`focus-ring inline-flex h-9 shrink-0 items-center gap-1.5 rounded-[3px] px-3 text-xs transition-colors ${
                    on ? "bg-primary text-primary-foreground" : "border border-border hover:border-primary"
                  }`}
                >
                  {on ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
                  {on ? t("dest.remove") : t("dest.add")}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
