/**
 * Digonto API client.
 *
 * Talks to the FastAPI backend documented in docs/api_contract.md. A few
 * rules the rest of the app relies on:
 *
 * - The access token lives ONLY in the module-level `accessToken` variable
 *   below. Never localStorage, never sessionStorage: both are readable by
 *   any script on the page, which is exactly what an XSS payload wants.
 * - The refresh token is an HttpOnly cookie the browser holds and sends
 *   automatically; every request therefore uses `credentials: "include"`.
 * - On a 401, we attempt POST /auth/refresh exactly once, then retry the
 *   original request. If refresh fails, the token is cleared and the app is
 *   sent to /auth (see `forceReauth`), except for calls that opt out via
 *   `skipAuthRedirect` (used by the initial session-restore probe, where a
 *   401 simply means "not logged in yet", not "something broke").
 * - Every error is parsed as an RFC 9457 problem+json body into `ApiError`.
 */

// ---------------------------------------------------------------------------
// Base configuration
// ---------------------------------------------------------------------------

export const API_BASE: string =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) ||
  "http://localhost:8000/api/v1";

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

// ---------------------------------------------------------------------------
// Errors: RFC 9457 problem+json
// ---------------------------------------------------------------------------

export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail_en: string;
  detail_bn: string;
  instance?: string | null;
  trace_id?: string | null;
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  type: string;
  title: string;
  detail_en: string;
  detail_bn: string;
  trace_id: string | null;
  instance: string | null;

  constructor(problem: ProblemDetail) {
    super(problem.detail_en || problem.title || "Request failed");
    this.name = "ApiError";
    this.status = problem.status;
    this.type = problem.type;
    this.title = problem.title;
    this.detail_en = problem.detail_en;
    this.detail_bn = problem.detail_bn;
    this.trace_id = problem.trace_id ?? null;
    this.instance = problem.instance ?? null;
  }
}

function networkErrorProblem(status = 0): ProblemDetail {
  return {
    type: "about:blank",
    title: "Network error",
    status,
    detail_en: "Could not reach the server. Check your connection and try again.",
    detail_bn: "সার্ভারে পৌঁছানো যায়নি। আপনার সংযোগ পরীক্ষা করে আবার চেষ্টা করুন।",
  };
}

async function toApiError(res: Response): Promise<ApiError> {
  let problem: ProblemDetail;
  try {
    problem = (await res.json()) as ProblemDetail;
    if (!problem.detail_en) {
      problem = {
        type: problem.type ?? "about:blank",
        title: problem.title ?? res.statusText,
        status: res.status,
        detail_en: "Something went wrong. Please try again.",
        detail_bn: "কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।",
      };
    }
  } catch {
    problem = {
      type: "about:blank",
      title: res.statusText || "Error",
      status: res.status,
      detail_en: "Something went wrong. Please try again.",
      detail_bn: "কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।",
    };
  }
  return new ApiError(problem);
}

// ---------------------------------------------------------------------------
// Unauthorized handling: refresh-once, then hard redirect to /auth
// ---------------------------------------------------------------------------

function forceReauth(): void {
  setAccessToken(null);
  if (typeof window !== "undefined") {
    window.location.assign("/auth");
  }
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!res.ok) return false;
        const data = (await res.json()) as { access_token: string; expires_in: number };
        setAccessToken(data.access_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

const AUTH_PATHS_WITHOUT_RETRY = new Set(["/auth/login", "/auth/signup", "/auth/refresh"]);

// ---------------------------------------------------------------------------
// Core request()
// ---------------------------------------------------------------------------

export interface RequestOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** When true, a failed refresh throws instead of redirecting to /auth.
   * Used by the initial "am I logged in" session probe on app load, where a
   * 401 is an expected, ordinary outcome, not a broken session. */
  skipAuthRedirect?: boolean;
  idempotencyKey?: string;
}

interface InternalRequestOptions extends RequestOptions {
  method: string;
  body?: unknown;
}

