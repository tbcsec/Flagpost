// Shared API types. Domain types land here as features are built.

export interface HelloResponse {
  message: string;
}

export interface User {
  id: string;
  // Optional — the display name is the primary identifier; email is a secondary
  // login handle a user may not have set.
  email: string | null;
  display_name: string;
  created_at: string;
  // Email verification (#74): null = unverified (or the account is exempt /
  // predates the gate). Drives the profile "verify your email" banner.
  email_verified_at: string | null;
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
  /** Set when an organiser has archived (closed out) the competition. */
  archived_at: string | null;
  /** When the retention job will hard-delete this archived competition (#26);
   *  null = no clock (active, retention off, or archived pre-feature). */
  purge_after: string | null;
  /** Competition-wide cap on guesses per subject per multiple-choice challenge
   *  (null = unlimited). */
  mc_guess_limit: number | null;
  /** Percent of a multiple-choice challenge's value docked per wrong guess, for
   *  the guessing subject (#148). 1–100; null = off. */
  mc_penalty_pct: number | null;
  /** Whether solving a challenge prompts the competitor for a 1–5 rating. */
  challenge_ratings_enabled: boolean;
  /** Per-competition managed vocab: tag names + ordered difficulty tiers. */
  challenge_tags: string[];
  difficulty_tiers: string[];
  /** Public spectator board + CTFtime feed opt-ins. */
  public_scoreboard: boolean;
  ctftime_enabled: boolean;
  /** Brackets/divisions competitors self-select at join. */
  brackets: string[];
  /** Max members per team (team-mode); null = unlimited. */
  max_team_size: number | null;
  /** Paused = gameplay halted; competitors can't submit flags. */
  paused: boolean;
  /** Per-competition rules/CoC override (#57); null = site-wide rules apply. */
  rules_override: RichTextDoc | null;
  /** Informational-only override: shown at join, never gating. */
  rules_display_only: boolean;
}

/** The effective rules document for a competition + the caller's standing
 *  (GET /competitions/{id}/rules). `required` is the server's verdict for the
 *  in-app re-acceptance gate (membership included); the join flows decide from
 *  the raw facts. */
export interface CompetitionRules {
  rules: RichTextDoc | null;
  display_only: boolean;
  accepted: boolean;
  exempt: boolean;
  required: boolean;
}

/** Site-wide rules authoring shape (Admin → Site settings). */
export interface RulesSettings {
  rules_text: RichTextDoc | null;
  rules_display_only: boolean;
}

/** Aggregate ratings for one challenge (staff — Feedback page). */
export interface ChallengeRatingSummary {
  challenge_id: string;
  title: string;
  average: number;
  count: number;
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

/** Per-user dashboard layout customization (§10.2–10.5). */
export interface DashboardLayoutEntry {
  widget_id: string;
  cols: number;
  rows: number;
  hidden: boolean;
}

export interface DashboardLayout {
  dashboard_key: string;
  entries: DashboardLayoutEntry[];
}

/** An external identity provider offered on the login page (#58, ADR-0021).
 *  The public shape is deliberately minimal — just enough to draw a button. */
export interface AuthProviderPublic {
  slug: string;
  name: string;
  /** Which transport — drives the login URL `/api/auth/{kind}/{slug}/login`. */
  kind: string;
}

/** Admin view of a provider. The client secret is write-only: only whether one
 *  is stored is ever returned. */
export interface AuthProvider {
  id: string;
  /** Protocol: "oidc", "saml" or "ldap". */
  kind: string;
  /** ADR-0022 trust posture: "open" = public-signup gate applies; "closed" =
   *  being enabled is the admission decision. SAML and LDAP are always closed. */
  posture: "open" | "closed";
  name: string;
  slug: string;
  email_is_authoritative: boolean;
  /** Per-kind non-secret settings (issuer/client_id for OIDC; IdP/SP entity ids,
   *  SSO URL and cert for SAML; server/bind/search settings for LDAP). Values
   *  are strings apart from LDAP's use_starttls flag; the shape is owned by the
   *  backend's per-kind config model. */
  config: Record<string, string | boolean | null>;
  enabled: boolean;
  created_at: string;
  secret_set: boolean;
  /** OIDC only: the exact callback URL to register at the IdP. Server-computed,
   *  since it depends on PUBLIC_BASE_URL — a mismatch is the commonest setup
   *  failure. Empty for non-OIDC kinds. */
  redirect_uri: string;
}

/** Support tickets (§4.4, ROADMAP #18). */
export type TicketStatus = "open" | "resolved";

/** A screenshot attached to a ticket message (issue #80). The bytes come from
 *  the API's `/content` route, never a storage URL — the production CSP allows
 *  `img-src 'self' … blob:` only, so a cross-origin MinIO URL wouldn't load. */
export interface TicketAttachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploader_user_id: string;
  created_at: string;
}

