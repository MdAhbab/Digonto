/**
 * Your profile: what the agents know about you, editable by you.
 *
 * `GET`/`PATCH /me/profile` existed and worked from the first build; nothing in the
 * interface reached them. So the fields every agent reasons from, the CGPA that decides
 * eligibility, the test score that clears a programme, the budget that filters
 * scholarships, could only be set by the demo seed. A signed-in student had no way to
 * tell the system anything about themselves, which is why the answers were generic.
 *
 * The page states what each field is used for rather than just naming it. A student
 * deciding whether to type their budget into a website deserves to know which feature
 * needs it, and "why does it want this" is the question that stops people filling forms
 * in. Every field is optional, and the copy says so: an incomplete profile produces a
 * less specific answer, never a refusal.
 */

import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { Reveal } from "../components/primitives";
import { api, ApiError, type ProfileOut, type ProfilePatch } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Seo, SEO_ROUTES } from "../lib/seo";

const DEGREES = ["bachelor", "master", "phd", "diploma"] as const;
const TESTS = ["ielts", "toefl", "duolingo", "pte", "none"] as const;

/** Empty string means "not answered" and must be sent as null, not as 0.
 *  A profile saying "CGPA 0" describes a student who failed; a profile saying nothing
 *  lets the model say which detail it is missing. */