async function rawFetch(path: string, opts: InternalRequestOptions): Promise<Response> {
  const headers: Record<string, string> = { ...opts.headers };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

  try {
    return await fetch(`${API_BASE}${path}`, {
      method: opts.method,
      credentials: "include",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch {
    throw new ApiError(networkErrorProblem());
  }
}

async function request<T>(path: string, opts: InternalRequestOptions, retried = false): Promise<T> {
  const res = await rawFetch(path, opts);

  if (res.status === 401 && !retried && !AUTH_PATHS_WITHOUT_RETRY.has(path)) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request<T>(path, opts, true);
    }
    if (opts.skipAuthRedirect) {
      throw await toApiError(res);
    }
    forceReauth();
    throw await toApiError(res);
  }

  if (!res.ok) {
    throw await toApiError(res);
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts, method: "GET" }),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "PUT", body }),
  del: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "DELETE", body }),
};

/** Builds a query string from a params object, skipping null/undefined. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

// ---------------------------------------------------------------------------
// Multipart upload with progress (vault documents)
// ---------------------------------------------------------------------------

function uploadOnce<T>(
  path: string,
  form: FormData,
  onProgress?: (pct: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    xhr.withCredentials = true;
    if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
    xhr.setRequestHeader(
      "Idempotency-Key",
      typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `idem-${Date.now()}-${Math.random()}`,
    );
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(xhr.responseText ? (JSON.parse(xhr.responseText) as T) : (undefined as T));
        } catch {
          resolve(undefined as T);
        }
        return;
      }
      let problem: ProblemDetail;
      try {
        problem = JSON.parse(xhr.responseText) as ProblemDetail;
      } catch {
        problem = {
          type: "about:blank",
          title: xhr.statusText || "Upload failed",
          status: xhr.status,
          detail_en: "The upload failed. Please try again.",
          detail_bn: "আপলোড ব্যর্থ হয়েছে। আবার চেষ্টা করুন।",
        };
      }
      reject(new ApiError(problem));
    };
    xhr.onerror = () => reject(new ApiError(networkErrorProblem()));
    xhr.send(form);
  });
}

export async function uploadDocument<T>(
  path: string,
  file: File,
  fields: Record<string, string>,
  onProgress?: (pct: number) => void,
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [k, v] of Object.entries(fields)) form.append(k, v);

  try {
    return await uploadOnce<T>(path, form, onProgress);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) return uploadOnce<T>(path, form, onProgress);
      forceReauth();
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// SSE: POST-based server-sent events (EventSource cannot POST or set headers)
// ---------------------------------------------------------------------------

// `never` in the parameter position (rather than `any`) is what lets a caller
// pass a map of handlers whose payload types differ per event name (e.g.
// `{ meta: (d: AskMetaEvent) => ..., token: (d: AskTokenEvent) => ... }`) and
// still have each one checked against its own event's real shape: a function
// `(d: T) => void` is assignable to `(d: never) => void` for any T, because
// `never` is assignable to every type in the contravariant parameter check.
export type SseHandlers = Record<string, (data: never) => void>;

async function sseOnce(
  path: string,
  body: unknown,
  handlers: SseHandlers,
  signal: AbortSignal | undefined,
  retried: boolean,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    throw new ApiError(networkErrorProblem());
  }

  if (res.status === 401 && !retried) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return sseOnce(path, body, handlers, signal, true);
    }
    forceReauth();
    throw await toApiError(res);
  }

  if (!res.ok || !res.body) {
    throw await toApiError(res);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex: number;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;
      const dataStr = dataLines.join("\n");
      let parsed: unknown = dataStr;
      try {
        parsed = JSON.parse(dataStr);
      } catch {
        // leave as raw string
      }
      const handler = handlers[eventName];
      if (handler) (handler as (data: unknown) => void)(parsed);
    }
  }
}

/** POST-based SSE. Streams `event:`/`data:` frames from `path` and dispatches
 * each parsed payload to the matching handler in `handlers`, keyed by event
 * name (e.g. "meta", "token", "citation", "alt", "refusal", "done", "error"). */
export function sse(
  path: string,
  body: unknown,
  handlers: SseHandlers,
  opts?: { signal?: AbortSignal },
): Promise<void> {
  return sseOnce(path, body, handlers, opts?.signal, false);
}

// ---------------------------------------------------------------------------
// WebSocket (interview room)
// ---------------------------------------------------------------------------

/** Opens an authenticated WebSocket to `path` (e.g. "/interview/sessions/{id}/ws").
 * The browser WebSocket API cannot set an Authorization header on the
 * handshake, so the access token travels as a `?token=` query parameter,
 * matching the backend's `_authenticate_ws` fallback. */
