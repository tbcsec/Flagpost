// API client (ARCHITECTURE.md §8).
//
// This is the single low-level transport. Components NEVER import it directly —
// they go through one TanStack Query hook module per domain (lib/hooks/*). It
// attaches the in-memory access token as a Bearer header and, on a 401,
// transparently attempts a single refresh (using the httpOnly refresh cookie)
// and retries once. Concurrent 401s share one in-flight refresh.

import { useAuthStore } from "@/stores/auth";
import type {
  AuthProvider,
  AuthProviderPublic,
  RichTextDoc,
  ProviderPreset,
  Announcement,
  AnnouncementCreate,
  AppNotification,
  NotificationPreferences,
  AuditLogPage,
  AuditLogQuery,
  Attachment,
  AutomationCatalog,
  AutomationRule,
  AutomationRuleInput,
  ChallengeAnalyticsReport,
  TeamAnalyticsReport,
  AiSettings,
  AiSettingsUpdate,
  AiConnectionResult,
  InstanceSettings,
  InstanceSettingsUpdate,
  InstanceConnectionResult,
  ChallengeDeployment,
  ChallengeDeploymentUpdate,
  Instance,
  AiAssistantType,
  AiAvailability,
  AiCompetitionSettings,
  AiCompetitionSettingsUpdate,
  AiConversationDetail,
  AiMessage,
  AiTranscriptDetail,
  AiTranscriptSummary,
  AiUsage,
  SubmissionPage,
  SubmissionQuery,
  QuestionInput,
  SurveyDetail,
  SurveyQuestion,
  SurveyResults,
  SurveySummary,
  Category,
  ChallengeHealth,
  DashboardLayout,
  DashboardLayoutEntry,
  DashboardStats,
  MyStanding,
  RecentSolve,
  Challenge,
  ChallengeCreate,
  ChallengeSolver,
  ChallengeUpdate,
  Competition,
  CompetitionCreate,
  CompetitionRules,
  CompetitionUpdate,
  HelloResponse,
  Hint,
  HintAuthored,
  HintUpdate,
  AdminOverview,
  Award,
  AwardInput,
  CompetitionReport,
  ModuleCatalogEntry,
  ReportCatalog,
  ReportCreate,
  ModuleState,
  MyTeam,
  Participant,
  ApiToken,
  ApiTokenCreated,
  UserAccount,
  UserImportReport,
  AdminPage,
  PageContent,
  PageNavEntry,
  PageWrite,
  Permissions,
  PermissionEntry,
  Role,
  BackupDocument,
  BackupImportResult,
  ChallengeRatingSummary,
  SetupRequest,
  SetupStatus,
  RoleAssignment,
  RulesSettings,
  PublicActivity,
  PublicCompetition,
  PublicInsights,
  PublicScoreboard,
  Scoreboard,
  SignedUrl,
  OperationalSettings,
  OperationalSettingsUpdate,
  SiteSettings,
  SiteSettingsAdmin,
  SubmitResult,
  Team,
  TeamApplication,
  TeamJoinResult,
  TeamUpdate,
  Ticket,
  TicketAttachment,
  TicketDetail,
  TokenResponse,
  User,
  CertificateTemplate,
  CertificateTemplateInput,
  CertificateExportJob,
  CertificateFont,
  CertificateAvailability,
  CertificateManifest,
  MyCertificate,
} from "@/lib/types";

// Baked at build time. Three shapes:
//  - absolute origin (dev default, demo images) — cross-origin API;
//  - **empty string** — same-origin mode: every request goes out relative
//    (`/api/...`) and resolves against the page's own origin, for deployments
//    behind a single-origin proxy (Caddy). The versioned release images bake
//    this, which is what makes one image reproducible on any host.
// `??` (not `||`) keeps the deliberate "" from falling back to localhost.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Absolutize a backend-relative path (e.g. a logo URL) to the API origin, so an
 *  `<img src>` resolves against the backend, not the frontend host. */
export function apiAssetUrl(path: string): string {
  return `${API_URL}${path}`;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The server's structured `detail` payload, when it sent one that isn't a
     *  plain string (e.g. the rules-gate rejection carries the rules document
     *  and competition id). Undefined for string details and non-JSON bodies. */
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let refreshPromise: Promise<boolean> | null = null;

async function runRefresh(): Promise<boolean> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Network error — the backend is unreachable (not running, CORS, offline).
    // Treat it as "not authenticated" rather than letting the rejection surface
    // as an unhandled error on app load; the app falls back to the login screen.
    useAuthStore.getState().clearSession();
    return false;
  }
  if (!res.ok) {
    useAuthStore.getState().clearSession();
    return false;
  }
  const data: TokenResponse = await res.json();
  useAuthStore.getState().setSession(data.access_token, data.user);
  return true;
}

/** Single-flight refresh: concurrent callers await the same attempt. */
function refreshOnce(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = runRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

interface RequestOptions {
  auth?: boolean;
  retryOn401?: boolean;
  /** How to read the response body. `blob` is for binary endpoints (e.g. a
   *  ticket screenshot) that still want the auth + refresh handling below. */
  parse?: "json" | "blob";
}

async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  { auth = true, retryOn401 = true, parse = "json" }: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth) {
    const token = useAuthStore.getState().accessToken;
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  // Let the browser set the multipart boundary for FormData; only default to
  // JSON for other bodies.
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
      credentials: "include",
    });
  } catch {
    // Network error (server unreachable, offline, CORS) — surface a clean
    // ApiError with a user-facing message rather than a raw "Failed to fetch"
    // TypeError or anything that reveals infrastructure detail. Status 0 marks
    // "no response" so callers can distinguish it from an HTTP error.
    throw new ApiError(
      0,
      "Can't reach Flagpost — the service may be offline or your connection may be down. Check your connection and try again in a moment.",
    );
  }

  if (res.status === 401 && retryOn401 && auth) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      return apiFetch<T>(path, init, { auth, retryOn401: false, parse });
    }
  }

  if (!res.ok) {
    const { message, detail } = await extractError(res);
    throw new ApiError(res.status, message, detail);
  }
  if (res.status === 204) return undefined as T;
  if (parse === "blob") return (await res.blob()) as T;
  return res.json() as Promise<T>;
}

// Plain, why-oriented messages for the statuses that don't carry a server
// `detail`. Clear enough to help a user (or support) understand the failure
// without leaking stack traces or infrastructure detail.
const STATUS_MESSAGES: Record<number, string> = {
  400: "That request couldn't be processed — check the details and try again.",
  401: "Your session has expired or isn't valid — please sign in again.",
  403: "You don't have permission to do that.",
  404: "That couldn't be found — it may have been removed or you may not have access.",
  409: "That conflicts with something that already exists.",
  413: "That file is too large to upload.",
  429: "Too many attempts — please wait a moment and try again.",
};

