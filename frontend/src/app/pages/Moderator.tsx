import { useEffect, useState } from "react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { Seo, SEO_ROUTES } from "../lib/seo";
import {
  api,
  qs,
  ApiError,
  type ModOverviewOut,
  type ChangeReviewItem,
  type ChangeCategory,
  type ModAnswerItem,
  type RefusalClusterOut,
  type PortalKind,
  type ModScholarshipOut,
  type ModUserListItem,
  type AdapterOut,
} from "../lib/api";

type Tab = "overview" | "changes" | "answers" | "refusals" | "scholarships" | "users" | "adapters";

const TABS: Tab[] = ["overview", "changes", "answers", "refusals", "scholarships", "users", "adapters"];
const CATEGORIES: ChangeCategory[] = ["deadline", "fee", "document_requirement", "policy", "cosmetic"];
const PORTAL_KINDS: PortalKind[] = ["embassy", "university", "scholarship", "government", "bank"];

export function Moderator() {
  const { t, lang } = useI18n();
  const [tab, setTab] = useState<Tab>("overview");
  const meta = SEO_ROUTES["/moderator"];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("brand.name")} title={t("mod.title")} sub={t("mod.sub")} />

      <div className="mx-auto max-w-[1180px] px-6 py-16 md:px-10">
        <div className="mb-10 flex flex-wrap gap-1 border-b border-[var(--hairline)]">
          {TABS.map((tb) => (
            <button
              key={tb}
              onClick={() => setTab(tb)}
              className={`focus-ring -mb-px border-b-2 px-4 py-2.5 font-mono text-[0.7rem] uppercase tracking-wider transition-colors ${
                tab === tb ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(`mod.tab.${tb}`)}
            </button>
          ))}
        </div>

        {tab === "overview" && <OverviewTab />}
        {tab === "changes" && <ChangesTab />}
        {tab === "answers" && <AnswersTab />}
        {tab === "refusals" && <RefusalsTab />}
        {tab === "scholarships" && <ScholarshipsTab />}
        {tab === "users" && <UsersTab />}
        {tab === "adapters" && <AdaptersTab />}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- */

function LoadingGrid() {
  return (
    <div className="space-y-px overflow-hidden rounded-[4px] border border-[var(--hairline)]" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-16 animate-pulse bg-card" />
      ))}
    </div>
  );
}

function ErrorCard({ error }: { error: ApiError }) {
  const { lang } = useI18n();
  return (
    <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-sm text-muted-foreground">
      {lang === "en" ? error.detail_en : error.detail_bn}
    </div>
  );
}

function EmptyCard() {
  const { t } = useI18n();
  return (
    <div className="rounded-[4px] border border-[var(--hairline)] bg-secondary/40 p-6 text-center text-sm text-muted-foreground">
      {t("mod.empty")}
    </div>
  );
}

/* ---------------------------------------------------------------------- */

function OverviewTab() {
  const { t } = useI18n();
  const [data, setData] = useState<ModOverviewOut | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<ModOverviewOut>("/mod/overview")
      .then((r) => !cancelled && setData(r))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err : null));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <ErrorCard error={error} />;
  if (!data) return <LoadingGrid />;

  const tiles: [string, number][] = [
    [t("mod.overview.pending_changes"), data.pending_changes],
    [t("mod.overview.escalated_answers"), data.escalated_answers],
    [t("mod.overview.unverified_scholarships"), data.unverified_scholarships],
    [t("mod.overview.silent_portals"), data.silent_portals],
    [t("mod.overview.dead_letters"), data.dead_letters],
    [t("mod.overview.adapters_awaiting"), data.adapters_awaiting_promotion],
    [t("mod.overview.new_users"), data.new_users_today],
  ];

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-3 lg:grid-cols-4">
      {tiles.map(([label, value]) => (
        <div key={label} className="bg-card p-6 text-center">
          <div className="font-mono text-3xl text-primary">{value}</div>
          <p className="mt-2 text-xs text-muted-foreground">{label}</p>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------------- */

function ChangesTab() {
  const { t, lang } = useI18n();
  const [items, setItems] = useState<ChangeReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [category, setCategory] = useState<ChangeCategory>("cosmetic");
  const [reason, setReason] = useState("");
  const [notify, setNotify] = useState(true);
  const [mode, setMode] = useState<"approve" | "reclassify" | "discard" | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    api
      .get<{ items: ChangeReviewItem[] }>("/mod/changes?status=pending")
      .then((r) => setItems(r.items))
      .catch((err) => setError(err instanceof ApiError ? err : null))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<{ items: ChangeReviewItem[] }>("/mod/changes?status=pending")
      .then((r) => !cancelled && setItems(r.items))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err : null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  function openAction(id: string, m: "approve" | "reclassify" | "discard", proposed: ChangeCategory | null) {
    setOpenId(id);
    setMode(m);
    setCategory(proposed ?? "cosmetic");
    setReason("");
    setNotify(true);
  }

  async function submit(id: string) {
    try {
      if (mode === "approve") await api.post(`/mod/changes/${id}/approve`, { category, notify });
      else if (mode === "reclassify") await api.post(`/mod/changes/${id}/reclassify`, { category, reason });
      else if (mode === "discard") await api.post(`/mod/changes/${id}/discard`, { reason });
      setItems((prev) => prev.filter((c) => c.id !== id));
      setOpenId(null);
      setMode(null);
    } catch {
      // leave the form open so the moderator can retry
    }
  }

  if (loading) return <LoadingGrid />;
  if (error) return <ErrorCard error={error} />;
  if (items.length === 0) return <EmptyCard />;

  return (
    <ul className="space-y-4">
      {items.map((c) => (
        <li key={c.id} className="rounded-[4px] border border-[var(--hairline)] bg-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="font-serif text-lg">{c.portal_label}</h3>
              <p className="font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
                {c.change_type} · {c.proposed_category ?? "—"}
                {c.confidence !== null && ` · ${t("mod.changes.confidence")} ${Math.round(c.confidence * 100)}%`}
              </p>
            </div>
            <span className="font-mono text-[0.62rem] text-muted-foreground">{c.created_at}</span>
          </div>
          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            {c.old_text && (
              <p className="rounded-[3px] border border-destructive/30 bg-destructive/5 p-3 text-destructive line-through">{c.old_text}</p>
            )}
            {c.new_text && (
              <p className="rounded-[3px] border border-[var(--gold)]/30 bg-[var(--gold)]/5 p-3">{c.new_text}</p>
            )}
          </div>

          {openId !== c.id ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={() => openAction(c.id, "approve", c.proposed_category)} className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground">
                {t("mod.changes.approve")}
              </button>
              <button onClick={() => openAction(c.id, "reclassify", c.proposed_category)} className="focus-ring h-9 rounded-[3px] border border-border px-4 text-xs">
                {t("mod.changes.reclassify")}
              </button>
              <button onClick={() => openAction(c.id, "discard", c.proposed_category)} className="focus-ring h-9 rounded-[3px] border border-destructive/50 px-4 text-xs text-destructive">
                {t("mod.changes.discard")}
              </button>
            </div>
          ) : (
            <div className="mt-4 space-y-3 rounded-[3px] border border-[var(--hairline)] bg-secondary/30 p-4">
              {(mode === "approve" || mode === "reclassify") && (
                <label className="block">
                  <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.category")}</span>
                  <select value={category} onChange={(e) => setCategory(e.target.value as ChangeCategory)} className="focus-ring h-9 w-full max-w-xs rounded-[3px] border border-border bg-input-background px-2 text-sm">
                    {CATEGORIES.map((cat) => (
                      <option key={cat} value={cat}>{cat}</option>
                    ))}
                  </select>
                </label>
              )}
              {mode === "approve" && (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
                  {t("mod.notify")}
                </label>
              )}
              {(mode === "reclassify" || mode === "discard") && (
                <label className="block">
                  <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.reason")}</span>
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="focus-ring w-full rounded-[3px] border border-border bg-input-background px-3 py-2 text-sm" />
                </label>
              )}
              <div className="flex gap-2">
                <button
                  onClick={() => submit(c.id)}
                  disabled={(mode === "reclassify" || mode === "discard") && !reason.trim()}
                  className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground disabled:opacity-60"
                >
                  {t("mod.confirm")}
                </button>
                <button onClick={() => setOpenId(null)} className="focus-ring h-9 rounded-[3px] px-4 text-xs text-muted-foreground">
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/* ---------------------------------------------------------------------- */

function AnswersTab() {
  const { t } = useI18n();
  const [filter, setFilter] = useState<"downvoted" | "escalated" | "low_confidence">("escalated");
  const [items, setItems] = useState<ModAnswerItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [correctingId, setCorrectingId] = useState<string | null>(null);
  const [correctionEn, setCorrectionEn] = useState("");
  const [correctionBn, setCorrectionBn] = useState("");
  const [note, setNote] = useState("");

  function load() {
    setLoading(true);
    setError(null);
    api
      .get<{ items: ModAnswerItem[] }>(`/mod/answers${qs({ filter })}`)
      .then((r) => setItems(r.items))
      .catch((err) => setError(err instanceof ApiError ? err : null))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<{ items: ModAnswerItem[] }>(`/mod/answers${qs({ filter })}`)
      .then((r) => !cancelled && setItems(r.items))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err : null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filter]);

  async function verify(id: string) {
    try {
      await api.post(`/mod/answers/${id}/verify`);
      setItems((prev) => prev.filter((a) => a.id !== id));
    } catch {
      // best-effort
    }
  }

  async function submitCorrection(id: string) {
    if (!correctionEn.trim() || !correctionBn.trim()) return;
    try {
      await api.post(`/mod/answers/${id}/correct`, { correction_en: correctionEn, correction_bn: correctionBn, note: note || null });
      setItems((prev) => prev.filter((a) => a.id !== id));
      setCorrectingId(null);
      setCorrectionEn("");
      setCorrectionBn("");
      setNote("");
    } catch {
      // leave form open
    }
  }

  return (
    <div>
      <label className="mb-6 block max-w-xs">
        <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.filter")}</span>
        <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className="focus-ring h-9 w-full rounded-[3px] border border-border bg-input-background px-2 text-sm">
          <option value="downvoted">{t("mod.filter.downvoted")}</option>
          <option value="escalated">{t("mod.filter.escalated")}</option>
          <option value="low_confidence">{t("mod.filter.low_confidence")}</option>
        </select>
      </label>

      {loading && <LoadingGrid />}
      {!loading && error && <ErrorCard error={error} />}
      {!loading && !error && items.length === 0 && <EmptyCard />}
      {!loading && !error && items.length > 0 && (
        <ul className="space-y-4">
          {items.map((a) => (
            <li key={a.id} className="rounded-[4px] border border-[var(--hairline)] bg-card p-5">
              <p className="font-serif text-base italic">{a.question_text}</p>
              {a.is_refusal ? (
                <p className="mt-2 text-sm text-muted-foreground">refusal</p>
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">{a.answer_en || a.answer_bn}</p>
              )}
              <p className="mt-2 font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
                {a.rating ?? "—"} {a.confidence !== null && `· ${Math.round(a.confidence * 100)}%`}
              </p>

              {correctingId !== a.id ? (
                <div className="mt-4 flex gap-2">
                  <button onClick={() => verify(a.id)} className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground">
                    {t("mod.answers.verify")}
                  </button>
                  <button onClick={() => setCorrectingId(a.id)} className="focus-ring h-9 rounded-[3px] border border-border px-4 text-xs">
                    {t("mod.answers.correct")}
                  </button>
                </div>
              ) : (
                <div className="mt-4 space-y-3 rounded-[3px] border border-[var(--hairline)] bg-secondary/30 p-4">
                  <label className="block">
                    <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.correct.en")}</span>
                    <textarea value={correctionEn} onChange={(e) => setCorrectionEn(e.target.value)} rows={2} className="focus-ring w-full rounded-[3px] border border-border bg-input-background px-3 py-2 text-sm" />
                  </label>
                  <label className="block">
                    <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.correct.bn")}</span>
                    <textarea value={correctionBn} onChange={(e) => setCorrectionBn(e.target.value)} rows={2} className="focus-ring w-full rounded-[3px] border border-border bg-input-background px-3 py-2 text-sm" />
                  </label>
                  <label className="block">
                    <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.correct.note")}</span>
                    <input value={note} onChange={(e) => setNote(e.target.value)} className="focus-ring h-9 w-full rounded-[3px] border border-border bg-input-background px-3 text-sm" />
                  </label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => submitCorrection(a.id)}
                      disabled={!correctionEn.trim() || !correctionBn.trim()}
                      className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground disabled:opacity-60"
                    >
                      {t("mod.confirm")}
                    </button>
                    <button onClick={() => setCorrectingId(null)} className="focus-ring h-9 rounded-[3px] px-4 text-xs text-muted-foreground">
                      {t("common.cancel")}
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------- */

function RefusalsTab() {
  const { t } = useI18n();
  const [items, setItems] = useState<RefusalClusterOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<PortalKind>("government");
  const [country, setCountry] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ items: RefusalClusterOut[] }>("/mod/refusals")
      .then((r) => !cancelled && setItems(r.items))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err : null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(clusterId: string) {
    if (!url.trim()) return;
    try {
      await api.post(`/mod/refusals/${clusterId}/add-portal`, { url, kind, country: country || null });
      setItems((prev) => prev.filter((c) => c.cluster_id !== clusterId));
      setOpenId(null);
      setUrl("");
      setCountry("");
    } catch {
      // leave form open
    }
  }

  if (loading) return <LoadingGrid />;
  if (error) return <ErrorCard error={error} />;
  if (items.length === 0) return <EmptyCard />;

  return (
    <ul className="space-y-4">
      {items.map((c) => (
        <li key={c.cluster_id} className="rounded-[4px] border border-[var(--hairline)] bg-card p-5">
          <p className="font-serif text-base italic">{c.sample_question}</p>
          <p className="mt-2 font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
            {c.count} students · {c.country_filter ?? "—"} · {c.last_asked_at}
          </p>
          {openId !== c.cluster_id ? (
            <button onClick={() => setOpenId(c.cluster_id)} className="focus-ring mt-4 h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground">
              {t("mod.refusals.addportal")}
            </button>
          ) : (
            <div className="mt-4 space-y-3 rounded-[3px] border border-[var(--hairline)] bg-secondary/30 p-4">
              <label className="block">
                <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.addportal.url")}</span>
                <input value={url} onChange={(e) => setUrl(e.target.value)} className="focus-ring h-9 w-full rounded-[3px] border border-border bg-input-background px-3 text-sm" />
              </label>
              <label className="block">
                <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.addportal.kind")}</span>
                <select value={kind} onChange={(e) => setKind(e.target.value as PortalKind)} className="focus-ring h-9 w-full max-w-xs rounded-[3px] border border-border bg-input-background px-2 text-sm">
                  {PORTAL_KINDS.map((k) => (
                    <option key={k} value={k}>{k}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.addportal.country")}</span>
                <input value={country} onChange={(e) => setCountry(e.target.value)} className="focus-ring h-9 w-full max-w-xs rounded-[3px] border border-border bg-input-background px-3 text-sm" />
              </label>
              <div className="flex gap-2">
                <button onClick={() => submit(c.cluster_id)} disabled={!url.trim()} className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground disabled:opacity-60">
                  {t("mod.confirm")}
                </button>
                <button onClick={() => setOpenId(null)} className="focus-ring h-9 rounded-[3px] px-4 text-xs text-muted-foreground">
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/* ---------------------------------------------------------------------- */

function ScholarshipsTab() {
  const { t } = useI18n();
  const [items, setItems] = useState<ModScholarshipOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ items: ModScholarshipOut[] }>("/mod/scholarships?verified=false")
      .then((r) => !cancelled && setItems(r.items))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err : null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  async function verify(id: string, verified: boolean) {
    try {
      await api.post(`/mod/scholarships/${id}/verify`, { verified });
      setItems((prev) => prev.filter((s) => s.id !== id));
    } catch {
      // best-effort
    }
  }

  if (loading) return <LoadingGrid />;
  if (error) return <ErrorCard error={error} />;
  if (items.length === 0) return <EmptyCard />;

  return (
    <ul className="space-y-px overflow-hidden rounded-[4px] border border-[var(--hairline)]">
      {items.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--hairline)] bg-card p-5 last:border-0">
          <div>
            <h3 className="font-serif text-lg">{s.name}</h3>
            <p className="font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
              {s.provider} · {s.country_code ?? "—"} · {s.active ? "active" : "inactive"}
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => verify(s.id, true)} className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground">
              {t("mod.scholarships.verify")}
            </button>
            <button onClick={() => verify(s.id, false)} className="focus-ring h-9 rounded-[3px] border border-border px-4 text-xs">
              {t("mod.scholarships.reject")}
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ---------------------------------------------------------------------- */

function UsersTab() {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<ModUserListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [action, setAction] = useState<"suspend" | "ban" | "reinstate" | null>(null);
  const [reasonEn, setReasonEn] = useState("");
  const [reasonBn, setReasonBn] = useState("");
  const [until, setUntil] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<{ items: ModUserListItem[] }>(`/mod/users${qs({ q: q || undefined })}`)
      .then((r) => !cancelled && setItems(r.items))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err : null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only; search uses form submit
  }, []);

  function load() {
    setLoading(true);
    setError(null);
    api
      .get<{ items: ModUserListItem[] }>(`/mod/users${qs({ q: q || undefined })}`)
      .then((r) => setItems(r.items))
      .catch((err) => setError(err instanceof ApiError ? err : null))
      .finally(() => setLoading(false));
  }

  function openAction(id: string, a: "suspend" | "ban" | "reinstate") {
    setActionId(id);
    setAction(a);
    setReasonEn("");
    setReasonBn("");
    setUntil("");
    setNote("");
  }

  async function submit(id: string) {
    try {
      if (action === "suspend") {
        if (!reasonEn.trim() || !reasonBn.trim() || !until) return;
        await api.post(`/mod/users/${id}/suspend`, { reason_en: reasonEn, reason_bn: reasonBn, until });
      } else if (action === "ban") {
        if (!reasonEn.trim() || !reasonBn.trim()) return;
        await api.post(`/mod/users/${id}/ban`, { reason_en: reasonEn, reason_bn: reasonBn });
      } else if (action === "reinstate") {
        await api.post(`/mod/users/${id}/reinstate`, { note: note || null });
      }
      setActionId(null);
      setAction(null);
      load();
    } catch {
      // leave form open
    }
  }

  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          load();
        }}
        className="mb-6 max-w-sm"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("mod.search.placeholder")}
          className="focus-ring h-10 w-full rounded-[3px] border border-border bg-input-background px-3 text-sm outline-none"
        />
      </form>

      {loading && <LoadingGrid />}
      {!loading && error && <ErrorCard error={error} />}
      {!loading && !error && items.length === 0 && <EmptyCard />}
      {!loading && !error && items.length > 0 && (
        <ul className="space-y-4">
          {items.map((u) => (
            <li key={u.id} className="rounded-[4px] border border-[var(--hairline)] bg-card p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-serif text-lg">{u.display_name}</h3>
                  <p className="font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
                    {u.email} · {u.role} · {u.status}
                    {u.flagged && " · flagged"}
                  </p>
                </div>
                <span className="font-mono text-[0.62rem] text-muted-foreground">
                  {u.question_count} Q · {u.document_count} docs
                </span>
              </div>

              {actionId !== u.id ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  <button onClick={() => openAction(u.id, "suspend")} className="focus-ring h-9 rounded-[3px] border border-border px-4 text-xs">
                    {t("mod.users.suspend")}
                  </button>
                  <button onClick={() => openAction(u.id, "ban")} className="focus-ring h-9 rounded-[3px] border border-destructive/50 px-4 text-xs text-destructive">
                    {t("mod.users.ban")}
                  </button>
                  <button onClick={() => openAction(u.id, "reinstate")} className="focus-ring h-9 rounded-[3px] border border-border px-4 text-xs">
                    {t("mod.users.reinstate")}
                  </button>
                </div>
              ) : (
                <div className="mt-4 space-y-3 rounded-[3px] border border-[var(--hairline)] bg-secondary/30 p-4">
                  {(action === "suspend" || action === "ban") && (
                    <>
                      <label className="block">
                        <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.reason.en")}</span>
                        <textarea value={reasonEn} onChange={(e) => setReasonEn(e.target.value)} rows={2} className="focus-ring w-full rounded-[3px] border border-border bg-input-background px-3 py-2 text-sm" />
                      </label>
                      <label className="block">
                        <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.reason.bn")}</span>
                        <textarea value={reasonBn} onChange={(e) => setReasonBn(e.target.value)} rows={2} className="focus-ring w-full rounded-[3px] border border-border bg-input-background px-3 py-2 text-sm" />
                      </label>
                    </>
                  )}
                  {action === "suspend" && (
                    <label className="block">
                      <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.until")}</span>
                      <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className="focus-ring h-9 rounded-[3px] border border-border bg-input-background px-3 text-sm" />
                    </label>
                  )}
                  {action === "reinstate" && (
                    <label className="block">
                      <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.note")}</span>
                      <input value={note} onChange={(e) => setNote(e.target.value)} className="focus-ring h-9 w-full rounded-[3px] border border-border bg-input-background px-3 text-sm" />
                    </label>
                  )}
                  <div className="flex gap-2">
                    <button
                      onClick={() => submit(u.id)}
                      disabled={
                        (action === "ban" && (!reasonEn.trim() || !reasonBn.trim())) ||
                        (action === "suspend" && (!reasonEn.trim() || !reasonBn.trim() || !until))
                      }
                      className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground disabled:opacity-60"
                    >
                      {t("mod.confirm")}
                    </button>
                    <button onClick={() => setActionId(null)} className="focus-ring h-9 rounded-[3px] px-4 text-xs text-muted-foreground">
                      {t("common.cancel")}
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------- */

function AdaptersTab() {
  const { t } = useI18n();
  const [items, setItems] = useState<AdapterOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [rollingBackId, setRollingBackId] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  function load() {
    setLoading(true);
    api
      .get<{ items: AdapterOut[] }>("/mod/adapters")
      .then((r) => setItems(r.items))
      .catch((err) => setError(err instanceof ApiError ? err : null))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<{ items: AdapterOut[] }>("/mod/adapters")
      .then((r) => !cancelled && setItems(r.items))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err : null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  async function promote(tag: string) {
    try {
      await api.post(`/mod/adapters/${tag}/promote`);
      load();
    } catch {
      // best-effort
    }
  }

  async function rollback(tag: string) {
    if (!reason.trim()) return;
    try {
      await api.post(`/mod/adapters/${tag}/rollback`, { reason });
      setRollingBackId(null);
      setReason("");
      load();
    } catch {
      // leave form open
    }
  }

  if (loading) return <LoadingGrid />;
  if (error) return <ErrorCard error={error} />;
  if (items.length === 0) return <EmptyCard />;

  return (
    <ul className="space-y-4">
      {items.map((a) => (
        <li key={a.id} className="rounded-[4px] border border-[var(--hairline)] bg-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="font-serif text-lg">{a.tag}</h3>
              <p className="font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
                {a.base_model} · rank {a.rank} · {a.sample_count} samples · {a.status}
              </p>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-3 font-mono text-xs text-muted-foreground">
            <span>groundedness {fmtBeforeAfter(a.groundedness_before, a.groundedness_after)}</span>
            <span>refusal {fmtBeforeAfter(a.refusal_correctness_before, a.refusal_correctness_after)}</span>
            <span>bangla {fmtBeforeAfter(a.bangla_clarity_before, a.bangla_clarity_after)}</span>
          </div>

          {a.status === "candidate" && (
            rollingBackId !== a.id ? (
              <div className="mt-4 flex gap-2">
                <button onClick={() => promote(a.id)} className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground">
                  {t("mod.adapters.promote")}
                </button>
                <button onClick={() => setRollingBackId(a.id)} className="focus-ring h-9 rounded-[3px] border border-destructive/50 px-4 text-xs text-destructive">
                  {t("mod.adapters.rollback")}
                </button>
              </div>
            ) : (
              <div className="mt-4 space-y-3 rounded-[3px] border border-[var(--hairline)] bg-secondary/30 p-4">
                <label className="block">
                  <span className="mb-1 block font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">{t("mod.reason")}</span>
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="focus-ring w-full rounded-[3px] border border-border bg-input-background px-3 py-2 text-sm" />
                </label>
                <div className="flex gap-2">
                  <button onClick={() => rollback(a.id)} disabled={!reason.trim()} className="focus-ring h-9 rounded-[3px] bg-primary px-4 text-xs text-primary-foreground disabled:opacity-60">
                    {t("mod.confirm")}
                  </button>
                  <button onClick={() => setRollingBackId(null)} className="focus-ring h-9 rounded-[3px] px-4 text-xs text-muted-foreground">
                    {t("common.cancel")}
                  </button>
                </div>
              </div>
            )
          )}
        </li>
      ))}
    </ul>
  );
}

function fmtBeforeAfter(before: number | null, after: number | null): string {
  const b = before !== null ? Math.round(before * 100) : null;
  const a = after !== null ? Math.round(after * 100) : null;
  if (b === null && a === null) return "—";
  return `${b ?? "—"}% → ${a ?? "—"}%`;
}