export function openWs(path: string): WebSocket {
  const wsBase = API_BASE.replace(/^http/, "ws");
  const url = new URL(`${wsBase}${path}`);
  if (accessToken) url.searchParams.set("token", accessToken);
  return new WebSocket(url.toString());
}

// ===========================================================================
// Domain types — mirror app/models/*.py field for field.
// ===========================================================================

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}

// --- auth / user (app/models/user.py, app/models/auth.py) ------------------

export type Role = "student" | "moderator" | "admin";
export type UserStatus = "active" | "suspended" | "banned";
export type LangPref = "bn" | "en";
export type ThemePref = "light" | "dark" | "system";

export interface Consents {
  improve_model: boolean;
  usage_analytics: boolean;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  status: UserStatus;
  lang_pref: LangPref;
  theme_pref: ThemePref;
  created_at: string;
  profile_complete: boolean;
  consents: Consents;
}

export interface AuthResponse {
  access_token: string;
  expires_in: number;
  user: User;
}

// --- ask (app/models/ask.py) ------------------------------------------------

export type AskLang = "bn" | "en";
export type ServedBy = "local" | "cache" | "degraded";

export interface AskRequest {
  question: string;
  conversation_id?: string | null;
  country?: string | null;
  lang?: AskLang | null;
}

export interface AskMetaEvent {
  question_id: string;
  answer_id: string;
  kb_version: number;
  cache_hit: boolean;
  served_by: ServedBy;
}

export interface AskTokenEvent {
  t: string;
}

export interface AskCitationEvent {
  ordinal: number;
  snapshot_id: string;
  portal: string;
  captured: string;
  quoted: string;
}

export interface AskAltEvent {
  lang: AskLang;
  text: string;
}

export interface AskRefusalEvent {
  reason_en: string;
  reason_bn: string;
  watching_portal_ids: string[];
}

export interface AskDoneEvent {
  latency_ms: number;
  first_token_ms: number;
  confidence: number | null;
  tokens: number;
}

/** The one camelCase surface: matches the frontend `QA` shape verbatim. */
export interface Citation {
  id: string;
  portal: string;
  captured: string;
  quoted: string;
}

export interface QAItem {
  id: string;
  q: string;
  answerEn: string;
  answerBn: string;
  citations: Citation[];
  refusal: boolean;
  created_at: string;
}

export type FeedbackRating = "up" | "down" | "unclear";

export interface FeedbackRequest {
  rating: FeedbackRating;
  correction?: string | null;
}

