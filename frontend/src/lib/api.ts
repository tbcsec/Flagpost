// API client (ARCHITECTURE.md §8).
//
// This is the single low-level transport. Components NEVER import it directly —
// they go through one TanStack Query hook module per domain (lib/hooks/*). It
// attaches the in-memory access token as a Bearer header and, on a 401,
// transparently attempts a single refresh (using the httpOnly refresh cookie)
// and retries once. Concurrent 401s share one in-flight refresh.

import { useAuthStore } from "@/stores/auth";
import type {
  Announcement,
  AppNotification,
  AuditLogPage,
  AuditLogQuery,
  Attachment,
  AutomationCatalog,
  AutomationRule,
  AutomationRuleInput,
  ChallengeAnalyticsReport,
  TeamAnalyticsReport,
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
  ChallengeUpdate,
  Competition,
  CompetitionCreate,
  CompetitionUpdate,
  HelloResponse,
  Hint,
  HintAuthored,
  ModuleState,
  MyTeam,
  Participant,
  UserAccount,
  Permissions,
  PermissionEntry,
  Role,
  RoleAssignment,
  Scoreboard,
  SignedUrl,
  SiteSettings,
  SiteSettingsAdmin,
  SubmitResult,
  Team,
  Ticket,
  TicketDetail,
  TokenResponse,
  User,
} from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
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
}

async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  { auth = true, retryOn401 = true }: RequestOptions = {},
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
      return apiFetch<T>(path, init, { auth, retryOn401: false });
    }
  }

  if (!res.ok) {
    throw new ApiError(res.status, await extractError(res));
  }
  if (res.status === 204) return undefined as T;
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

async function extractError(res: Response): Promise<string> {
  // Prefer the server's own reason — it's the most specific (e.g. "Incorrect
  // email or password", "A team with that name already exists").
  try {
    const body = await res.json();
    if (typeof body?.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
    // FastAPI validation errors (422) arrive as an array under `detail`.
    if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
      return `Invalid input: ${body.detail[0].msg}`;
    }
  } catch {
    /* non-JSON body — fall through to a status-based message */
  }
  if (res.status >= 500) {
    return "The Flagpost service ran into a problem. Please try again — if it keeps happening, contact an administrator.";
  }
  return (
    STATUS_MESSAGES[res.status] ??
    `The request failed (error ${res.status}). Please try again.`
  );
}

// --- Typed endpoint helpers (consumed only by hooks) ------------------------

export const authApi = {
  register: (input: { email: string; password: string; display_name: string }) =>
    apiFetch<TokenResponse>(
      "/api/auth/register",
      { method: "POST", body: JSON.stringify(input) },
      { auth: false },
    ),
  login: (input: { email: string; password: string }) =>
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
  /** Restore a session from the refresh cookie on app load. */
  restore: () => refreshOnce(),
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
  // Self-serve join for a public competition (from the lobby list).
  join: (id: string) =>
    apiFetch<Competition>(`/api/competitions/${id}/join`, { method: "POST" }),
  // Join any competition by invite code — the only way into a private one.
  joinByCode: (invite_code: string) =>
    apiFetch<Competition>("/api/competitions/join", {
      method: "POST",
      body: JSON.stringify({ invite_code }),
    }),
};

export const teamsApi = {
  list: (competitionId: string) =>
    apiFetch<Team[]>(`/api/competitions/${competitionId}/teams`),
  // 404 means "not in a team" — callers treat that as null, not an error.
  me: (competitionId: string) =>
    apiFetch<MyTeam>(`/api/competitions/${competitionId}/teams/me`),
  create: (competitionId: string, input: { name: string }) =>
    apiFetch<MyTeam>(`/api/competitions/${competitionId}/teams`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  join: (competitionId: string, input: { invite_code: string }) =>
    apiFetch<MyTeam>(`/api/competitions/${competitionId}/teams/join`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  leave: (competitionId: string) =>
    apiFetch<void>(`/api/competitions/${competitionId}/teams/leave`, {
      method: "POST",
    }),
};

export const participantsApi = {
  // The individual-mode roster: Participant-role holders + their standing.
  list: (competitionId: string) =>
    apiFetch<Participant[]>(`/api/competitions/${competitionId}/participants`),
};

export const usersApi = {
  // Admin user management (§7). Directory read is view_all_users; writes are
  // manage_users — both Administrator-only among the built-ins.
  list: (q?: string) =>
    apiFetch<UserAccount[]>(`/api/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  create: (input: { email: string; display_name: string; password: string }) =>
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
  unban: (id: string) =>
    apiFetch<UserAccount>(`/api/users/${id}/unban`, { method: "POST" }),
  remove: (id: string) => apiFetch<void>(`/api/users/${id}`, { method: "DELETE" }),
};

export const modulesApi = {
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
};

export const submissionsApi = {
  submit: (competitionId: string, challengeId: string, flag: string) =>
    apiFetch<SubmitResult>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/submit`,
      { method: "POST", body: JSON.stringify({ flag }) },
    ),
};

export const scoreboardApi = {
  // Initial load only — live updates arrive over the scoreboard WS room (§4.1).
  get: (competitionId: string) =>
    apiFetch<Scoreboard>(`/api/competitions/${competitionId}/scoreboard`),
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

export const siteSettingsApi = {
  // Public read — served unauthenticated so login/register can brand themselves.
  get: () => apiFetch<SiteSettings>("/api/site-settings", {}, { auth: false }),
  update: (input: { platform_name: string; default_palette: string; accent: string }) =>
    apiFetch<SiteSettingsAdmin>("/api/site-settings", {
      method: "PUT",
      body: JSON.stringify(input),
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
  create: (competitionId: string, input: { title: string; body: string }) =>
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
    input: { body: string; cost: number },
  ) =>
    apiFetch<HintAuthored>(
      `/api/competitions/${competitionId}/challenges/${challengeId}/hints`,
      { method: "POST", body: JSON.stringify(input) },
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