async function extractError(
  res: Response,
): Promise<{ message: string; detail?: unknown }> {
  // Prefer the server's own reason — it's the most specific (e.g. "Incorrect
  // email or password", "A team with that name already exists").
  try {
    const body = await res.json();
    if (typeof body?.detail === "string" && body.detail.trim()) {
      return { message: body.detail };
    }
    // FastAPI validation errors (422) arrive as an array under `detail`.
    if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
      return { message: `Invalid input: ${body.detail[0].msg}` };
    }
    // Structured detail objects: keep the payload for callers that understand
    // it (e.g. the rules gate), and surface its embedded message when present.
    if (body?.detail && typeof body.detail === "object") {
      const msg = (body.detail as { message?: unknown }).message;
      return {
        message:
          typeof msg === "string" && msg.trim()
            ? msg
            : STATUS_MESSAGES[res.status] ??
              `The request failed (error ${res.status}). Please try again.`,
        detail: body.detail,
      };
    }
  } catch {
    /* non-JSON body — fall through to a status-based message */
  }
  if (res.status >= 500) {
    return {
      message:
        "The Flagpost service ran into a problem. Please try again — if it keeps happening, contact an administrator.",
    };
  }
  return {
    message:
      STATUS_MESSAGES[res.status] ??
      `The request failed (error ${res.status}). Please try again.`,
  };
}

// --- Typed endpoint helpers (consumed only by hooks) ------------------------

export const setupApi = {
  // Public: drives the first-run wizard redirect.
  status: () => apiFetch<SetupStatus>("/api/setup/status", {}, { auth: false }),
  complete: (input: SetupRequest) =>
    apiFetch<TokenResponse>(
      "/api/setup",
      { method: "POST", body: JSON.stringify(input) },
      { auth: false },
    ),
};

