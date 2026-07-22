// Shared API types. Domain types land here as features are built.

export interface HelloResponse {
  message: string;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export type ParticipationMode = "team" | "individual";
export type Visibility = "public" | "private";

export interface Competition {
  id: string;
  name: string;
  description: string;
  start_at: string | null;
  end_at: string | null;
  registration_opens_at: string | null;
  registration_closes_at: string | null;
  participation_mode: ParticipationMode;
  visibility: Visibility;
  /** Organiser-shareable code for joining a private competition. */
  invite_code: string;
  created_at: string;
}

/** Effective permissions for the current user (auth/me/permissions). The set
 *  for a competition is `global ∪ by_competition[id]`. */
export interface Permissions {
  global: string[];
  by_competition: Record<string, string[]>;
}

/** Operational dashboard reads (§10). Each widget fetches its own slice. */
export interface DashboardStats {
  total_solves: number;
  total_submissions: number;
  active_participants: number;
  published_challenges: number;
  recent_solves_1h: number;
}

export interface RecentSolve {
  subject_name: string;
  challenge_title: string;
  points: number;
  at: string;
}

export interface ChallengeHealth {
  challenge_id: string;
  title: string;
  points: number;
  solves: number;
  attempts: number;
}

export interface MyStanding {
  rank: number | null;
  points: number | null;
  solved_count: number;
}

/** Support tickets (§4.4, ROADMAP #18). */
export type TicketStatus = "open" | "resolved";

export interface TicketMessage {
  id: string;
  author_user_id: string;
  author_name: string;
  body: string;
  is_internal: boolean;
  created_at: string;
}

export interface Ticket {
  id: string;
  subject: string;
  status: TicketStatus;
  challenge_id: string | null;
  challenge_title: string | null;
  opener_name: string;
  team_name: string | null;
  assignee_name: string | null;
  message_count: number;
  created_at: string;
}

export interface TicketDetail extends Ticket {
  messages: TicketMessage[];
}

/** An automation rule (§5.1): Trigger → Conditions → Actions. */
export interface AutomationCondition {
  field: string;
  operator: string;
  value?: string | number | boolean | null;
}

/** Action config is per-type (§5.3); the list page only needs `type`. */
export interface AutomationAction {
  type: string;
  [key: string]: unknown;
}

export interface AutomationRule {
  id: string;
  name: string;
  trigger_type: string;
  conditions: AutomationCondition[];
  actions: AutomationAction[];
  is_enabled: boolean;
  competition_id: string | null;
  owner_user_id: string | null;
  trigger_count: number;
  last_triggered_at: string | null;
  created_at: string;
}

export interface AutomationRuleInput {
  name: string;
  trigger_type: string;
  conditions: AutomationCondition[];
  actions: AutomationAction[];
  is_enabled: boolean;
}

/** The editor catalog (§5.5) — the builder is generated from it. */
export interface CatalogField {
  key: string;
  label: string;
  kind: "text" | "textarea" | "number" | "select" | "string_list" | "keyvalue";
  required: boolean;
  options: string[] | null;
  placeholder: string | null;
  templateable: boolean;
}

export interface TriggerEntry {
  event: string;
  label: string;
  fields: string[];
}

export interface OperatorEntry {
  value: string;
  label: string;
  unary: boolean;
}

export interface ActionCatalogEntry {
  type: string;
  label: string;
  personal_allowed: boolean;
  fields: CatalogField[];
}

export interface AutomationCatalog {
  triggers: TriggerEntry[];
  operators: OperatorEntry[];
  actions: ActionCatalogEntry[];
}

/** One in-app notification for the bell (§4.4). `read` is derived server-side
 *  from the row's nullable `read_at`. */
export interface AppNotification {
  id: string;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  competition_id: string | null;
  read: boolean;
  created_at: string;
}

/** One persisted event from the audit log (§3.3). */
export interface AuditLogEntry {
  id: string;
  event_name: string;
  payload: Record<string, unknown>;
  competition_id: string | null;
  user_id: string | null;
  created_at: string;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditLogQuery {
  event?: string;
  competition_id?: string;
  user_id?: string;
  team_id?: string;
  q?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export interface CompetitionCreate {
  name: string;
  description?: string;
  participation_mode?: ParticipationMode;
  visibility?: Visibility;
  start_at?: string | null;
  end_at?: string | null;
  registration_opens_at?: string | null;
  registration_closes_at?: string | null;
}

export type CompetitionUpdate = Partial<CompetitionCreate>;

export interface TeamMember {
  user_id: string;
  display_name: string;
  is_captain: boolean;
}

/** Public listing shape — no invite code. */
export interface Team {
  id: string;
  competition_id: string;
  name: string;
  member_count: number;
  created_at: string;
}

/** A member's view of their own team. */
export interface MyTeam {
  id: string;
  competition_id: string;
  name: string;
  invite_code: string;
  members: TeamMember[];
  created_at: string;
}

export interface Category {
  id: string;
  competition_id: string;
  name: string;
  created_at: string;
}

export type FlagType = "static" | "regex";
export type ChallengeState = "draft" | "published";

/** TipTap/ProseMirror document. */
export type RichTextDoc = Record<string, unknown>;

export interface Challenge {
  id: string;
  competition_id: string;
  title: string;
  description: RichTextDoc;
  category_id: string | null;
  points: number;
  state: ChallengeState;
  flag_type: FlagType;
  case_insensitive: boolean;
  /** The only flag-related fact the server ever returns (§13.2). */
  has_flag: boolean;
  /** Whether the requesting subject (team or user) has solved this (§13.2). */
  solved: boolean;
  /** Number of distinct subjects that have solved this challenge. */
  solve_count: number;
  created_at: string;
}

export interface ChallengeCreate {
  title: string;
  description?: RichTextDoc;
  category_id?: string | null;
  points?: number;
  flag_type?: FlagType;
  case_insensitive?: boolean;
  flag?: string | null;
}

export type ChallengeUpdate = Partial<ChallengeCreate>;

export interface Attachment {
  id: string;
  challenge_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface SignedUrl {
  url: string;
  expires_in_seconds: number;
}

/** Result of a flag submission (§13.2). */
export interface SubmitResult {
  correct: boolean;
  already_solved: boolean;
  points_awarded: number;
  is_first_blood: boolean;
}

/** One ranked row on the scoreboard (Phase 7). The subject is the team in
 *  team-mode, the user in individual-mode — same as scoring. */
export interface ScoreboardEntry {
  rank: number;
  subject_id: string;
  name: string;
  points: number;
  /** When the subject reached its current score — the ranking tie-break. */
  last_solve_at: string | null;
}

export interface Scoreboard {
  competition_id: string;
  mode: ParticipationMode;
  entries: ScoreboardEntry[];
}

/** A broadcast announcement (Phase 8). */
export interface Announcement {
  id: string;
  competition_id: string;
  title: string;
  body: string;
  created_at: string;
}

/** A hint as a competitor sees it (Phase 9): `body` is null until this subject
 *  has revealed it. Editors receive every body with `revealed: true`. */
export interface Hint {
  id: string;
  challenge_id: string;
  cost: number;
  revealed: boolean;
  body: string | null;
}

/** The authoring view returned when creating a hint. */
export interface HintAuthored {
  id: string;
  challenge_id: string;
  body: string;
  cost: number;
  created_at: string;
}

// Site-wide theme + branding (§9). Public shape (login/register read it).
export interface SiteSettings {
  platform_name: string;
  default_palette: string;
  accent: string;
}

// Admin shape adds the last-updated timestamp.
export interface SiteSettingsAdmin extends SiteSettings {
  updated_at: string | null;
}

// RBAC admin (§7.4). Roles are data: a permission-key array + scope.
export type RoleScope = "global" | "competition";

export interface Role {
  id: string;
  name: string;
  description: string;
  is_system: boolean;
  scope: RoleScope;
  permissions: string[];
}

// One catalog entry for the editor's permission matrix (§7.1).
export interface PermissionEntry {
  key: string;
  category: string;
  scope: RoleScope;
  reserved: boolean;
}

export interface RoleAssignment {
  id: string;
  user_id: string;
  user_email: string;
  user_display_name: string;
  role_id: string;
  role_name: string;
  role_scope: RoleScope;
  competition_id: string | null;
  competition_name: string | null;
}
