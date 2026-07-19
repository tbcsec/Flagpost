// API client (ARCHITECTURE.md §8).
//
// This is the single low-level transport. Components NEVER import it directly —
// they go through one TanStack Query hook module per domain (lib/hooks/*). It
// attaches the in-memory access token as a Bearer header and, on a 401,
// transparently attempts a single refresh (using the httpOnly refresh cookie)
// and retries once. Concurrent 401s share one in-flight refresh.

import { useAuthStore } from "@/stores/auth";
import type {
  Category,
  Challenge,
  ChallengeCreate,
  ChallengeUpdate,
  Competition,
  CompetitionCreate,
  CompetitionUpdate,
  HelloResponse,
  MyTeam,
  Team,
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
  const res = await fetch(`${API_URL}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
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
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

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

async function extractError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* non-JSON body */
  }
  return `Request failed (${res.status})`;
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

/** Unauthenticated connectivity check (skeleton hello endpoint). */
export const getHello = () =>
  apiFetch<HelloResponse>("/api/hello", {}, { auth: false });