export interface TicketMessage {
  id: string;
  author_user_id: string;
  author_name: string;
  body: string;
  is_internal: boolean;
  created_at: string;
  attachments: TicketAttachment[];
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

/** Feedback / surveys (ROADMAP #22). */
export type QuestionType =
  | "rating_1_10"
  | "rating_1_5"
  | "short_text"
  | "long_text"
  | "multiple_choice";

export interface SurveyQuestion {
  id: string;
  prompt: string;
  type: QuestionType;
  options: string[];
  required: boolean;
  position: number;
}

export interface QuestionInput {
  prompt: string;
  type: QuestionType;
  options: string[];
  required: boolean;
}

export interface SurveySummary {
  id: string;
  title: string;
  description: string | null;
  is_open: boolean;
  question_count: number;
  response_count: number;
  created_at: string;
  /** For a competitor: whether they've responded. null for staff. */
  responded: boolean | null;
}

export interface SurveyDetail extends SurveySummary {
  questions: SurveyQuestion[];
}

export interface QuestionResults {
  question_id: string;
  prompt: string;
  type: QuestionType;
  answered: number;
  average: number | null;
  counts: Record<string, number> | null;
  texts: string[] | null;
}

export interface SurveyResults {
  survey_id: string;
  title: string;
  response_count: number;
  questions: QuestionResults[];
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

/** Per-challenge analytics (ROADMAP #23). */
export interface ChallengeAnalytics {
  challenge_id: string;
  title: string;
  category: string | null;
  points: number;
  state: string;
  solve_count: number;
  attempt_count: number;
  fail_count: number;
  completion_rate: number; // 0..1
  avg_solve_time_seconds: number | null;
  hints_used: number;
  ticket_count: number;
  avg_rating: number | null;
  rating_count: number;
}

export interface ChallengeAnalyticsReport {
  mode: string;
  subject_count: number;
  challenges: ChallengeAnalytics[];
}

export interface TeamAnalytics {
  subject_id: string;
  name: string;
  rank: number;
  points: number;
  solve_count: number;
  first_bloods: number;
  ticket_count: number;
  last_solve_at: string | null;
}

export interface TeamAnalyticsReport {
  mode: string;
  teams: TeamAnalytics[];
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

/** Per-user notification preferences (§4.4). `inapp_*` gate whether a bell
 *  notification is created; `browser`/`sound` are client-honored delivery
 *  hints for the notifications that are made. */
export interface NotificationPreferences {
  inapp_tickets: boolean;
  inapp_automations: boolean;
  /** A `critical` announcement is delivered even when this is off (#40). */
  inapp_announcements: boolean;
  browser: boolean;
  sound: boolean;
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

/** One raw flag-submission attempt (staff-only submissions browser, ROADMAP
 *  #76) — the exact payload and timestamp, for dispute resolution. */
export type SubmissionCorrectness = "correct" | "incorrect" | "duplicate";

export interface SubmissionEntry {
  id: string;
  challenge_id: string;
  user_id: string;
  team_id: string | null;
  value: string;
  correctness: SubmissionCorrectness;
  points_awarded: number;
  created_at: string;
}

export interface SubmissionPage {
  items: SubmissionEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface SubmissionQuery {
  challenge_id?: string;
  user_id?: string;
  team_id?: string;
  correctness?: SubmissionCorrectness;
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
  mc_guess_limit?: number | null;
  mc_penalty_pct?: number | null;
  challenge_ratings_enabled?: boolean;
  challenge_tags?: string[];
  difficulty_tiers?: string[];
  public_scoreboard?: boolean;
  ctftime_enabled?: boolean;
  brackets?: string[];
  max_team_size?: number | null;
  paused?: boolean;
  rules_override?: RichTextDoc | null;
  rules_display_only?: boolean;
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
  affiliation: string | null;
  country: string | null;
  website: string | null;
  created_at: string;
}

/** A member's view of their own team. */
export interface MyTeam {
  id: string;
  competition_id: string;
  name: string;
  invite_code: string;
  members: TeamMember[];
  affiliation: string | null;
  country: string | null;
  website: string | null;
  approval_required: boolean;
  created_at: string;
}

/** Captain-editable team profile (PATCH). */
export interface TeamUpdate {
  name?: string;
  affiliation?: string | null;
  country?: string | null;
  website?: string | null;
  approval_required?: boolean;
}

/** Result of joining: an open team returns it; an approval-required one is
 *  pending until the captain approves. */
export interface TeamJoinResult {
  pending: boolean;
  team: MyTeam | null;
}

/** A pending join request (captain's view). */
export interface TeamApplication {
  id: string;
  user_id: string;
  display_name: string;
  created_at: string;
}

/** Per-competition health row on the site-admin dashboard (§6.3). */
export interface CompetitionHealth {
  id: string;
  name: string;
  status: "draft" | "scheduled" | "running" | "ended" | "archived";
  visibility: Visibility;
  participation_mode: ParticipationMode;
  participants: number;
  published_challenges: number;
  solves: number;
  open_tickets: number;
  created_at: string;
}

/** The site-admin overview: platform totals + per-competition health. */
export interface AdminOverview {
  total_users: number;
  active_users: number;
  total_competitions: number;
  active_competitions: number;
  archived_competitions: number;
  total_teams: number;
  total_challenges: number;
  published_challenges: number;
  total_submissions: number;
  total_solves: number;
  competitions: CompetitionHealth[];
}

/** An account in the admin user directory (Admin → Users, §7). */
export interface UserAccount {
  id: string;
  email: string | null;
  display_name: string;
  is_active: boolean;
  is_administrator: boolean;
  created_at: string;
}

/** A personal API token (issue #75) — never carries the raw value or its hash. */
export interface ApiToken {
  id: string;
  user_id: string;
  user_display_name: string;
  description: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** The mint response — carries the raw token once, never shown again. */
export interface ApiTokenCreated extends ApiToken {
  token: string;
}

/** A loaded module's per-competition state (Admin → Plugins, §11.3). */
export interface ModuleState {
  id: string;
  name: string;
  version: string;
  enabled: boolean;
  required_core: boolean;
}

/** A single competitor in an individual-mode competition's roster. */
export interface Participant {
  user_id: string;
  display_name: string;
  joined_at: string;
  rank: number | null;
  points: number;
  solve_count: number;
}

// A manual award (§5.3): title + description + points granted to a competitor.
export interface AwardInput {
  user_ids: string[];
  title: string;
  description?: string;
  points: number;
}

export interface Award {
  id: string;
  title: string;
  description: string | null;
  points: number;
  user_id: string | null;
  created_at: string;
}

export interface Category {
  id: string;
  competition_id: string;
  name: string;
  created_at: string;
}

export type FlagType = "static" | "regex" | "multiple_choice";
export type ChallengeState = "draft" | "published";
export type ScoringType = "static" | "dynamic";

/** TipTap/ProseMirror document. */
export type RichTextDoc = Record<string, unknown>;

export interface Challenge {
  id: string;
  competition_id: string;
  title: string;
  description: RichTextDoc;
  category_id: string | null;
  /** Configured value — the *initial* worth for dynamic challenges. */
  points: number;
  scoring_type: ScoringType;
  min_points: number | null;
  decay: number | null;
  /** Current worth given the solve count (== points for static, decayed for
   *  dynamic). This is what cards should display. */
  value: number;
  /** Scheduled release time; null = released on publish. Competitors never see
   *  a challenge before this (staff do, badged "Scheduled"). */
  release_at: string | null;
  /** Prerequisite challenge ids (unlock chain) + whether this challenge is
   *  currently locked for the requesting subject. Staff always see locked=false. */
  prerequisites: string[];
  locked: boolean;
  /** Metadata from the competition's managed vocab. */
  tags: string[];
  difficulty: string | null;
  state: ChallengeState;
  flag_type: FlagType;
  case_insensitive: boolean;
  /** The only flag-related fact the server ever returns (§13.2). */
  has_flag: boolean;
  /** Multiple-choice options shown to the competitor (correct one is hidden). */
  choices: string[] | null;
  /** Guesses left for the subject on a multiple-choice challenge under the
   *  competition cap; null = no cap / not multiple-choice / already solved. */
  attempts_remaining: number | null;
  /** The multiple-choice challenge's current worth for the requesting subject
   *  after their wrong guesses so far, under the competition's wrong-guess
   *  penalty (#148). Null unless a penalty has already reduced it below `value`. */
  subject_value: number | null;
  /** The requesting user's own 1–5 rating, or null if unrated (post-solve prompt). */
  my_rating: number | null;
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
  scoring_type?: ScoringType;
  min_points?: number | null;
  decay?: number | null;
  release_at?: string | null;
  prerequisites?: string[];
  tags?: string[];
  difficulty?: string | null;
  flag_type?: FlagType;
  case_insensitive?: boolean;
  flag?: string | null;
  /** Options for a multiple_choice challenge (the correct one is `flag`). */
  choices?: string[] | null;
}

export type ChallengeUpdate = Partial<ChallengeCreate>;

/** One subject that solved a challenge (the "who solved this" list). */
export interface ChallengeSolver {
  subject_id: string;
  name: string;
  solved_at: string;
  is_first_blood: boolean;
}

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
  /** Guesses left on a multiple-choice challenge after this attempt (null = no cap). */
  attempts_remaining: number | null;
  /** Base worth before the multiple-choice wrong-guess penalty (#148), so the
   *  result can show "reduced from N". Null unless a penalty lowered this award. */
  full_value: number | null;
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
  /** The subject's chosen bracket/division, or null. */
  bracket: string | null;
}

export interface Scoreboard {
  competition_id: string;
  mode: ParticipationMode;
  entries: ScoreboardEntry[];
  /** True when these standings are a frozen snapshot (§13 scoreboard freeze). */
  frozen: boolean;
  frozen_at: string | null;
  /** The competition's bracket/division vocab (empty = no brackets). */
  brackets: string[];
}

/** The spectator (no-login) board for a public competition. */
export interface PublicScoreboard extends Scoreboard {
  name: string;
  start_at: string | null;
  end_at: string | null;
}

/** A competition listed in the public /public directory. */
export interface PublicCompetition {
  id: string;
  name: string;
  participation_mode: ParticipationMode;
  start_at: string | null;
  end_at: string | null;
}

/** Spectator context for a public competition (#24). Every score-derived figure
 *  respects a scoreboard freeze exactly like the board it accompanies. */
/** One awarded solve in the public recent-solves feed (venue mode, #77).
 *  `is_first_blood` marks the earliest solve of its challenge — what the venue
 *  splash fires on. Freeze-aware, so a frozen board emits none after the cutoff.
 *  (Distinct from the dashboard's `RecentSolve`, which is a different shape.) */
export interface PublicRecentSolve {
  challenge_id: string;
  title: string;
  subject_name: string;
  solved_at: string;
  points: number;
  is_first_blood: boolean;
}

export interface PublicActivity {
  recent_solves: PublicRecentSolve[];
}

export interface PublicInsights {
  frozen: boolean;
  frozen_at: string | null;
  stats: {
    participants: number;
    solves: number;
    challenges: number;
    unsolved: number;
  };
  highlights: {
    most_solved: { title: string; count: number } | null;
    most_attempted: { title: string; count: number } | null;
    first_blood_leader: { name: string; count: number } | null;
    fastest_solve: { title: string; name: string; seconds: number } | null;
  };
  timeline: {
    start: string | null;
    end: string | null;
    /** Cumulative points per subject for the top entrants; each series ends on
     *  that subject's board total. */
    series: {
      subject_id: string;
      name: string;
      points: { t: string; points: number }[];
    }[];
  };
}

/** A broadcast announcement (Phase 8). */
/** Urgency ladder (#40). `critical` overrides a muted in-app notification
 *  category and doesn't auto-dismiss from the banner. */
export type AnnouncementSeverity = "info" | "warning" | "critical";

/** Who an announcement went to. "all" = the whole competition. */
export type AnnouncementAudience = "all" | "teams" | "users";

export interface Announcement {
  id: string;
  competition_id: string;
  title: string;
  body: string;
  severity: AnnouncementSeverity;
  audience_type: AnnouncementAudience;
  /** Team or user ids, per `audience_type`; empty for "all". Only meaningful
   *  to staff — a recipient only ever receives announcements meant for them. */
  audience_ids: string[];
  created_at: string;
}

/** What the composer sends. `audience_ids` is ignored for "all". */
export interface AnnouncementCreate {
  title: string;
  body: string;
  severity: AnnouncementSeverity;
  audience_type: AnnouncementAudience;
  audience_ids: string[];
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
  registration_open: boolean;
  // Path to the custom org logo (absolutized to the API origin by the hook), or
  // null to use the built-in Flagpost mark.
  logo_url: string | null;
  // Whether the platform-name wordmark shows beside the logo in the lockup.
  show_wordmark: boolean;
  // Demo instance (config-driven): drives the "resets hourly" banner + the
  // login-page demo credentials.
  demo_mode: boolean;
  // Archived-competition retention (#26) — public so the archive confirm can
  // show the exact deletion date to edit_competition holders.
  archive_auto_delete: boolean;
  archive_retention_days: number;
  // Whether public registration currently requires an email (the email-domain
  // allowlist, #56, or email verification, #74, is enabled). Neither policy's
  // internals are public.
  email_required: boolean;
  // Whether an unverified account is blocked from joining a competition
  // (#74). Public so the join button / profile banner can explain a 403.
  email_verification_enabled: boolean;
}

// Admin shape adds the last-updated timestamp.
export interface SiteSettingsAdmin extends SiteSettings {
  updated_at: string | null;
}

/** Operational site config (Admin → Site settings): registration + SMTP. */
export interface OperationalSettings {
  registration_open: boolean;
  smtp_host: string | null;
  smtp_port: number;
  smtp_username: string | null;
  smtp_from: string;
  smtp_starttls: boolean;
  smtp_password_set: boolean;
  /** Archived-competition retention (#26). */
  archive_auto_delete: boolean;
  archive_retention_days: number;
  /** Email-domain allowlist for public registration (#56). Admin-only. */
  email_domain_allowlist_enabled: boolean;
  allowed_email_domains: string[];
  /** Email verification gate (#74). Enabling it requires SMTP configured. */
  email_verification_enabled: boolean;
  /** Daily update check + anonymous adoption count (#111). On by default; this
   *  is the operator's off switch. The timestamp and status sit beside it so an
   *  admin can tell whether the check is working, rather than inferring it from
   *  the absence of a notice. */
  update_checks_enabled: boolean;
  last_update_check_at: string | null;
  last_update_check_status: string | null;
  /** What this deployment runs — a release like "1.2.0" from an image, or
   *  "1.2.0-src" from a source build — vs. the newest the
   *  endpoint has reported. `update_available` folds in the dismissal. */
  current_version: string;
  latest_known_version: string | null;
  /** Raw fact: a newer release exists. Not dismissal-adjusted — the settings
   *  page must stay truthful after the banner is dismissed. */
  update_available: boolean;
  /** Whether the current latest has been waved away. The banner shows when
   *  `update_available && !update_notice_dismissed`. */
  update_notice_dismissed: boolean;
  updated_at: string | null;
}

/** First-run setup wizard (ADR-0017). */
export interface SetupStatus {
  needs_setup: boolean;
}

export interface SetupRequest {
  admin: { display_name: string; password: string; email?: string };
  platform_name: string;
  default_palette: string;
  accent: string;
  registration_open: boolean;
  /** Update check + anonymous adoption count (#111), offered at first run so an
   *  operator can decline before the first check fires. */
  update_checks_enabled: boolean;
}

/** A platform export document (Admin → Site settings → Export). Opaque data — the
 *  frontend only round-trips it back to the import endpoint. */
export interface BackupDocument {
  flagpost_export: boolean;
  schema_version: number;
  exported_at: string;
  sections: string[];
  data: Record<string, unknown[]>;
}

/** Per-table create/skip counts returned by an import. */
export type BackupImportResult = Record<string, { created: number; skipped: number }>;

export interface OperationalSettingsUpdate {
  registration_open: boolean;
  smtp_host: string | null;
  smtp_port: number;
  smtp_username: string | null;
  smtp_from: string;
  smtp_starttls: boolean;
  /** Omit / null to keep the stored password; a value replaces it. */
  smtp_password?: string | null;
  archive_auto_delete: boolean;
  archive_retention_days: number;
  email_domain_allowlist_enabled: boolean;
  allowed_email_domains: string[];
  email_verification_enabled: boolean;
  update_checks_enabled: boolean;
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
  user_email: string | null;
  user_display_name: string;
  role_id: string;
  role_name: string;
  role_scope: RoleScope;
  competition_id: string | null;
  competition_name: string | null;
}

// --- AI assistants (#98, ADR-0023) ------------------------------------------

/** How much a competitor assistant may say (site default, per-competition
 *  override arrives in a later phase). Surfaced now so the admin form can set
 *  the inheritable default. */
export type AiGuidanceLevel = "platform_only" | "conceptual" | "guided";

/** Site-level provider config (Admin → Site settings → AI). The API key is
 *  write-only — only `api_key_set` is ever read back. */
export interface AiSettings {
  enabled: boolean;
  base_url: string | null;
  model: string | null;
  max_output_tokens: number;
  competitor_max_output_tokens: number;
  request_timeout_s: number;
  admin_prompt_override: string | null;
  competitor_prompt_override: string | null;
  default_guidance_level: AiGuidanceLevel;
  api_key_set: boolean;
  updated_at: string | null;
}

/** Update payload — every field optional (partial update). Omit `api_key` to
 *  keep the stored one; `""` clears it (a keyless local endpoint). */
export interface AiSettingsUpdate {
  enabled?: boolean;
  base_url?: string | null;
  model?: string | null;
  api_key?: string;
  max_output_tokens?: number;
  competitor_max_output_tokens?: number;
  request_timeout_s?: number;
  admin_prompt_override?: string | null;
  competitor_prompt_override?: string | null;
  default_guidance_level?: AiGuidanceLevel;
}

/** One leg of the provider test-connection probe. */
export interface AiConnectionCheck {
  ok: boolean;
  detail: string;
}

export interface AiConnectionResult {
  completion: AiConnectionCheck;
  tool_call: AiConnectionCheck;
  model: string;
}

export interface AiConversation {
  id: string;
  assistant_type: string;
  created_at: string;
  closed_at: string | null;
}

/** A conversation plus its full message history — returned when opening the
 *  chat, so the window hydrates (resumes) in one call. */
export interface AiConversationDetail extends AiConversation {
  messages: AiMessage[];
}

export interface AiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Names of the tools the assistant turn invoked (metadata only). */
  tool_calls: { name: string }[] | null;
  created_at: string;
}

export interface AiUsage {
  input_tokens: number;
  output_tokens: number;
  message_count: number;
}

/** Which assistant(s) the caller may open here — the audience-aware launcher
 *  gate. Both false when the module is off/unconfigured. */
export interface AiAvailability {
  admin: boolean;
  competitor: boolean;
  /** Whether the caller accepted the competitor disclosure (only meaningful
   *  when `competitor` is true) — drives the first-run modal. */
  competitor_disclosure_accepted: boolean;
}

export type AiAssistantType = "admin" | "competitor";

/** Per-competition competitor-assistant controls (organiser view).
 *  `guidance_level` is the raw override (null = inherit the site default);
 *  `effective_guidance_level` is what actually applies. */
export interface AiCompetitionSettings {
  competitor_enabled: boolean;
  guidance_level: AiGuidanceLevel | null;
  effective_guidance_level: AiGuidanceLevel;
  challenge_metadata_access: boolean;
  updated_at: string | null;
}

export interface AiCompetitionSettingsUpdate {
  competitor_enabled?: boolean;
  /** Omit to leave unchanged; null clears the override (inherit). */
  guidance_level?: AiGuidanceLevel | null;
  challenge_metadata_access?: boolean;
}

/** One competitor conversation in the organiser's transcript-review list. */
export interface AiTranscriptSummary {
  id: string;
  user_id: string;
  user_display_name: string;
  assistant_type: string;
  message_count: number;
  created_at: string;
  /** When the thread was last active (newest message) — the sort key and the
   *  "last seen" shown for a long-lived resumed conversation. */
  last_activity_at: string;
  closed_at: string | null;
}

export interface AiTranscriptDetail extends AiTranscriptSummary {
  messages: AiMessage[];
}