function num(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

type Draft = Record<string, string>;

function toDraft(p: ProfileOut | null): Draft {
  return {
    display_name: p?.display_name ?? "",
    home_district: p?.home_district ?? "",
    degree_level: p?.degree_level ?? "",
    field_of_study: p?.field_of_study ?? "",
    cgpa: p?.cgpa != null ? String(p.cgpa) : "",
    cgpa_scale: p?.cgpa_scale != null ? String(p.cgpa_scale) : "4",
    graduation_year: p?.graduation_year != null ? String(p.graduation_year) : "",
    english_test: p?.english_test ?? "",
    english_overall: p?.english_overall != null ? String(p.english_overall) : "",
    listening: p?.english_sub?.listening != null ? String(p.english_sub.listening) : "",
    reading: p?.english_sub?.reading != null ? String(p.english_sub.reading) : "",
    writing: p?.english_sub?.writing != null ? String(p.english_sub.writing) : "",
    speaking: p?.english_sub?.speaking != null ? String(p.english_sub.speaking) : "",
    budget_bdt: p?.budget_bdt != null ? String(p.budget_bdt) : "",
    intake_target: p?.intake_target ?? "",
    study_gap_years: p?.study_gap_years != null ? String(p.study_gap_years) : "",
  };
}

export function Profile() {
  const { t, lang } = useI18n();
  const meta = SEO_ROUTES["/profile"];

  const [draft, setDraft] = useState<Draft>(toDraft(null));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await api.get<ProfileOut>("/me/profile");
        if (!cancelled) setDraft(toDraft(p));
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err : null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [key]: e.target.value }));
  };

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const sub = {
      listening: num(draft.listening),
      reading: num(draft.reading),
      writing: num(draft.writing),
      speaking: num(draft.speaking),
    };
    const body: ProfilePatch = {
      display_name: draft.display_name.trim() || null,
      home_district: draft.home_district.trim() || null,
      degree_level: (draft.degree_level || null) as ProfilePatch["degree_level"],
      field_of_study: draft.field_of_study.trim() || null,
      cgpa: num(draft.cgpa),
      cgpa_scale: num(draft.cgpa_scale),
      graduation_year: num(draft.graduation_year),
      english_test: (draft.english_test || null) as ProfilePatch["english_test"],
      english_overall: num(draft.english_overall),
      // Omitted entirely when no band was given, so a blank set of sub-scores does not
      // overwrite stored ones with four nulls.
      english_sub: Object.values(sub).some((v) => v !== null) ? sub : null,
      budget_bdt: num(draft.budget_bdt),
      intake_target: draft.intake_target.trim() || null,
      study_gap_years: num(draft.study_gap_years),
    };
    try {
      const updated = await api.patch<ProfileOut>("/me/profile", body);
      setDraft(toDraft(updated));
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setSaving(false);
    }
  }

  const field = (
    key: string,
    label: string,
    hint: string,
    opts: { type?: string; options?: readonly string[]; placeholder?: string } = {},
  ) => (
    <div>
      <label htmlFor={`p-${key}`} className="block text-xs uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </label>
      {opts.options ? (
        <select
          id={`p-${key}`}
          value={draft[key]}
          onChange={set(key)}
          className="focus-ring mt-2 w-full rounded-[4px] border border-[var(--hairline)] bg-background p-2.5 text-sm"
        >
          <option value="">{t("profile.unset")}</option>
          {opts.options.map((o) => (
            <option key={o} value={o}>
              {t(`profile.opt.${o}`)}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={`p-${key}`}
          type={opts.type ?? "text"}
          inputMode={opts.type === "number" ? "decimal" : undefined}
          value={draft[key]}
          onChange={set(key)}
          placeholder={opts.placeholder}
          className="focus-ring mt-2 w-full rounded-[4px] border border-[var(--hairline)] bg-background p-2.5 text-sm"
        />
      )}
      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{hint}</p>
    </div>
  );

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("profile.eyebrow")} title={t("profile.title")} sub={t("profile.sub")} />

      <div className="mx-auto max-w-[860px] px-6 py-16 md:px-10">
        {loading ? (
          <div className="space-y-3" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-14 animate-pulse rounded-[4px] bg-secondary" />
            ))}
          </div>
        ) : (
          <Reveal>
            <form onSubmit={save} className="space-y-12">
              <section>
                <h2 className="font-serif text-xl">{t("profile.sec.you")}</h2>
                <div className="mt-6 grid gap-6 sm:grid-cols-2">
                  {field("display_name", t("profile.name"), t("profile.name.hint"))}
                  {field("home_district", t("profile.district"), t("profile.district.hint"))}
                </div>
              </section>

              <section>
                <h2 className="font-serif text-xl">{t("profile.sec.study")}</h2>
                <div className="mt-6 grid gap-6 sm:grid-cols-2">
                  {field("degree_level", t("profile.degree"), t("profile.degree.hint"), { options: DEGREES })}
                  {field("field_of_study", t("profile.field"), t("profile.field.hint"))}
                  {field("cgpa", t("profile.cgpa"), t("profile.cgpa.hint"), { type: "number", placeholder: "3.62" })}
                  {field("cgpa_scale", t("profile.scale"), t("profile.scale.hint"), { type: "number", placeholder: "4" })}
                  {field("graduation_year", t("profile.gradyear"), t("profile.gradyear.hint"), { type: "number", placeholder: "2023" })}
                  {field("study_gap_years", t("profile.gap"), t("profile.gap.hint"), { type: "number", placeholder: "0" })}
                </div>
              </section>

              <section>
                <h2 className="font-serif text-xl">{t("profile.sec.english")}</h2>
                <div className="mt-6 grid gap-6 sm:grid-cols-2">
                  {field("english_test", t("profile.test"), t("profile.test.hint"), { options: TESTS })}
                  {field("english_overall", t("profile.overall"), t("profile.overall.hint"), { type: "number", placeholder: "7.0" })}
                </div>
                <div className="mt-6 grid gap-4 sm:grid-cols-4">
                  {field("listening", t("profile.listening"), "", { type: "number" })}
                  {field("reading", t("profile.reading"), "", { type: "number" })}
                  {field("writing", t("profile.writing"), "", { type: "number" })}
                  {field("speaking", t("profile.speaking"), "", { type: "number" })}
                </div>
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  {t("profile.sub.hint")}
                </p>
              </section>

              <section>
                <h2 className="font-serif text-xl">{t("profile.sec.plan")}</h2>
                <div className="mt-6 grid gap-6 sm:grid-cols-2">
                  {field("budget_bdt", t("profile.budget"), t("profile.budget.hint"), { type: "number", placeholder: "2500000" })}
                  {field("intake_target", t("profile.intake"), t("profile.intake.hint"), { placeholder: "Fall 2027" })}
                </div>
              </section>

              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {lang === "en" ? error.detail_en : error.detail_bn}
                </p>
              )}

              <div className="flex items-center gap-4 border-t border-[var(--hairline)] pt-8">
                <button
                  type="submit"
                  disabled={saving}
                  className="focus-ring inline-flex items-center gap-2 rounded-[4px] bg-primary px-6 py-2.5 text-sm text-primary-foreground disabled:opacity-50"
                >
                  {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                  {saving ? t("profile.saving") : t("profile.save")}
                </button>
                {saved && (
                  <span role="status" className="inline-flex items-center gap-2 text-sm text-primary">
                    <Check className="size-4" aria-hidden="true" /> {t("profile.saved")}
                  </span>
                )}
              </div>

              <p className="text-xs leading-relaxed text-muted-foreground">
                {t("profile.privacy")}
              </p>
            </form>
          </Reveal>
        )}
      </div>
    </div>
  );
}

export default Profile;