export interface ConversationOut {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

// --- ledger (app/models/ledger.py) ------------------------------------------

export type PortalKind = "embassy" | "university" | "scholarship" | "government" | "bank";
export type PortalStatus = "ok" | "unchanged" | "unreachable" | "parse_failed";
export type ChangeType = "added" | "removed" | "modified";
export type ChangeCategory = "deadline" | "fee" | "document_requirement" | "policy" | "cosmetic";

export interface LedgerPassage {
  ordinal: number;
  section_path: string | null;
  text: string;
}

export interface SnapshotDetail {
  id: string;
  portal: string;
  portal_url: string;
  captured: string;
  content_hash: string;
  http_status: number | null;
  quoted: string | null;
  retired: boolean;
  passages: LedgerPassage[];
}

export interface PortalOut {
  id: string;
  url: string;
  kind: PortalKind;
  country_code: string | null;
  label: string;
  enabled: boolean;
  last_fetch_at: string | null;
  last_status: PortalStatus | null;
  consecutive_failures: number;
}

export interface LedgerChangeOut {
  id: string;
  portal_id: string;
  change_type: ChangeType;
  category: ChangeCategory | null;
  category_confidence: number | null;
  old_text: string | null;
  new_text: string | null;
  created_at: string;
}

// --- planner (app/models/planner.py) ----------------------------------------

export interface SnapshotCitation {
  snapshot_id: string;
  portal?: string | null;
  captured?: string | null;
  quoted?: string | null;
}

export type StepStatus = "done" | "active" | "upcoming" | "blocked";
export type ChangeTrigger = "portal_change" | "profile_update" | "document_change" | "manual" | "schedule";

export interface PlanStepOut {
  id: string;
  step_key: string;
  month: string;
  titleEn: string;
  titleBn: string;
  descEn: string;
  descBn: string;
  status: StepStatus;
  due_at: string | null;
  depends_on: string[];
  citation: SnapshotCitation | null;
}

export interface PlanTimelineOut {
  plan_id: string;
  intake_label: string | null;
  steps: PlanStepOut[];
  unseen_changes: number;
}

export interface PlanChangeOut {
  id: string;
  textEn: string;
  textBn: string;
  source: string;
  trigger: ChangeTrigger;
  step_key: string | null;
  created_at: string;
  seen: boolean;
}

export interface SimulateResponse {
  simulated: true;
  change: PlanChangeOut;
  plan: PlanTimelineOut;
}

// --- vault (app/models/vault.py) --------------------------------------------

export type DocumentKind =
  | "passport"
  | "transcript"
  | "certificate"
  | "bank_statement"
  | "solvency_letter"
  | "english_test"
  | "sop"
  | "recommendation"
  | "offer_letter"
  | "visa_refusal"
  | "consultancy_contract"
  | "photo"
  | "other";
export type DocumentStatus = "uploaded" | "scanning" | "extracted" | "failed" | "quarantined";
export type Severity = "ok" | "warn" | "error";
export type FindingSeverity = "critical" | "warning" | "info";
export type AuditStatus = "queued" | "running" | "complete" | "failed";

export interface DocumentOut {
  id: string;
  kind: DocumentKind;
  nameEn: string;
  nameBn: string;
  count: number;
  expiresDays: number | null;
  severity: Severity;
  findingEn: string;
  findingBn: string;
  actionEn: string;
  actionBn: string;
  status: DocumentStatus;
  uploaded_at: string;
}

export interface DocumentDetail {
  id: string;
  kind: DocumentKind;
  original_name: string;
  mime_type: string;
  byte_size: number;
  page_count: number | null;
  issued_on: string | null;
  expires_on: string | null;
  status: DocumentStatus;
  uploaded_at: string;
}

export interface DocumentDownloadOut {
  url: string;
  expires_at: string;
}

export interface AuditFindingOut {
  id: string;
  document_id: string | null;
  code: string;
  severity: FindingSeverity;
  title_en: string;
  title_bn: string;
  detail_en: string;
  detail_bn: string;
  evidence: Record<string, unknown> | null;
  action_en: string | null;
  action_bn: string | null;
  citation: SnapshotCitation | null;
}

export interface AuditOut {
  id: string;
  status: AuditStatus;
  started_at: string;
  finished_at: string | null;
  findings: AuditFindingOut[];
}

export interface AuditStartResponse {
  audit_id: string;
}

// --- funding (app/models/funding.py) ----------------------------------------

export type CoverageType = "full" | "partial" | "tuition_only" | "stipend_only" | "travel";
export type SortKey = "name" | "country" | "coverage" | "deadline";
export type SortOrder = "asc" | "desc";
export type FeeCategory = "free" | "official_fee" | "fair_service" | "unjustified";
export type SourceKind = "own_funds" | "awards" | "sponsorship" | "loan" | "other";

export interface MatchReasonOut {
  criterion: string;
  met: boolean;
  reason_en: string;
  reason_bn: string;
}

export interface ScholarshipOut {
  id: string;
  name: string;
  country: string | null;
  coverage: number | null;
  deadline: string | null;
  score: number;
  rank: number;
  eligible: boolean;
  verified: boolean;
  reasons: MatchReasonOut[];
  citation: SnapshotCitation | null;
}

export interface ScholarshipDetail extends ScholarshipOut {
  provider: string;
  coverage_type: CoverageType | null;
  amount: number | null;
  currency: string | null;
  url: string;
}

export interface BudgetOut {
  tuition_bdt: number;
  living_bdt: number;
  travel_bdt: number;
  visa_fee_bdt: number;
  awards_bdt: number;
  own_funds_bdt: number;
  gap_bdt: number;
  solvency_required_bdt: number | null;
  fx_rate_used: number | null;
  computed_at: string;
}

export interface FundingSourceCreate {
  kind: SourceKind;
  amount_bdt: number;
}

export interface FundingSourceOut {
  id: string;
  kind: SourceKind;
  label_en: string;
  label_bn: string;
  amount_bdt: number;
}

export interface FeeCheckRequest {
  consultancy?: string | null;
  quoted_bdt?: number | null;
  country?: string | null;
  document_id?: string | null;
}

export interface FeeLineOut {
  label_en: string;
  label_bn: string;
  category: FeeCategory;
  amount_bdt: number;
  note_en?: string | null;
  note_bn?: string | null;
  citation?: SnapshotCitation | null;
}

export interface FeeCheckOut {
  quoted_bdt: number;
  fair_bdt: number | null;
  lines: FeeLineOut[];
}

// --- interview (app/models/interview.py) ------------------------------------

export type InterviewMode = "text" | "voice";
export type SessionStatus = "active" | "complete" | "abandoned";
export type InterviewPhase = "idle" | "listening" | "thinking" | "speaking";

export interface QuestionOut {
  ordinal: number;
  text_en: string;
  text_bn: string;
  probes: string | null;
  audio_url: string | null;
}

export interface SessionCreateResponse {
  session_id: string;
  mode: InterviewMode;
  first_question: QuestionOut;
}

export interface SessionOut {
  id: string;
  mode: InterviewMode;
  status: SessionStatus;
  country_code: string | null;
  visa_type: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface ContradictionOut {
  document_id: string;
  field: string;
  said: string;
  document_says: string;
}

// Server -> client WS messages
export interface TranscriptPartialMsg {
  type: "transcript.partial";
  text: string;
}
export interface TranscriptFinalMsg {
  type: "transcript.final";
  text: string;
  confidence: number;
}
export interface PhaseMsg {
  type: "phase";
  phase: InterviewPhase;
}
export interface ScoreMsg {
  type: "score";
  relevance: number;
  consistency: number;
  credibility: number;
  contradicts: ContradictionOut[];
}
export interface QuestionMsg {
  type: "question";
  ordinal: number;
  text_en: string;
  text_bn: string;
  probes: string | null;
  audio_url: string | null;
}
export interface SessionCompleteMsg {
  type: "session.complete";
  report_id: string;
}
export interface WsErrorMsg {
  type: "error";
  detail_en: string;
  detail_bn: string;
}
export type InterviewServerMsg =
  | TranscriptPartialMsg
  | TranscriptFinalMsg
  | PhaseMsg
  | ScoreMsg
  | QuestionMsg
  | SessionCompleteMsg
  | WsErrorMsg;

// Client -> server WS messages
export interface ClientAnswerText {
  type: "answer_text";
  text: string;
}

export interface TurnGrade {
  ordinal: number;
  question_en: string;
  question_bn: string;
  relevance: number | null;
  consistency: number | null;
  credibility: number | null;
  feedback_en: string | null;
  feedback_bn: string | null;
  contradicts: ContradictionOut[];
}

export interface InterviewReportOut {
  id: string;
  session_id: string;
  overall: number;
  summary_en: string;
  summary_bn: string;
  strengths: string[];
  weaknesses: string[];
  turns: TurnGrade[];
  created_at: string;
}

// --- profile / targets (app/models/profile.py, the slice Funding needs) ----

export type TargetStatus =
  | "considering"
  | "applying"
  | "submitted"
  | "offer"
  | "rejected"
  | "accepted"
  | "withdrawn";

export interface TargetOut {
  id: string;
  programme_id: string;
  programme_name: string;
  institution_name: string;
  country_code: string;
  visa_type: string | null;
  rank: number;
  status: TargetStatus;
  created_at: string;
}

// --- destinations (app/models/destination.py) -------------------------------

export interface DestinationOut {
  id: string;
  name_en: string;
  name_bn: string;
  lat: number;
  lng: number;
  note_en: string;
  note_bn: string;
  visa_types: string[];
  shortlisted: boolean;
  citation: SnapshotCitation | null;
}

// --- meta --------------------------------------------------------------

export interface MetaStatsOut {
  portals_watched: number;
  snapshots_archived: number;
  questions_answered: number;
  citation_rate: number;
  commission_taken_pct: number;
  sdg_aligned: number;
  as_of: string;
}

// --- moderation (app/models/moderation.py) ----------------------------------

export interface ChangeReviewItem {
  id: string;
  portal_id: string;
  portal_label: string;
  change_type: ChangeType;
  old_text: string | null;
  new_text: string | null;
  from_snapshot_id: string;
  to_snapshot_id: string;
  proposed_category: ChangeCategory | null;
  confidence: number | null;
  created_at: string;
}

export interface ApproveChangeRequest {
  category: ChangeCategory;
  notify: boolean;
}
export interface ReclassifyChangeRequest {
  category: ChangeCategory;
  reason: string;
}
export interface DiscardChangeRequest {
  reason: string;
}

export interface ModAnswerItem {
  id: string;
  question_text: string;
  answer_en: string | null;
  answer_bn: string | null;
  confidence: number | null;
  is_refusal: boolean;
  rating: FeedbackRating | null;
  reviewer_verified: boolean;
  created_at: string;
}

export interface CorrectAnswerRequest {
  correction_bn: string;
  correction_en: string;
  note?: string | null;
}

export interface RefusalClusterOut {
  cluster_id: string;
  sample_question: string;
  count: number;
  country_filter: string | null;
  last_asked_at: string;
}

export interface AddPortalFromRefusalRequest {
  url: string;
  kind: PortalKind;
  country?: string | null;
}

export interface ModPortalOut {
  id: string;
  url: string;
  kind: PortalKind;
  country_code: string | null;
  label: string;
  parser_key: string;
  crawl_cron: string;
  enabled: boolean;
  last_fetch_at: string | null;
  last_status: string | null;
  consecutive_failures: number;
}

export interface PortalCreateRequest {
  url: string;
  kind: PortalKind;
  country_code?: string | null;
  label: string;
  parser_key?: string;
  crawl_cron?: string;
}

export interface PortalPatchRequest {
  enabled?: boolean;
  crawl_cron?: string;
  parser_key?: string;
  label?: string;
}

export interface ModScholarshipOut {
  id: string;
  name: string;
  provider: string;
  country_code: string | null;
  verified: boolean;
  active: boolean;
  url: string;
  updated_at: string;
}

export interface VerifyScholarshipRequest {
  verified: boolean;
  note?: string | null;
}

export interface ModUserListItem {
  id: string;
  email: string;
  display_name: string;
  role: string;
  status: UserStatus;
  created_at: string;
  last_seen_at: string | null;
  question_count: number;
  document_count: number;
  flagged: boolean;
}

export interface ModerationActionOut {
  id: string;
  action: string;
  subject_type: string;
  subject_id: string;
  reason_en: string | null;
  reason_bn: string | null;
  created_at: string;
}

export interface ModUserDetail {
  id: string;
  email: string;
  display_name: string;
  role: string;
  status: UserStatus;
  status_reason_en: string | null;
  status_reason_bn: string | null;
  created_at: string;
  last_seen_at: string | null;
  question_count: number;
  document_count: number;
  plan_step_count: number;
  report_count: number;
  moderation_history: ModerationActionOut[];
}

export interface SuspendRequest {
  reason_en: string;
  reason_bn: string;
  until: string;
}
export interface BanRequest {
  reason_en: string;
  reason_bn: string;
}
export interface ReinstateRequest {
  note?: string | null;
}

export type ReportCategory = "wrong_information" | "dishonesty_request" | "abuse" | "privacy" | "other";
export type ReportStatus = "open" | "reviewing" | "resolved" | "dismissed";

export interface UserReportOut {
  id: string;
  subject_type: "answer" | "user" | "scholarship" | "content";
  subject_id: string;
  category: ReportCategory;
  detail: string | null;
  status: ReportStatus;
  created_at: string;
}

export type AdapterStatus = "training" | "candidate" | "promoted" | "rolled_back" | "failed";

export interface AdapterOut {
  id: string;
  tag: string;
  base_model: string;
  rank: number;
  sample_count: number;
  status: AdapterStatus;
  trained_at: string;
  groundedness_before: number | null;
  groundedness_after: number | null;
  refusal_correctness_before: number | null;
  refusal_correctness_after: number | null;
  bangla_clarity_before: number | null;
  bangla_clarity_after: number | null;
}

export interface AdapterRollbackRequest {
  reason: string;
}

export interface ModHealthOut {
  pending_changes: number;
  crawl_failures_48h: number;
  dead_letters: number;
  model_latency_p50_ms: number | null;
  model_latency_p95_ms: number | null;
  queue_depth_agent: number;
}

export interface ModOverviewOut {
  pending_changes: number;
  escalated_answers: number;
  unverified_scholarships: number;
  silent_portals: number;
  dead_letters: number;
  adapters_awaiting_promotion: number;
  new_users_today: number;
}