export const authApi = {
  register: (input: { display_name: string; password: string; email?: string }) =>
    apiFetch<TokenResponse>(
      "/api/auth/register",
      { method: "POST", body: JSON.stringify(input) },
      { auth: false },
    ),
  // `identifier` is the display name (username) or the email address.
  login: (input: { identifier: string; password: string }) =>
    apiFetch<TokenResponse>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify(input) },
      { auth: false },
    ),
  logout: () =>
    apiFetch<void>("/api/auth/logout", { method: "POST" }, { retryOn401: false }),
  me: () => apiFetch<User>("/api/auth/me"),
  permissions: () => apiFetch<Permissions>("/api/auth/me/permissions"),
  changePassword: (input: { current_password: string; new_password: string }) =>
    apiFetch<void>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  forgotPassword: (input: { email: string }) =>
    apiFetch<void>(
      "/api/auth/forgot-password",
      { method: "POST", body: JSON.stringify(input) },
      { auth: false },
    ),
  resetPassword: (input: { token: string; new_password: string }) =>
    apiFetch<void>(
      "/api/auth/reset-password",
      { method: "POST", body: JSON.stringify(input) },
      { auth: false },
    ),
  verifyEmail: (input: { token: string }) =>
    apiFetch<void>(
      "/api/auth/verify-email",
      { method: "POST", body: JSON.stringify(input) },
      { auth: false },
    ),
  resendVerification: () =>
    apiFetch<void>("/api/auth/resend-verification", { method: "POST" }),
  // Enabled external identity providers for the login page (#58). Public — the
  // login screen renders before there's any session.
  // The kind-agnostic public provider list (OIDC + SAML redirect kinds).
  providers: () =>
    apiFetch<AuthProviderPublic[]>("/api/auth/providers", {}, { auth: false }),
  // Self-service add / change / clear of your own address (#106). Returns the
  // updated UserOut — the same shape the auth store already holds, so the
  // caller can drop it straight in.
  // Profile picture (self-service). The server re-encodes; response is the
  // updated user (fresh avatar_updated_at for the cache-buster).
  uploadAvatar: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<User>("/api/profile/avatar", { method: "POST", body: form });
  },
  removeAvatar: () => apiFetch<void>("/api/profile/avatar", { method: "DELETE" }),
  // Change your own username (the primary login handle). Returns the updated
  // user; a cooldown (username_change_allowed_at) rate-limits repeats.
  changeUsername: (input: { current_password: string; new_display_name: string }) =>
    apiFetch<User>("/api/auth/change-username", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  changeEmail: (input: { current_password: string; new_email: string | null }) =>
    apiFetch<User>("/api/auth/change-email", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  /** Restore a session from the refresh cookie on app load. */
  restore: () => refreshOnce(),
};

// Admin CRUD for identity providers, all kinds (ADR-0022). Gated on
// manage_auth_providers — a higher-stakes grant than manage_site_settings,
// since it governs who can log in at all. The secret is write-only over this
// API; kind-specific settings travel in the nested `config` object.
export const authProvidersApi = {
  base: "/api/admin/auth-providers",
  list: () => apiFetch<AuthProvider[]>(authProvidersApi.base),
  create: (input: {
    kind: string;
    name: string;
    slug: string;
    posture?: "open" | "closed";
    email_is_authoritative?: boolean;
    secret?: string | null;
    config: Record<string, string | boolean | null>;
    enabled?: boolean;
  }) =>
    apiFetch<AuthProvider>(authProvidersApi.base, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  // Omit secret to leave the stored one untouched; "" clears it. `config` is a
  // full replacement, not a merge.
  update: (
    id: string,
    input: Partial<{
      name: string;
      posture: "open" | "closed";
      email_is_authoritative: boolean;
      secret: string;
      config: Record<string, string | boolean | null>;
      enabled: boolean;
    }>,
  ) =>
    apiFetch<AuthProvider>(`${authProvidersApi.base}/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  remove: (id: string) =>
    apiFetch<void>(`${authProvidersApi.base}/${id}`, { method: "DELETE" }),
  // Built-in quick-setup recipes (Google, Microsoft Entra). Read-only and
  // static per build — a preset only prefills the create form; the write path
  // stays the ordinary `create` above.
  presets: () =>
    apiFetch<ProviderPreset[]>(`${authProvidersApi.base}/presets`),
};

export const competitionsApi = {
  list: () => apiFetch<Competition[]>("/api/competitions"),
  get: (id: string) => apiFetch<Competition>(`/api/competitions/${id}`),
  create: (input: CompetitionCreate) =>
    apiFetch<Competition>("/api/competitions", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  update: (id: string, input: CompetitionUpdate) =>
    apiFetch<Competition>(`/api/competitions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  // Clone a competition's config into a fresh one under a new name.
  clone: (id: string, name: string) =>
    apiFetch<Competition>(`/api/competitions/${id}/clone`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  archive: (id: string) =>
    apiFetch<Competition>(`/api/competitions/${id}/archive`, { method: "POST" }),
  unarchive: (id: string) =>
    apiFetch<Competition>(`/api/competitions/${id}/unarchive`, { method: "POST" }),
  // Manual gameplay lifecycle (#221): open (running) / close (ended) play now.
  start: (id: string) =>
    apiFetch<Competition>(`/api/competitions/${id}/start`, { method: "POST" }),
  stop: (id: string) =>
    apiFetch<Competition>(`/api/competitions/${id}/stop`, { method: "POST" }),
  remove: (id: string) =>
    apiFetch<void>(`/api/competitions/${id}`, { method: "DELETE" }),
  // Self-serve join for a public competition (from the lobby list).
  join: (id: string) =>
    apiFetch<Competition>(`/api/competitions/${id}/join`, { method: "POST" }),
  // Join any competition by invite code — the only way into a private one.
  // `accept_rules` accepts the competition's rules in the same request: the
  // code path can't pre-fetch them (the id is unknown until the code resolves),
  // so a rules rejection is retried with acceptance attached.
  joinByCode: (invite_code: string, accept_rules = false) =>
    apiFetch<Competition>("/api/competitions/join", {
      method: "POST",
      body: JSON.stringify({ invite_code, accept_rules }),
    }),
};

export const rulesApi = {
  // The effective rules document + the caller's standing for one competition.
  get: (competitionId: string) =>
    apiFetch<CompetitionRules>(`/api/competitions/${competitionId}/rules`),
  accept: (competitionId: string) =>
    apiFetch<CompetitionRules>(
      `/api/competitions/${competitionId}/rules/accept`,
      { method: "POST" },
    ),
};

export const teamsApi = {
  list: (competitionId: string) =>
    apiFetch<Team[]>(`/api/competitions/${competitionId}/teams`),
  // 404 means "not in a team" — callers treat that as null, not an error.
  me: (competitionId: string) =>
    apiFetch<MyTeam>(`/api/competitions/${competitionId}/teams/me`),
  create: (
    competitionId: string,
    input: {
      name: string;
      affiliation?: string | null;
      country?: string | null;
      website?: string | null;
      approval_required?: boolean;
    },
  ) =>
    apiFetch<MyTeam>(`/api/competitions/${competitionId}/teams`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateMine: (competitionId: string, input: TeamUpdate) =>
    apiFetch<MyTeam>(`/api/competitions/${competitionId}/teams/me`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  join: (competitionId: string, input: { invite_code: string }) =>
    apiFetch<TeamJoinResult>(`/api/competitions/${competitionId}/teams/join`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  requests: (competitionId: string) =>
    apiFetch<TeamApplication[]>(
      `/api/competitions/${competitionId}/teams/me/requests`,
    ),
  approveRequest: (competitionId: string, applicationId: string) =>
    apiFetch<MyTeam>(
      `/api/competitions/${competitionId}/teams/me/requests/${applicationId}/approve`,
      { method: "POST" },
    ),
  rejectRequest: (competitionId: string, applicationId: string) =>
    apiFetch<void>(
      `/api/competitions/${competitionId}/teams/me/requests/${applicationId}/reject`,
      { method: "POST" },
    ),
  leave: (competitionId: string) =>
    apiFetch<void>(`/api/competitions/${competitionId}/teams/leave`, {
      method: "POST",
    }),
};

export const participantsApi = {
  // The individual-mode roster: Participant-role holders + their standing.
  list: (competitionId: string) =>
    apiFetch<Participant[]>(`/api/competitions/${competitionId}/participants`),
  // Manual award over the roster (score_override): grants title/points to
  // selected competitors, folded into the scoreboard.
  award: (competitionId: string, input: AwardInput) =>
    apiFetch<Award[]>(`/api/competitions/${competitionId}/awards`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
};

export const usersApi = {
  // Admin user management (§7). Directory read is view_all_users; writes are
  // manage_users — both Administrator-only among the built-ins.
  list: (q?: string) =>
    apiFetch<UserAccount[]>(`/api/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  create: (input: { display_name: string; password: string; email?: string }) =>
    apiFetch<UserAccount>("/api/users", { method: "POST", body: JSON.stringify(input) }),
  update: (
    id: string,
    input: { display_name?: string; email?: string; password?: string },
  ) =>
    apiFetch<UserAccount>(`/api/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  ban: (id: string) => apiFetch<UserAccount>(`/api/users/${id}/ban`, { method: "POST" }),
  // Moderation: strip a user's profile picture (manage_users).
  removeAvatar: (id: string) =>
    apiFetch<void>(`/api/users/${id}/avatar`, { method: "DELETE" }),
  unban: (id: string) =>
    apiFetch<UserAccount>(`/api/users/${id}/unban`, { method: "POST" }),
  remove: (id: string) => apiFetch<void>(`/api/users/${id}`, { method: "DELETE" }),
  // Mass CSV import (#171). Two-phase: dryRun previews (no writes), the plain
  // call commits atomically. Same report shape both ways.
  importCsv: (
    file: File,
    opts: { dryRun: boolean; defaultCompetitionId?: string },
  ) => {
    const form = new FormData();
    form.append("file", file);
    if (opts.defaultCompetitionId) {
      form.append("default_competition_id", opts.defaultCompetitionId);
    }
    return apiFetch<UserImportReport>(
      `/api/users/import${opts.dryRun ? "?dry_run=true" : ""}`,
      { method: "POST", body: form },
    );
  },
};

export const apiTokensApi = {
  // Oversight (manage_api_tokens): list every token, revoke any — never mint.
  list: () => apiFetch<ApiToken[]>("/api/api-tokens"),
  revoke: (id: string) => apiFetch<void>(`/api/api-tokens/${id}`, { method: "DELETE" }),
  // Self-service (any authenticated user, own account only). The create body
  // carries no user id: the holder is always the caller.
  create: (input: { description: string; expires_in_days: number }) =>
    apiFetch<ApiTokenCreated>("/api/api-tokens", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  listMine: () => apiFetch<ApiToken[]>("/api/api-tokens/me"),
  revokeMine: (id: string) =>
    apiFetch<void>(`/api/api-tokens/me/${id}`, { method: "DELETE" }),
};

export const adminApi = {
  // Site-admin overview: cross-competition totals + health (view_global_analytics).
  overview: () => apiFetch<AdminOverview>("/api/admin/overview"),
};

export const modulesApi = {
  // Site-level optional-module catalog — the at-creation picker source (#252),
  // available before a competition exists (create_competition-gated).
  catalog: () => apiFetch<ModuleCatalogEntry[]>("/api/modules"),
  // Per-competition module inventory + toggle (Admin → Plugins, §11.3).
  list: (competitionId: string) =>
    apiFetch<ModuleState[]>(`/api/competitions/${competitionId}/modules`),
  // Member-readable enabled optional-module ids — gates the nav for every viewer.
  enabled: (competitionId: string) =>
    apiFetch<string[]>(`/api/competitions/${competitionId}/modules/enabled`),
  toggle: (competitionId: string, moduleId: string, enabled: boolean) =>
    apiFetch<ModuleState>(`/api/competitions/${competitionId}/modules/${moduleId}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
};

// Post-event reports (#134, ADR-0030) — organiser-facing, gated on generate_report.
export const reportsApi = {
  base: (competitionId: string) => `/api/competitions/${competitionId}/reports`,
  catalog: (competitionId: string) =>
    apiFetch<ReportCatalog>(`${reportsApi.base(competitionId)}/catalog`),
  list: (competitionId: string) =>
    apiFetch<CompetitionReport[]>(reportsApi.base(competitionId)),
  create: (competitionId: string, input: ReportCreate) =>
    apiFetch<CompetitionReport>(reportsApi.base(competitionId), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  get: (competitionId: string, reportId: string) =>
    apiFetch<CompetitionReport>(`${reportsApi.base(competitionId)}/${reportId}`),
  remove: (competitionId: string, reportId: string) =>
    apiFetch<void>(`${reportsApi.base(competitionId)}/${reportId}`, {
      method: "DELETE",
    }),
  // Streamed through the API (auth'd blob), not a presigned object-store URL —
  // the report renders on any topology, incl. the tunnelled demo where MinIO
  // isn't browser-reachable. Mirrors certificatesApi.downloadMine.
  download: (
    competitionId: string,
    reportId: string,
    fmt: "pdf" | "html",
    filename: string,
  ) =>
    downloadFile(
      `${reportsApi.base(competitionId)}/${reportId}/download/${fmt}`,
      filename,
    ),
};

export const categoriesApi = {
  list: (competitionId: string) =>
    apiFetch<Category[]>(`/api/competitions/${competitionId}/categories`),
  create: (competitionId: string, input: { name: string }) =>
    apiFetch<Category>(`/api/competitions/${competitionId}/categories`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  remove: (competitionId: string, categoryId: string) =>
    apiFetch<void>(
      `/api/competitions/${competitionId}/categories/${categoryId}`,
      { method: "DELETE" },
    ),
};

export const challengesApi = {
  list: (competitionId: string) =>
    apiFetch<Challenge[]>(`/api/competitions/${competitionId}/challenges`),
  get: (competitionId: string, challengeId: string) =>
    apiFetch<Challenge>(
      `/api/competitions/${competitionId}/challenges/${challengeId}`,
    ),
  solves: (competitionId: string, challengeId: string) =>
    apiFetch<ChallengeSolver[]>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/solves`,
    ),
  create: (competitionId: string, input: ChallengeCreate) =>
    apiFetch<Challenge>(`/api/competitions/${competitionId}/challenges`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  update: (competitionId: string, challengeId: string, input: ChallengeUpdate) =>
    apiFetch<Challenge>(
      `/api/competitions/${competitionId}/challenges/${challengeId}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),
  publish: (competitionId: string, challengeId: string) =>
    apiFetch<Challenge>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/publish`,
      { method: "POST" },
    ),
  unpublish: (competitionId: string, challengeId: string) =>
    apiFetch<Challenge>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/unpublish`,
      { method: "POST" },
    ),
  remove: (competitionId: string, challengeId: string) =>
    apiFetch<void>(
      `/api/competitions/${competitionId}/challenges/${challengeId}`,
      { method: "DELETE" },
    ),
  // Reset multiple-choice guesses (challenge_edit). Empty target = everyone.
  resetGuesses: (
    competitionId: string,
    challengeId: string,
    target: { user_id?: string; team_id?: string },
  ) =>
    apiFetch<void>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/reset-guesses`,
      { method: "POST", body: JSON.stringify(target) },
    ),
  // Bulk YAML (ctfcli) export/import.
  exportZip: (competitionId: string) =>
    downloadFile(
      `/api/competitions/${competitionId}/challenges/export`,
      "challenges.zip",
    ),
  importZip: (competitionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<{ created: number; skipped: number; errors: string[] }>(
      `/api/competitions/${competitionId}/challenges/import`,
      { method: "POST", body: form },
    );
  },
};

export const ratingsApi = {
  // Rate a solved challenge 1–5 (competitor). Feedback module + the competition's
  // challenge_ratings_enabled flag gate it server-side.
  rate: (competitionId: string, challengeId: string, rating: number) =>
    apiFetch<void>(
      `/api/competitions/${competitionId}/challenge-ratings/${challengeId}`,
      { method: "POST", body: JSON.stringify({ rating }) },
    ),
  // Per-challenge aggregates (staff).
  summary: (competitionId: string) =>
    apiFetch<ChallengeRatingSummary[]>(
      `/api/competitions/${competitionId}/challenge-ratings`,
    ),
};

function queryString(query: object): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(
    query as Record<string, string | number | undefined>,
  )) {
    if (value !== undefined && value !== null && value !== "") {
      qs.set(key, String(value));
    }
  }
  const suffix = qs.toString();
  return suffix ? `?${suffix}` : "";
}

export const submissionsApi = {
  submit: (competitionId: string, challengeId: string, flag: string) =>
    apiFetch<SubmitResult>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/submit`,
      { method: "POST", body: JSON.stringify({ flag }) },
    ),
  // Staff submissions browser (ROADMAP #76) — raw payload + exact timestamp
  // per attempt, for dispute resolution. Gated view_submissions server-side.
  browse: (competitionId: string, query: SubmissionQuery) =>
    apiFetch<SubmissionPage>(
      `/api/competitions/${competitionId}/analytics/submissions${queryString(query)}`,
    ),
  exportCsv: (competitionId: string, query: SubmissionQuery) =>
    downloadFile(
      `/api/competitions/${competitionId}/analytics/submissions/export${queryString(query)}`,
      `submissions-${competitionId}.csv`,
    ),
};

export const scoreboardApi = {
  // Initial load only — live updates arrive over the scoreboard WS room (§4.1).
  get: (competitionId: string, bracket?: string | null) =>
    apiFetch<Scoreboard>(
      `/api/competitions/${competitionId}/scoreboard${bracket ? `?bracket=${encodeURIComponent(bracket)}` : ""}`,
    ),
  // Staff freeze/unfreeze the public board (scoreboard_freeze).
  freeze: (competitionId: string) =>
    apiFetch<Scoreboard>(`/api/competitions/${competitionId}/scoreboard/freeze`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  unfreeze: (competitionId: string) =>
    apiFetch<Scoreboard>(`/api/competitions/${competitionId}/scoreboard/unfreeze`, {
      method: "POST",
    }),
};

export const bracketsApi = {
  // Staff assign a subject's (team or user) division (edit_competition).
  setForSubject: (competitionId: string, subjectId: string, bracket: string | null) =>
    apiFetch<{ bracket: string | null }>(
      `/api/competitions/${competitionId}/bracket/${subjectId}`,
      { method: "PUT", body: JSON.stringify({ bracket }) },
    ),
};

export const publicApi = {
  // The /public directory of competitions offering a public scoreboard.
  competitions: () =>
    apiFetch<PublicCompetition[]>(`/api/public/competitions`),
  // The unauthenticated spectator board (public competitions only).
  scoreboard: (competitionId: string) =>
    apiFetch<PublicScoreboard>(
      `/api/public/competitions/${competitionId}/scoreboard`,
    ),
  // Spectator stats, highlights and the points timeline (#24).
  insights: (competitionId: string) =>
    apiFetch<PublicInsights>(
      `/api/public/competitions/${competitionId}/insights`,
    ),
  // Recent awarded solves, first-bloods tagged — drives venue mode (#77).
  activity: (competitionId: string) =>
    apiFetch<PublicActivity>(
      `/api/public/competitions/${competitionId}/activity`,
    ),
};

export const ticketsApi = {
  base: (competitionId: string) => `/api/competitions/${competitionId}/tickets`,
  list: (competitionId: string, status?: "open" | "resolved") => {
    const suffix = status ? `?status_filter=${status}` : "";
    return apiFetch<Ticket[]>(`${ticketsApi.base(competitionId)}${suffix}`);
  },
  get: (competitionId: string, ticketId: string) =>
    apiFetch<TicketDetail>(`${ticketsApi.base(competitionId)}/${ticketId}`),
  create: (
    competitionId: string,
    input: { subject: string; body: string; challenge_id?: string | null },
  ) =>
    apiFetch<TicketDetail>(ticketsApi.base(competitionId), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  reply: (
    competitionId: string,
    ticketId: string,
    input: { body: string; is_internal?: boolean },
  ) =>
    apiFetch<TicketDetail>(`${ticketsApi.base(competitionId)}/${ticketId}/messages`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  assign: (competitionId: string, ticketId: string, assignee_user_id?: string) =>
    apiFetch<TicketDetail>(`${ticketsApi.base(competitionId)}/${ticketId}/assign`, {
      method: "POST",
      body: JSON.stringify({ assignee_user_id: assignee_user_id ?? null }),
    }),
  resolve: (competitionId: string, ticketId: string) =>
    apiFetch<TicketDetail>(`${ticketsApi.base(competitionId)}/${ticketId}/resolve`, {
      method: "POST",
    }),
};

// Ticket screenshots (issue #80). Bytes are streamed through the API rather
// than a presigned storage URL, so the inline preview is same-origin and works
// under the production CSP (`img-src 'self' … blob:`).
export const ticketAttachmentsApi = {
  upload: (competitionId: string, ticketId: string, messageId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<TicketAttachment>(
      `${ticketsApi.base(competitionId)}/${ticketId}/messages/${messageId}/attachments`,
      { method: "POST", body: form },
    );
  },
  content: (competitionId: string, ticketId: string, attachmentId: string) =>
    apiFetch<Blob>(
      `${ticketsApi.base(competitionId)}/${ticketId}/attachments/${attachmentId}/content`,
      {},
      { parse: "blob" },
    ),
  remove: (competitionId: string, ticketId: string, attachmentId: string) =>
    apiFetch<void>(
      `${ticketsApi.base(competitionId)}/${ticketId}/attachments/${attachmentId}`,
      { method: "DELETE" },
    ),
};

export const dashboardApi = {
  base: (competitionId: string) => `/api/competitions/${competitionId}/dashboard`,
  stats: (competitionId: string) =>
    apiFetch<DashboardStats>(`${dashboardApi.base(competitionId)}/stats`),
  recentSolves: (competitionId: string) =>
    apiFetch<RecentSolve[]>(`${dashboardApi.base(competitionId)}/recent-solves`),
  challengeHealth: (competitionId: string) =>
    apiFetch<ChallengeHealth[]>(`${dashboardApi.base(competitionId)}/challenge-health`),
  me: (competitionId: string) =>
    apiFetch<MyStanding>(`${dashboardApi.base(competitionId)}/me`),
  // Layout customization (§10.2–10.5). Per-user; `key` selects which dashboard.
  getLayout: (competitionId: string, key: string) =>
    apiFetch<DashboardLayout | null>(
      `${dashboardApi.base(competitionId)}/layout?dashboard_key=${encodeURIComponent(key)}`,
    ),
  saveLayout: (competitionId: string, key: string, entries: DashboardLayoutEntry[]) =>
    apiFetch<DashboardLayout>(
      `${dashboardApi.base(competitionId)}/layout?dashboard_key=${encodeURIComponent(key)}`,
      { method: "PUT", body: JSON.stringify({ entries }) },
    ),
  resetLayout: (competitionId: string, key: string) =>
    apiFetch<void>(
      `${dashboardApi.base(competitionId)}/layout?dashboard_key=${encodeURIComponent(key)}`,
      { method: "DELETE" },
    ),
};

export const rolesApi = {
  list: () => apiFetch<Role[]>("/api/roles"),
  catalog: () => apiFetch<PermissionEntry[]>("/api/roles/catalog"),
  create: (input: {
    name: string;
    description?: string;
    scope?: "global" | "competition";
    permissions?: string[];
    clone_from?: string;
  }) => apiFetch<Role>("/api/roles", { method: "POST", body: JSON.stringify(input) }),
  update: (
    id: string,
    input: { name?: string; description?: string; permissions?: string[] },
  ) => apiFetch<Role>(`/api/roles/${id}`, { method: "PATCH", body: JSON.stringify(input) }),
  remove: (id: string) => apiFetch<void>(`/api/roles/${id}`, { method: "DELETE" }),
  assignments: () => apiFetch<RoleAssignment[]>("/api/roles/assignments"),
  assign: (input: { email: string; role_id: string; competition_id?: string | null }) =>
    apiFetch<RoleAssignment>("/api/roles/assignments", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  unassign: (assignmentId: string) =>
    apiFetch<void>(`/api/roles/assignments/${assignmentId}`, { method: "DELETE" }),
};

// Custom pages (#198, ADR-0034). The two reads are public: a page may be
// published `public`, and the nav list drives the sidebar for signed-out
// visitors too. Authoring lives behind `manage_pages` on /api/admin/pages.
export const pagesApi = {
  // The two reads take an explicit `authed` flag because the same endpoints
  // serve both audiences: anonymous gets the public subset, a signed-in caller
  // gets public + members-only. `auth: false` in apiFetch means the token is
  // NEVER attached — so the caller must say which slice it wants, and the
  // hooks key their queries on it (a cached anonymous nav list must not
  // survive into a signed-in session, which is exactly the bug this fixes).
  nav: (authed: boolean) =>
    apiFetch<PageNavEntry[]>("/api/pages", {}, { auth: authed }),
  get: (slug: string, authed: boolean) =>
    apiFetch<PageContent>(
      `/api/pages/${encodeURIComponent(slug)}`,
      {},
      { auth: authed },
    ),
  adminList: () => apiFetch<AdminPage[]>("/api/admin/pages"),
  create: (input: PageWrite) =>
    apiFetch<AdminPage>("/api/admin/pages", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  update: (id: string, input: Partial<PageWrite>) =>
    apiFetch<AdminPage>(`/api/admin/pages/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  remove: (id: string) =>
    apiFetch<void>(`/api/admin/pages/${id}`, { method: "DELETE" }),
  reorder: (pageIds: string[]) =>
    apiFetch<AdminPage[]>("/api/admin/pages/reorder", {
      method: "POST",
      body: JSON.stringify({ page_ids: pageIds }),
    }),
};

export const siteSettingsApi = {
  // Public read — served unauthenticated so login/register can brand themselves.
  get: () => apiFetch<SiteSettings>("/api/site-settings", {}, { auth: false }),
  update: (input: {
    platform_name: string;
    default_palette: string;
    accent: string;
    background_style: string;
    // null clears the sign-in notice; the form always sends the field, so the
    // backend's omit-leaves-unchanged case never applies from this client (#197).
    login_notice: RichTextDoc | null;
    show_wordmark: boolean;
  }) =>
    apiFetch<SiteSettingsAdmin>("/api/site-settings", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  // Site-wide rules / code of conduct authoring — admin-only.
  rules: () => apiFetch<RulesSettings>("/api/site-settings/rules"),
  updateRules: (input: RulesSettings) =>
    apiFetch<RulesSettings>("/api/site-settings/rules", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  // Operational settings — admin-only (registration policy + SMTP).
  operational: () =>
    apiFetch<OperationalSettings>("/api/site-settings/operational"),
  // Hide the update notice until something newer than the current latest ships
  // (#111). Returns the refreshed settings, so the caller can reuse the same
  // cache entry rather than refetching.
  dismissUpdateNotice: () =>
    apiFetch<OperationalSettings>("/api/site-settings/update-notice/dismiss", {
      method: "POST",
    }),
  updateOperational: (input: OperationalSettingsUpdate) =>
    apiFetch<OperationalSettings>("/api/site-settings/operational", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  // Branding — a custom org logo. Admin-only; the served bytes are public.
  uploadLogo: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<SiteSettingsAdmin>("/api/site-settings/logo", {
      method: "POST",
      body: form,
    });
  },
  deleteLogo: () =>
    apiFetch<SiteSettingsAdmin>("/api/site-settings/logo", { method: "DELETE" }),
  // Platform export / import (full-fidelity, section-selectable backup).
  backupSections: () => apiFetch<string[]>("/api/site-settings/backup/sections"),
  exportBackup: (sections: string[]) =>
    apiFetch<BackupDocument>("/api/site-settings/export", {
      method: "POST",
      body: JSON.stringify({ sections }),
    }),
  importBackup: (sections: string[], payload: BackupDocument) =>
    apiFetch<BackupImportResult>("/api/site-settings/import", {
      method: "POST",
      body: JSON.stringify({ sections, payload }),
    }),
};

export const auditLogApi = {
  list: (query: AuditLogQuery) => {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        qs.set(key, String(value));
      }
    }
    const suffix = qs.toString();
    return apiFetch<AuditLogPage>(
      `/api/admin/audit-log${suffix ? `?${suffix}` : ""}`,
    );
  },
  eventNames: () => apiFetch<string[]>("/api/admin/audit-log/event-names"),
};

export const announcementsApi = {
  // Initial load only — new announcements arrive over the announcements WS room.
  list: (competitionId: string) =>
    apiFetch<Announcement[]>(`/api/competitions/${competitionId}/announcements`),
  create: (competitionId: string, input: AnnouncementCreate) =>
    apiFetch<Announcement>(`/api/competitions/${competitionId}/announcements`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
};

export const hintsApi = {
  list: (competitionId: string, challengeId: string) =>
    apiFetch<Hint[]>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/hints`,
    ),
  create: (
    competitionId: string,
    challengeId: string,
    input: {
      body: string;
      cost: number;
      hidden?: boolean;
      release_at?: string | null;
    },
  ) =>
    apiFetch<HintAuthored>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/hints`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  update: (
    competitionId: string,
    challengeId: string,
    hintId: string,
    patch: HintUpdate,
  ) =>
    apiFetch<HintAuthored>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/hints/${hintId}`,
      { method: "PATCH", body: JSON.stringify(patch) },
    ),
  remove: (competitionId: string, challengeId: string, hintId: string) =>
    apiFetch<void>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/hints/${hintId}`,
      { method: "DELETE" },
    ),
  reveal: (competitionId: string, challengeId: string, hintId: string) =>
    apiFetch<Hint>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/hints/${hintId}/reveal`,
      { method: "POST" },
    ),
};

export const attachmentsApi = {
  list: (competitionId: string, challengeId: string) =>
    apiFetch<Attachment[]>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/attachments`,
    ),
  upload: (competitionId: string, challengeId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<Attachment>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/attachments`,
      { method: "POST", body: form },
    );
  },
  // Fetch a fresh short-lived signed URL at click time (§13.3) — never store it.
  signedUrl: (competitionId: string, challengeId: string, attachmentId: string) =>
    apiFetch<SignedUrl>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/attachments/${attachmentId}/url`,
    ),
  remove: (competitionId: string, challengeId: string, attachmentId: string) =>
    apiFetch<void>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/attachments/${attachmentId}`,
      { method: "DELETE" },
    ),
};

export const automationsApi = {
  // Org rules (§5.1). The competition context rides ?competition_id= — the
  // same place the backend permission check reads it; omitting it means the
  // global-rules surface (Administrator only).
  list: (competitionId?: string) =>
    apiFetch<AutomationRule[]>(
      `/api/automations${competitionId ? `?competition_id=${competitionId}` : ""}`,
    ),
  get: (ruleId: string) => apiFetch<AutomationRule>(`/api/automations/${ruleId}`),
  create: (input: AutomationRuleInput, competitionId?: string) =>
    apiFetch<AutomationRule>(
      `/api/automations${competitionId ? `?competition_id=${competitionId}` : ""}`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  update: (ruleId: string, input: AutomationRuleInput) =>
    apiFetch<AutomationRule>(`/api/automations/${ruleId}`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  remove: (ruleId: string) =>
    apiFetch<void>(`/api/automations/${ruleId}`, { method: "DELETE" }),
  catalog: (competitionId?: string) =>
    apiFetch<AutomationCatalog>(
      `/api/automations/catalog${competitionId ? `?competition_id=${competitionId}` : ""}`,
    ),
  // Personal rules (§5.1): notify-self only, no automation permission needed.
  personal: {
    list: () => apiFetch<AutomationRule[]>("/api/automations/personal"),
    create: (input: AutomationRuleInput & { competition_id?: string | null }) =>
      apiFetch<AutomationRule>("/api/automations/personal", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    update: (
      ruleId: string,
      input: AutomationRuleInput & { competition_id?: string | null },
    ) =>
      apiFetch<AutomationRule>(`/api/automations/personal/${ruleId}`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    remove: (ruleId: string) =>
      apiFetch<void>(`/api/automations/personal/${ruleId}`, { method: "DELETE" }),
  },
};

// AI provider config (#98, ADR-0023) — Admin → Site settings → AI. Gated on
// manage_ai (a higher-stakes grant than manage_site_settings: it holds an API
// key and enables outbound calls). The key is write-only over this API.
export const aiAdminApi = {
  get: () => apiFetch<AiSettings>("/api/admin/ai/settings"),
  // Omit api_key to leave the stored one; "" clears it.
  update: (input: AiSettingsUpdate) =>
    apiFetch<AiSettings>("/api/admin/ai/settings", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  // Probe the saved config: a completion + a forced tool call, reported apart.
  testConnection: () =>
    apiFetch<AiConnectionResult>("/api/admin/ai/test-connection", {
      method: "POST",
    }),
};

// Challenge instancing site infra config (#266, ADR-0036). Same write-only
// secret + staged test-connection posture as the AI panel.
export const instancesAdminApi = {
  get: () => apiFetch<InstanceSettings>("/api/admin/instances/settings"),
  // Omit registry_credentials to leave the stored one; "" clears it.
  update: (input: InstanceSettingsUpdate) =>
    apiFetch<InstanceSettings>("/api/admin/instances/settings", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  // Run the provisioner's staged validate() against the saved config.
  testConnection: () =>
    apiFetch<InstanceConnectionResult>("/api/admin/instances/test-connection", {
      method: "POST",
    }),
};

// The per-challenge deployment spec (authoring). One per challenge; GET 404s
// when none is set yet, upsert replaces it, DELETE removes it.
export const deploymentsApi = {
  base: (competitionId: string, challengeId: string) =>
    `/api/competitions/${competitionId}/challenges/${challengeId}/deployment`,
  get: (competitionId: string, challengeId: string) =>
    apiFetch<ChallengeDeployment>(
      deploymentsApi.base(competitionId, challengeId),
    ),
  upsert: (
    competitionId: string,
    challengeId: string,
    input: ChallengeDeploymentUpdate,
  ) =>
    apiFetch<ChallengeDeployment>(deploymentsApi.base(competitionId, challengeId), {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  remove: (competitionId: string, challengeId: string) =>
    apiFetch<void>(deploymentsApi.base(competitionId, challengeId), {
      method: "DELETE",
    }),
};

// A competitor's own instance of a challenge (#266). GET 404s when they have
// none; launch/extend/destroy drive its lifecycle (provisioning is async, so
// the row starts `requested` and goes live over the activity room).
export const instanceApi = {
  base: (competitionId: string, challengeId: string) =>
    `/api/competitions/${competitionId}/challenges/${challengeId}/instance`,
  get: (competitionId: string, challengeId: string) =>
    apiFetch<Instance>(instanceApi.base(competitionId, challengeId)),
  launch: (competitionId: string, challengeId: string) =>
    apiFetch<Instance>(instanceApi.base(competitionId, challengeId), {
      method: "POST",
    }),
  extend: (competitionId: string, challengeId: string) =>
    apiFetch<Instance>(`${instanceApi.base(competitionId, challengeId)}/extend`, {
      method: "POST",
    }),
  destroy: (competitionId: string, challengeId: string) =>
    apiFetch<{ status: string }>(instanceApi.base(competitionId, challengeId), {
      method: "DELETE",
    }),
};

// The administrator assistant's conversation API (#98, ADR-0023 Phase 2).
// Competition-scoped; the live answer streams over the `ai` WS room while the
// POST persists it (so the hook opens a socket, not just these calls).
export const aiApi = {
  base: (competitionId: string) => `/api/competitions/${competitionId}/ai`,
  availability: (competitionId: string) =>
    apiFetch<AiAvailability>(`${aiApi.base(competitionId)}/availability`),
  // Record the caller's one-time competitor-disclosure acceptance (idempotent).
  acceptDisclosure: (competitionId: string) =>
    apiFetch<void>(`${aiApi.base(competitionId)}/disclosure/accept`, {
      method: "POST",
    }),
  // Resume-or-create: returns the caller's open thread (with its message
  // history) for this competition + assistant type, or a fresh one.
  createConversation: (competitionId: string, assistantType: AiAssistantType) =>
    apiFetch<AiConversationDetail>(`${aiApi.base(competitionId)}/conversations`, {
      method: "POST",
      body: JSON.stringify({ assistant_type: assistantType }),
    }),
  postMessage: (competitionId: string, conversationId: string, content: string) =>
    apiFetch<AiMessage>(
      `${aiApi.base(competitionId)}/conversations/${conversationId}/messages`,
      { method: "POST", body: JSON.stringify({ content }) },
    ),
  // Staff-gated (a competitor never calls it — the hook gates on assistant type).
  usage: (competitionId: string) =>
    apiFetch<AiUsage>(`${aiApi.base(competitionId)}/usage`),
  // Per-competition competitor-assistant controls (edit_competition).
  competitionSettings: (competitionId: string) =>
    apiFetch<AiCompetitionSettings>(`${aiApi.base(competitionId)}/settings`),
  updateCompetitionSettings: (
    competitionId: string,
    input: AiCompetitionSettingsUpdate,
  ) =>
    apiFetch<AiCompetitionSettings>(`${aiApi.base(competitionId)}/settings`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  // Transcript review (ai_view_transcripts) — competitor conversations only.
  transcripts: (competitionId: string) =>
    apiFetch<AiTranscriptSummary[]>(`${aiApi.base(competitionId)}/transcripts`),
  transcript: (competitionId: string, conversationId: string) =>
    apiFetch<AiTranscriptDetail>(
      `${aiApi.base(competitionId)}/transcripts/${conversationId}`,
    ),
};

export const analyticsApi = {
  challenges: (competitionId: string) =>
    apiFetch<ChallengeAnalyticsReport>(
      `/api/competitions/${competitionId}/analytics/challenges`,
    ),
  teams: (competitionId: string) =>
    apiFetch<TeamAnalyticsReport>(
      `/api/competitions/${competitionId}/analytics/teams`,
    ),
};

export const notificationsApi = {
  // The current user's own notification center (§4.4) — site-wide, not nested
  // under a competition, since a user's notifications span every competition.
  list: () => apiFetch<AppNotification[]>("/api/notifications"),
  unreadCount: () =>
    apiFetch<{ unread: number }>("/api/notifications/unread-count"),
  markRead: (id: string) =>
    apiFetch<AppNotification>(`/api/notifications/${id}/read`, { method: "POST" }),
  markAllRead: () =>
    apiFetch<void>("/api/notifications/read-all", { method: "POST" }),
  getPreferences: () =>
    apiFetch<NotificationPreferences>("/api/notifications/preferences"),
  updatePreferences: (prefs: NotificationPreferences) =>
    apiFetch<NotificationPreferences>("/api/notifications/preferences", {
      method: "PUT",
      body: JSON.stringify(prefs),
    }),
};

/** Fetch a file with the access token and trigger a browser download. Used for
 *  the survey CSV export, which isn't JSON so it can't go through apiFetch. */
async function downloadFile(path: string, filename: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`${API_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: "include",
  });
  if (!res.ok) throw new ApiError(res.status, "Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const feedbackApi = {
  base: (competitionId: string) => `/api/competitions/${competitionId}/surveys`,
  list: (competitionId: string) =>
    apiFetch<SurveySummary[]>(feedbackApi.base(competitionId)),
  get: (competitionId: string, surveyId: string) =>
    apiFetch<SurveyDetail>(`${feedbackApi.base(competitionId)}/${surveyId}`),
  create: (competitionId: string, input: { title: string; description?: string | null }) =>
    apiFetch<SurveyDetail>(feedbackApi.base(competitionId), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  update: (
    competitionId: string,
    surveyId: string,
    input: { title: string; description: string | null; is_open: boolean },
  ) =>
    apiFetch<SurveyDetail>(`${feedbackApi.base(competitionId)}/${surveyId}`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  remove: (competitionId: string, surveyId: string) =>
    apiFetch<void>(`${feedbackApi.base(competitionId)}/${surveyId}`, { method: "DELETE" }),
  addQuestion: (competitionId: string, surveyId: string, input: QuestionInput) =>
    apiFetch<SurveyQuestion>(`${feedbackApi.base(competitionId)}/${surveyId}/questions`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateQuestion: (
    competitionId: string,
    surveyId: string,
    questionId: string,
    input: QuestionInput,
  ) =>
    apiFetch<SurveyQuestion>(
      `${feedbackApi.base(competitionId)}/${surveyId}/questions/${questionId}`,
      { method: "PUT", body: JSON.stringify(input) },
    ),
  removeQuestion: (competitionId: string, surveyId: string, questionId: string) =>
    apiFetch<void>(
      `${feedbackApi.base(competitionId)}/${surveyId}/questions/${questionId}`,
      { method: "DELETE" },
    ),
  reorder: (competitionId: string, surveyId: string, question_ids: string[]) =>
    apiFetch<SurveyQuestion[]>(
      `${feedbackApi.base(competitionId)}/${surveyId}/questions/order`,
      { method: "PUT", body: JSON.stringify({ question_ids }) },
    ),
  submit: (
    competitionId: string,
    surveyId: string,
    answers: { question_id: string; value: string }[],
  ) =>
    apiFetch<void>(`${feedbackApi.base(competitionId)}/${surveyId}/responses`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  results: (competitionId: string, surveyId: string) =>
    apiFetch<SurveyResults>(`${feedbackApi.base(competitionId)}/${surveyId}/results`),
  exportCsv: (competitionId: string, surveyId: string) =>
    downloadFile(
      `${feedbackApi.base(competitionId)}/${surveyId}/responses.csv`,
      `survey-${surveyId}-responses.csv`,
    ),
};

/** Unauthenticated connectivity check (skeleton hello endpoint). */
export const getHello = () =>
  apiFetch<HelloResponse>("/api/hello", {}, { auth: false });

// Certificates (#219, ADR-0027) — optional `certificates` module.
export const certificatesApi = {
  base: (competitionId: string) =>
    `/api/competitions/${competitionId}/certificates`,
  getTemplate: (competitionId: string) =>
    apiFetch<CertificateTemplate>(`${certificatesApi.base(competitionId)}/template`),
  saveTemplate: (competitionId: string, input: CertificateTemplateInput) =>
    apiFetch<CertificateTemplate>(`${certificatesApi.base(competitionId)}/template`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  uploadBackground: (competitionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<CertificateTemplate>(
      `${certificatesApi.base(competitionId)}/background`,
      { method: "POST", body: form },
    );
  },
  uploadImage: (competitionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<{ image_key: string }>(
      `${certificatesApi.base(competitionId)}/images`,
      { method: "POST", body: form },
    );
  },
  // Render the in-progress design with sample tokens through the real renderer.
  preview: (competitionId: string, input: CertificateTemplateInput) =>
    apiFetch<Blob>(
      `${certificatesApi.base(competitionId)}/preview`,
      { method: "POST", body: JSON.stringify(input) },
      { parse: "blob" },
    ),
  release: (competitionId: string) =>
    apiFetch<CertificateTemplate>(`${certificatesApi.base(competitionId)}/release`, {
      method: "POST",
    }),
  createExport: (competitionId: string) =>
    apiFetch<CertificateExportJob>(`${certificatesApi.base(competitionId)}/exports`, {
      method: "POST",
    }),
  getExport: (competitionId: string, jobId: string) =>
    apiFetch<CertificateExportJob>(
      `${certificatesApi.base(competitionId)}/exports/${jobId}`,
    ),
  // Fetch a certificate element image as a blob for the editor.
  media: (competitionId: string, key: string) =>
    apiFetch<Blob>(
      `${certificatesApi.base(competitionId)}/media?key=${encodeURIComponent(key)}`,
      {},
      { parse: "blob" },
    ),
  // The current uploaded background (keyless), as a blob for the editor canvas.
  backgroundImage: (competitionId: string) =>
    apiFetch<Blob>(
      `${certificatesApi.base(competitionId)}/background-image`,
      {},
      { parse: "blob" },
    ),
  myAvailability: (competitionId: string) =>
    apiFetch<CertificateAvailability>(`${certificatesApi.base(competitionId)}/me`),
  downloadMine: (competitionId: string, filename: string) =>
    downloadFile(`${certificatesApi.base(competitionId)}/me/download`, filename),
  // Custom fonts (organiser-uploaded, per competition).
  fonts: (competitionId: string) =>
    apiFetch<CertificateFont[]>(`${certificatesApi.base(competitionId)}/fonts`),
  uploadFont: (competitionId: string, file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    return apiFetch<CertificateFont>(
      `${certificatesApi.base(competitionId)}/fonts`,
      { method: "POST", body: form },
    );
  },
  deleteFont: (competitionId: string, fontId: string) =>
    apiFetch<void>(`${certificatesApi.base(competitionId)}/fonts/${fontId}`, {
      method: "DELETE",
    }),
  // A custom font's bytes as a blob, for the editor's @font-face (auth'd, like
  // element images — @font-face can't carry the bearer token itself).
  fontFile: (competitionId: string, fontId: string) =>
    apiFetch<Blob>(
      `${certificatesApi.base(competitionId)}/fonts/${fontId}/file`,
      {},
      { parse: "blob" },
    ),
  // Download the design as a portable JSON document (assets embedded).
  exportTemplate: (competitionId: string, filename: string) =>
    downloadFile(`${certificatesApi.base(competitionId)}/template/export`, filename),
  // Replace the current design with a previously-exported document.
  importTemplate: (competitionId: string, doc: unknown) =>
    apiFetch<CertificateTemplate>(
      `${certificatesApi.base(competitionId)}/template/import`,
      { method: "POST", body: JSON.stringify(doc) },
    ),
};

export const meCertificatesApi = {
  list: () => apiFetch<MyCertificate[]>("/api/me/certificates"),
};

export const certificateAssetsApi = {
  // Unauthenticated: bundled, non-sensitive editor configuration.
  manifest: () =>
    apiFetch<CertificateManifest>(
      "/api/certificate-assets/manifest",
      {},
      { auth: false },
    ),
};
