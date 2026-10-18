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
  // Profile picture: null = none. Doubles as the avatar URL cache-buster.
  avatar_updated_at: string | null;
  // When you may next change your username (ISO), or null if now. Drives the
  // profile cooldown notice.
  username_change_allowed_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export type ParticipationMode = "team" | "individual";
export type Visibility = "public" | "private";
/** Gameplay lifecycle (#221): the gate on competitor access. */
export type CompetitionStatus = "not_started" | "running" | "ended";

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
  /** Gameplay lifecycle (#221): the gate on competitor access to challenges +
   *  the scoreboard. not_started → running → ended (reversible). Moved by the
   *  start/stop actions and the schedule; never a plain settings save. */
  status: CompetitionStatus;
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
  /** Scoreboard-freeze instant (null = live). Drives the Controls-panel toggle. */
  scoreboard_frozen_at: string | null;
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

// --- New manager sections (#332) -------------------------------------------

export interface UnsolvedChallenge {
  challenge_id: string;
  title: string;
  points: number;
  attempts: number;
}

export interface DifficultyProgress {
  difficulty: string | null;
  total: number;
  solved: number;
}

export interface TeamActivity {
  subject_id: string;
  name: string;
  submissions: number;
  last_active: string | null;
  idle: boolean;
}

export interface BruteForceSubject {
  subject_id: string;
  name: string;
  wrong: number;
  total: number;
}

export interface ModerationEvent {
  event_name: string;
  actor_name: string | null;
  at: string;
}

export interface InstanceStatusCount {
  status: string;
  count: number;
}

export interface InstanceFailure {
  challenge_title: string;
  reason: string | null;
  at: string;
}

export interface InstanceHealth {
  active_by_status: InstanceStatusCount[];
  failures: InstanceFailure[];
}

/** Per-user dashboard layout customization (§10.2–10.5). Positions are 2D grid
 *  coordinates on a 12-column grid (issue #21). */
export interface DashboardLayoutEntry {
  widget_id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  // Legacy (pre-catalog) field: the old customize UX hid sections in place. The
  // catalog model (#330) instead adds/removes them, so a section is present iff
  // it has an entry. Kept optional to read old saves — a legacy `hidden: true`
  // entry is treated as "not added" (dropped) on load. New saves omit it.
  hidden?: boolean;
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
  /** A well-known upstream ("google" | "microsoft"), derived server-side from
   *  the stored issuer, so the login button can carry the official brand mark.
   *  Null for everything else — the button then renders exactly as before. */
  brand: string | null;
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

/** An input a provider preset needs from the admin before its issuer template
 *  can be resolved (e.g. Microsoft's tenant GUID). `pattern` is a regex the
 *  value must match; `help` explains where to find it. */
export interface PresetParam {
  key: string;
  label: string;
  placeholder: string;
  pattern: string;
  /** Canonicalization applied before the value is substituted into the issuer
   *  template. Entra lowercases the tenant GUID in its discovery doc and `iss`
   *  claim, and the backend's issuer checks are case-sensitive — so an
   *  uppercase paste must be normalized, not saved verbatim to fail at first
   *  sign-in. */
  normalize?: "lowercase" | null;
  help: string;
}

/** The endpoint set + claim map an `oauth2`-kind preset prefills (#193,
 *  ADR-0033). Mirrors the non-secret half of the backend's OAuth2Config; the
 *  client id and secret always come from the admin's own registered app. */
export interface OAuth2PresetConfig {
  authorize_url: string;
  token_url: string;
  userinfo_url: string;
  scopes: string;
  subject_field: string;
  email_field: string | null;
  name_field: string | null;
  /** A userinfo boolean asserting the address is verified (Discord). */
  email_verified_field: string | null;
  /** A separate list endpoint holding verified addresses (GitHub). */
  emails_url: string | null;
  use_pkce: boolean;
}

/** A built-in one-click setup recipe for a well-known IdP (Google, Microsoft
 *  Entra, GitHub, Discord), served by GET /api/admin/auth-providers/presets.
 *  Purely form-prefill data — creation still flows through the ordinary
 *  provider POST, so a preset is not a write path. An OIDC preset sets exactly
 *  one of `issuer` / `issuer_template` (a template carries `{key}` placeholders
 *  resolved from `params`); an `oauth2` preset sets neither and carries
 *  `oauth2` instead. */
export interface ProviderPreset {
  id: string;
  name: string;
  kind: string;
  issuer: string | null;
  issuer_template: string | null;
  /** Multi-tenant only (ADR-0032): dropped into the new provider's
   *  `config.issuer_template` — the pattern the id_token `iss` is validated
   *  against at login. Distinct from `issuer_template` above (form-fill into
   *  `config.issuer`). null for every single-value preset. */
  config_issuer_template: string | null;
  params: PresetParam[];
  /** `oauth2`-kind presets only (#193, ADR-0033): a plain-OAuth2 provider has
   *  no issuer, so the preset carries the endpoint set and the claim map
   *  instead. null on every OIDC preset. */
  oauth2: OAuth2PresetConfig | null;
  scopes: string;
  default_slug: string;
  posture: string;
  /** Where the admin registers the upstream OAuth app (console/portal URL). */
  setup_url: string;
  /** 1–2 sentences of guidance shown on the quick-setup card. */
  notes: string;
}

/** Support tickets (§4.4, ROADMAP #18). */
export type TicketStatus = "open" | "resolved";

/** A screenshot attached to a ticket message (issue #80). The bytes come from
 *  the API's `/content` route, never a storage URL — the production CSP allows
 *  `img-src 'self' … blob:` only, so a cross-origin object-store URL wouldn't load. */
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
  /** A staff answer also sent to everyone as a clarification (#450) — and
   *  whether the judges since withdrew it (then a competitor gets no text). */
  sent_to_all: boolean;
  withdrawn?: boolean;
  created_at: string;
  attachments: TicketAttachment[];
}

/** "question": a competitor's question about a challenge, asked from its page
 *  (#450) — read-only for the asker once sent, resolved once answered. */
export type TicketKind = "support" | "question";

export interface Ticket {
  id: string;
  subject: string;
  kind: TicketKind;
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

/** Entities an automation id-field can reference — drives the name-search
 *  dropdowns that replace raw id text boxes (#212). */
export type EntityRefType =
  | "competition"
  | "challenge"
  | "survey"
  | "hint"
  | "team"
  | "user"
  | "role";

/** The editor catalog (§5.5) — the builder is generated from it. */
export interface CatalogField {
  key: string;
  label: string;
  kind: "text" | "textarea" | "number" | "select" | "string_list" | "keyvalue" | "entity";
  required: boolean;
  options: string[] | null;
  placeholder: string | null;
  templateable: boolean;
  /** For kind "entity": which entity this id references, so the builder renders
   *  a name-search dropdown instead of a raw id box. */
  entity_type: EntityRefType | null;
}

/** A trigger payload field: `key` is stored/interpolated as `{key}`; `label` is
 *  the human name the builder shows in the condition field picker (§5.5). */
export interface TriggerField {
  key: string;
  label: string;
  /** When the field is an id, which entity it references — so a condition value
   *  on it becomes a name dropdown instead of a raw id box. */
  entity_type: EntityRefType | null;
}

export interface TriggerEntry {
  event: string;
  label: string;
  fields: TriggerField[];
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
  // Optional modules to turn off at creation (#252); optional modules default
  // on, so only opt-outs are sent. Create-only — not part of the update shape.
  disabled_modules?: string[];
}

export type CompetitionUpdate = Partial<Omit<CompetitionCreate, "disabled_modules">>;

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
  /** The team's custom registration-field answers (#350). */
  field_values: RegistrationValues;
}

/** Captain-editable team profile (PATCH). */
export interface TeamUpdate {
  name?: string;
  affiliation?: string | null;
  country?: string | null;
  website?: string | null;
  approval_required?: boolean;
  /** Custom registration-field answers for the team (#350). */
  field_values?: RegistrationValues;
}

// --- Custom registration fields (#350) ---------------------------------------

export type RegistrationFieldType = "text" | "textarea" | "select" | "checkbox";

/** An organiser-defined field on a competition. */
export interface RegistrationField {
  id: string;
  key: string;
  label: string;
  field_type: RegistrationFieldType;
  options: string[];
  required: boolean;
  position: number;
}

/** One field definition as authored (no id — the PUT replaces the whole set). */
export interface RegistrationFieldInput {
  key: string;
  label: string;
  field_type: RegistrationFieldType;
  options: string[];
  required: boolean;
  position: number;
}

/** A subject's answers: `{field_key: value}` (string for text/select, bool for
 *  checkbox). */
export type RegistrationValues = Record<string, string | boolean>;

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
  // Profile picture flag/cache-buster — drives the admin "remove picture" action.
  avatar_updated_at: string | null;
}

/** One CSV row's outcome in the mass user import report (#171). `row` is the
 *  line number in the uploaded file (the header is line 1). */
export interface UserImportRow {
  row: number;
  display_name: string;
  email: string | null;
  role: string | null;
  competition: string | null;
  status: "create" | "skip" | "error";
  reason: string | null;
  role_action: "assign" | "skip" | null;
  role_reason: string | null;
}

/** The per-row report POST /api/users/import returns for both phases —
 *  dry-run preview and the commit — so both screens render the same shape. */
export interface UserImportReport {
  dry_run: boolean;
  total: number;
  created: number;
  skipped: number;
  errors: number;
  roles_assigned: number;
  roles_skipped: number;
  ignored_columns: string[];
  rows: UserImportRow[];
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
  /** The manifest's one-liner: the fallback when the UI has no copy of its own. */
  description: string;
  /** An inert module (AI, instances, code judge) not yet switched on site-wide. */
  needs_setup: boolean;
}

/** A site-level catalog entry for an optional module — the at-creation module
 *  picker's source (#252), available before any competition exists. */
export interface ModuleCatalogEntry {
  id: string;
  name: string;
  description: string;
  needs_setup: boolean;
}

// --- Post-event reports (#134, ADR-0030) ------------------------------------

export type ReportStatus = "pending" | "running" | "ready" | "failed";

export interface ReportSection {
  id: string;
  label: string;
}

/** The section/preset/format catalog that drives the "Reports" settings tab. */
export interface ReportCatalog {
  sections: ReportSection[];
  /** preset id → the section ids it pre-selects. */
  presets: Record<string, string[]>;
  formats: string[];
}

export interface ReportCreate {
  sections: string[];
  formats: string[];
  preset?: string | null;
  top_n?: number;
}

export interface CompetitionReport {
  id: string;
  version: number;
  status: ReportStatus;
  config: {
    preset?: string | null;
    sections: string[];
    formats: string[];
    options?: { top_n?: number };
  };
  error: string | null;
  created_at: string;
  completed_at: string | null;
  /** Short-lived signed download URLs, present only when status is "ready". */
  pdf_url: string | null;
  html_url: string | null;
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

// "programming" (#447) has no flag: it's marked by the code judge running the
// competitor's program against the problem's test cases.
export type FlagType = "static" | "regex" | "multiple_choice" | "programming";
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
  /** Where to reach the live service — a URL, `host:port`, or instructions.
   *  Null when the challenge has none, **and** whenever the server withholds it:
   *  competitors don't get it while the challenge is locked (#262). */
  connection_info: string | null;
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
  /** Whether this challenge offers per-subject instances (#266) — drives the
   *  competitor "Launch instance" panel. */
  instanced: boolean;
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
  connection_info?: string | null;
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
  /** Null when a competitor solves a dynamic challenge under a scoreboard
   *  freeze: its worth would reveal the live solve count the freeze hides. */
  points_awarded: number | null;
  /** Null when a competitor solves under a scoreboard freeze: it would reveal
   *  whether anyone has solved the challenge since the cutoff. */
  is_first_blood: boolean | null;
  /** Guesses left on a multiple-choice challenge after this attempt (null = no cap). */
  attempts_remaining: number | null;
  /** Base worth before the multiple-choice wrong-guess penalty (#148), so the
   *  result can show "reduced from N". Null unless a penalty lowered this award,
   *  and null whenever `points_awarded` is. */
  full_value: number | null;
  /** The subject's current worth going forward after this attempt, under the
   *  wrong-guess penalty (#148) — set on an incorrect guess so the open detail
   *  can drop the shown value live. Null when nothing's been docked yet. */
  subject_value: number | null;
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
  /** True when these are live standings read past a freeze in effect — the
   *  staff view (#501). `frozen || live` = competitors see a frozen board. */
  live: boolean;
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

/** Cumulative points-over-time for the authenticated scoreboard (#348) — the
 *  same shape the public insights timeline carries, so the shared chart renders
 *  both. Each series ends on that subject's board total; it honours the same
 *  freeze + bracket scoping as the standings beside it. */
export interface ScoreboardTimeline {
  start: string | null;
  end: string | null;
  series: {
    subject_id: string;
    name: string;
    points: { t: string; points: number }[];
  }[];
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
  /** Scheduled-publish state (#349). On the published feed `hidden` is always
   *  false; the staff scheduled list carries hidden rows with a `publish_at`. */
  hidden: boolean;
  publish_at: string | null;
  /** A clarification (#450) is about one challenge and answers `question`
   *  (the body is the answer). It never says who asked. */
  kind: "announcement" | "clarification";
  challenge_id: string | null;
  question: string | null;
  /** A clarification the judges took back: still listed, but for
   *  competitors without its answer (`body` is empty). */
  withdrawn_at?: string | null;
}

/** A clarification as listed on its challenge's page (#450). */
export interface Clarification {
  id: string;
  question: string | null;
  /** The judges' answer — empty for a competitor once withdrawn. */
  body: string;
  created_at: string;
  withdrawn_at?: string | null;
}

/** What the composer sends. `audience_ids` is ignored for "all". A future
 *  `publish_at` schedules the post (#349); null/past posts it immediately. */
export interface AnnouncementCreate {
  title: string;
  body: string;
  severity: AnnouncementSeverity;
  audience_type: AnnouncementAudience;
  audience_ids: string[];
  publish_at?: string | null;
}

/** A partial edit of a still-scheduled announcement (#349). Content and timing
 *  only — the audience is fixed at creation; `publish_at: null` releases it now. */
export interface AnnouncementUpdate {
  title?: string;
  body?: string;
  severity?: AnnouncementSeverity;
  publish_at?: string | null;
}

/** A hint as a competitor sees it (Phase 9): `body` is null until this subject
 *  has revealed it. Editors receive every body with `revealed: true`. */
export interface Hint {
  id: string;
  challenge_id: string;
  cost: number;
  revealed: boolean;
  body: string | null;
  /** Authoring state (#213), populated for editors — competitors never receive
   *  a hidden hint. `hidden` gates visibility; `release_at` is an optional
   *  scheduled publish time. */
  hidden: boolean;
  release_at: string | null;
}

/** The authoring view returned when creating or updating a hint. */
export interface HintAuthored {
  id: string;
  challenge_id: string;
  body: string;
  cost: number;
  hidden: boolean;
  release_at: string | null;
  created_at: string;
}

/** Partial hint edit (#213). Only the provided fields change; setting `hidden`
 *  false publishes a hidden hint. `release_at: null` clears a schedule. */
export interface HintUpdate {
  body?: string;
  cost?: number;
  hidden?: boolean;
  release_at?: string | null;
}

// Site-wide theme + branding (§9). Public shape (login/register read it).
// A custom brand theme (#323). Admin-managed presets whose token pack the theme
// layer injects at runtime when one is the active `default_palette`.
export type ThemeMode = "dark" | "light";

/** The active theme embedded in the public site-settings payload — the minimum
 *  the runtime paint needs (id + mode + token map), null for a built-in palette. */
export interface ActiveTheme {
  id: string;
  mode: ThemeMode;
  tokens: Record<string, string>;
}

/** A theme preset as the admin manager sees it (GET /api/admin/themes). */
export interface ThemePreset {
  id: string;
  name: string;
  mode: ThemeMode;
  tokens: Record<string, string>;
  source: "builtin" | "custom";
  created_at: string;
}

export interface ThemePresetInput {
  id: string;
  name: string;
  mode: ThemeMode;
  tokens: Record<string, string>;
}

export interface ThemePresetUpdate {
  name?: string;
  mode?: ThemeMode;
  tokens?: Record<string, string>;
}

// One click-to-sign-in demo account on the login card (#360; demo mode only).
export interface DemoCredential {
  label: string;
  description: string;
  identifier: string;
  password: string;
}

export interface SiteSettings {
  platform_name: string;
  default_palette: string;
  accent: string;
  // The active custom theme's token pack (#323) when default_palette names a
  // preset, else null (a built-in palette). Public — needed pre-auth to paint.
  active_theme: ActiveTheme | null;
  // Front-door animated background slug (#195): "none" (flat), "aurora",
  // "gradient", or "constellation". Public so the login/register/public pages
  // render it before there's a session.
  background_style: string;
  // Custom sign-in notice (#197): a ProseMirror doc rendered above the sign-in
  // card via RichTextView, or null for none. Public — the login page is its
  // whole audience.
  login_notice: RichTextDoc | null;
  registration_open: boolean;
  // Path to the custom org logo (absolutized to the API origin by the hook), or
  // null to use the built-in Flagpost mark.
  logo_url: string | null;
  // Whether the platform-name wordmark shows beside the logo in the lockup.
  show_wordmark: boolean;
  // Whether the cross-competition skills web is on site-wide (#364), for gating
  // the Skills nav/tab.
  skills_enabled: boolean;
  // Demo instance (config-driven): drives the "resets hourly" banner.
  demo_mode: boolean;
  // Demo login accounts (#360) the login card renders as click-to-sign-in
  // buttons. Only populated on a demo instance (empty on a production site);
  // data-driven so a custom baseline carries its own accounts.
  demo_credentials: DemoCredential[];
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
  // Whether accounts may rename themselves (#298). Public so the profile page
  // can hide its username card; admin rename is never gated by it.
  username_changes_enabled: boolean;
}

// Admin shape adds the last-updated timestamp.
export interface SiteSettingsAdmin extends SiteSettings {
  updated_at: string | null;
}

/** Operational site config (Admin → Site settings): registration + SMTP. */
export interface OperationalSettings {
  registration_open: boolean;
  /** Self-service rename toggle (#298); admin rename is unaffected. */
  username_changes_enabled: boolean;
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
  /** Self-service rename toggle (#298). Omit to leave unchanged (the
   *  update_checks_enabled pattern — a whole-object PUT must not silently
   *  re-enable a feature an admin turned off). */
  username_changes_enabled?: boolean;
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

// --- challenge instancing (#266, ADR-0036): site infra config ----------------

/** Admin → Site settings → Instances. The registry credential is write-only —
 *  only `registry_credentials_set` is read back (never the value). */
export interface InstanceSettings {
  enabled: boolean;
  backend: string;
  endpoint_url: string | null;
  public_host: string | null;
  registry_credentials_set: boolean;
  tcp_port_min: number;
  tcp_port_max: number;
  default_cpu: number;
  default_memory_mb: number;
  default_pids: number;
  max_concurrent: number;
  egress_policy: string;
  chal_base_domain: string | null;
  spawn_rate_limit: number;
  spawn_rate_window_seconds: number;
  // Kubernetes kind (#320). The bearer token is write-only — only
  // `k8s_bearer_token_set` is read back.
  k8s_namespace: string;
  k8s_bearer_token_set: boolean;
  k8s_ca_cert: string | null;
  k8s_ingress_class: string | null;
  k8s_image_pull_secret: string | null;
  k8s_cluster_cidr: string | null;
}

/** Partial update. Omit `registry_credentials` to keep the stored one; `""`
 *  clears it. */
export interface InstanceSettingsUpdate {
  enabled?: boolean;
  backend?: string;
  endpoint_url?: string | null;
  public_host?: string | null;
  registry_credentials?: string;
  tcp_port_min?: number;
  tcp_port_max?: number;
  default_cpu?: number;
  default_memory_mb?: number;
  default_pids?: number;
  max_concurrent?: number;
  egress_policy?: string;
  // "" clears the base domain.
  chal_base_domain?: string | null;
  spawn_rate_limit?: number;
  spawn_rate_window_seconds?: number;
  // Kubernetes kind (#320). The bearer token is write-only — omit to keep the
  // stored one, `""` clears it. The other fields clear on `""`.
  k8s_namespace?: string;
  k8s_bearer_token?: string;
  k8s_ca_cert?: string;
  k8s_ingress_class?: string;
  k8s_image_pull_secret?: string;
  k8s_cluster_cidr?: string;
}

/** One staged leg of the "Test connection" probe (ADR-0036 §1). */
export interface InstanceConnectionLeg {
  name: string;
  ok: boolean;
  detail: string;
}

export interface InstanceConnectionResult {
  ok: boolean;
  legs: InstanceConnectionLeg[];
}

/** The per-challenge deployment spec (authoring content). At most one per
 *  challenge; the editor upserts it in place. */
export interface ChallengeDeployment {
  id: string;
  challenge_id: string;
  competition_id: string;
  backend: string;
  image_ref: string | null;
  manifest: Record<string, unknown> | null;
  exposure: string;
  ports: number[];
  env: Record<string, string>;
  resource_limits: Record<string, unknown> | null;
  lifetime_s: number | null;
  per_subject_cap: number;
  flag_mode: string;
  flag_template: string | null;
}

/** A connection endpoint on a running instance, as shown to the subject. */
export interface InstanceEndpoint {
  kind: string;
  host?: string | null;
  port?: number | null;
  url?: string | null;
}

/** The requesting subject's own instance of a challenge (#266). Endpoints are
 *  populated only while `status === "running"`. */
export interface Instance {
  id: string;
  challenge_id: string;
  status:
    | "requested"
    | "provisioning"
    | "running"
    | "expiring"
    | "destroyed"
    | "failed";
  endpoints: InstanceEndpoint[];
  expires_at: string | null;
  started_at: string | null;
  extend_count: number;
  failure_reason: string | null;
}

/** The staff ops view of an instance — adds the subject + backend handle the
 *  competitor view hides (GET /competitions/{c}/instances, instance_view). */
export interface AdminInstance extends Instance {
  competition_id: string;
  user_id: string;
  team_id: string | null;
  backend_handle: string | null;
  created_at: string | null;
  last_seen_at: string | null;
  /** Human labels resolved server-side (fall back to ids). subject_label is the
   *  team name (team mode) or the requesting user's display name. */
  challenge_title: string | null;
  subject_label: string | null;
}

/** Upsert payload — the full spec is replaced on each save (PUT). */
export interface ChallengeDeploymentUpdate {
  backend: string;
  image_ref?: string | null;
  manifest?: Record<string, unknown> | null;
  exposure: string;
  ports: number[];
  env: Record<string, string>;
  resource_limits?: Record<string, unknown> | null;
  lifetime_s?: number | null;
  per_subject_cap: number;
  flag_mode: string;
  flag_template?: string | null;
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

// --- Certificates (#219, ADR-0027) -----------------------------------------

export type CertBackgroundKind = "color" | "preset" | "upload";
export type CertRecipientRule = "all" | "solvers";
export type CertReleaseMode = "manual" | "on_end" | "end_delay";
export type CertElementType = "token" | "text" | "image";
export type CertAlign = "left" | "center" | "right";

/** One drag-positioned element. Coordinates are % of the canvas; font_size is
 *  % of canvas height — matching the server renderer (parity, ADR-0027). */
export interface CertElement {
  type: CertElementType;
  x: number;
  y: number;
  width: number;
  font?: string;
  font_size?: number;
  color?: string;
  align?: CertAlign;
  bold?: boolean;
  italic?: boolean;
  token?: string;
  text?: string;
  image_key?: string;
}

export interface CertificateTemplate {
  id: string;
  competition_id: string;
  background_kind: CertBackgroundKind;
  background_preset: string | null;
  background_color: string;
  preset_accent: string | null;
  preset_base: string | null;
  has_background_image: boolean;
  elements: CertElement[];
  recipient_rule: CertRecipientRule;
  release_mode: CertReleaseMode;
  release_delay_minutes: number;
  released_at: string | null;
  released: boolean;
}

export interface CertificateTemplateInput {
  background_kind: CertBackgroundKind;
  background_preset: string | null;
  background_color: string;
  preset_accent: string | null;
  preset_base: string | null;
  elements: CertElement[];
  recipient_rule: CertRecipientRule;
  release_mode: CertReleaseMode;
  release_delay_minutes: number;
}

export interface MyCertificate {
  competition_id: string;
  competition_name: string;
  released_at: string;
}

export interface CertificateAvailability {
  available: boolean;
  released_at: string | null;
  competition_name: string | null;
}

export interface CertificateExportJob {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  total: number;
  rendered: number;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  download_url: string | null;
}

export interface CertManifestFont {
  id: string;
  label: string;
}

/** An organiser-uploaded custom font. Referenced by an element as
 *  `font: "custom:<id>"`; `format` is "ttf" | "otf". */
export interface CertificateFont {
  id: string;
  name: string;
  format: string;
}
export interface CertManifestToken {
  key: string;
  label: string;
  sample: string;
}
export interface CertManifestPreset {
  id: string;
  label: string;
  accent: string;
  base: string;
}
export interface CertificateManifest {
  canvas: {
    width: number;
    height: number;
    aspect_ratio: number;
  };
  fonts: CertManifestFont[];
  default_font: string;
  tokens: CertManifestToken[];
  presets: CertManifestPreset[];
  default_color: string;
  bounds: {
    max_elements: number;
    max_text_len: number;
    max_image_elements: number;
    font_size_min: number;
    font_size_max: number;
  };
}

/** Custom pages (#198, ADR-0034) — admin-authored, site-level content shown in
 *  the sidebar and rendered at `/p/{slug}`.
 *
 *  Titles and bodies are **operator-authored data, not UI strings**: they sit
 *  outside the next-intl catalog for the same reason challenge names do, so a
 *  multilingual install shows the same page to every locale. */
export interface PageNavEntry {
  slug: string;
  title: string;
  /** A name from the curated icon set; unknown names fall back to a default
   *  glyph rather than rendering nothing (see `components/app/page-icons.tsx`). */
  icon: string;
  nav_order: number;
}

/** One page's renderable content. */
export interface PageContent extends PageNavEntry {
  content: RichTextDoc | null;
}

/** Authoring view — adds the state only a `manage_pages` holder needs. */
export interface AdminPage extends PageContent {
  id: string;
  visibility: PageVisibility;
  draft: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export type PageVisibility = "public" | "authenticated";

export interface PageWrite {
  slug: string;
  title: string;
  content: RichTextDoc | null;
  icon: string;
  nav_order: number;
  visibility: PageVisibility;
  draft: boolean;
}

// Cross-competition skills web (#364, ADR-0039).
export interface SkillScore {
  skill: string;
  score: number;
}

export interface UserSkills {
  skills: SkillScore[];
  total: number;
  competitions_played: number;
}

// --- Marketplace (module import, #389, ADR-0040) ----------------------------

export interface MarketplaceTrustedKey {
  key_id: string;
  public_key: string; // base64 raw ed25519
  verified: boolean;
  label?: string | null;
}

export interface MarketplaceSettings {
  enabled: boolean;
  registry_url: string;
  trust_policy: string; // official | verified | signed | any
  max_trust_tier: string; // pack | declarative | code
  trusted_keys: MarketplaceTrustedKey[];
}

export interface MarketplaceSettingsUpdate {
  enabled?: boolean;
  registry_url?: string;
  trust_policy?: string;
  max_trust_tier?: string;
  trusted_keys?: MarketplaceTrustedKey[];
}

/** The confirmation payload for a resolved import code. The trust fields are the
 *  registry's claims; the instance re-verifies the signature at install. */
export interface MarketplaceResolveResult {
  id: string;
  name: string;
  version: string;
  kind: string; // pack | module
  pack_type?: string | null;
  trust_tier?: string | null;
  publisher: Record<string, unknown>;
  requires_flagpost: Record<string, unknown>;
  capabilities: string[];
  signature_present: boolean;
  installable: boolean;
}

export interface ContentPackInstallResult {
  id: string;
  name: string;
  version: string;
  pack_type: string;
  target: string; // a competition id, or "site"
  result: Record<string, unknown>;
}

// --- Competition invite links (#427) ---

/** A shareable competition link (join or view) with a managed lifecycle —
 * richer than the permanent competition invite code. */
export interface InviteLink {
  id: string;
  competition_id: string;
  token: string;
  capability: "join" | "view";
  label: string | null;
  expires_at: string | null;
  max_uses: number | null;
  use_count: number;
  /** When the link last admitted someone (new-join semantics, like use_count). */
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  /** Usable right now: not revoked, not expired, uses remaining. */
  active: boolean;
}

/** Create payload — lifecycle fields are optional (null = no limit). */
export interface InviteLinkInput {
  capability: "join" | "view";
  label?: string | null;
  expires_at?: string | null;
  max_uses?: number | null;
}

/** What the public landing gets back for a valid token — no token echo, no
 * counters. `actionable`: join = still admits people; view = board available. */
export interface InviteLinkResolved {
  capability: "join" | "view";
  competition_id: string;
  competition_name: string;
  competition_status: "not_started" | "running" | "ended";
  participation_mode: "team" | "individual";
  actionable: boolean;
  /** Why a join link isn't actionable (#427 Phase 4); null when it is. */
  reason?: "ended" | "registration_not_open" | "registration_closed" | null;
  requires_login: boolean;
}

/** Body for completing a join through a link (mirrors the invite-code path). */
export interface InviteLinkJoinInput {
  accept_rules?: boolean;
  field_values?: Record<string, unknown> | null;
}

// --- Admin skills matrix (#364/#435, ADR-0039) -------------------------------

/** One user×skill cell (#435). `weighted` = Σ points awarded at solve time
 * (decay rarity included — but points don't normalize across competitions, so
 * compare via `pct`); `solved`/`available` = coverage against the user's member
 * competitions; `pct` = percentile of `weighted` within the column. */
export interface SkillCell {
  weighted: number;
  solved: number;
  available: number;
  pct: number;
  /** v2 (#440): counts, not ratios — derive per-solve client-side. */
  attempts: number;
  hints: number;
  first_bloods: number;
}

export interface SkillPopulation {
  solvers: number;
  mean_weighted: number;
}

export interface SkillMatrixUser {
  user_id: string;
  display_name: string;
  scores: Record<string, SkillCell>; // missing key = untouched category
  total: number;
  total_weighted: number;
}

export interface SkillMatrix {
  skills: string[]; // the shared axis (columns)
  users: SkillMatrixUser[];
  population: Record<string, SkillPopulation>;
  total_users: number;
  limit: number;
  offset: number;
}

export type SkillWindow = "all" | "365" | "90" | "30";

export interface SkillMatrixQuery {
  limit: number;
  offset: number;
  sort?: string; // "total" or a skill key
  direction?: "asc" | "desc";
  window?: SkillWindow;
  q?: string; // display-name substring search
}

/** The admin drill-down (#440). */
export interface AdminUserSkillRow {
  skill: string;
  weighted: number;
  solved: number;
  attempts: number;
  hints: number;
  first_bloods: number;
}

export interface AdminUserSolve {
  challenge_title: string;
  competition_name: string;
  skill: string;
  points_awarded: number;
  attempts: number;
  hints: number;
  first_blood: boolean;
  solved_at: string;
}

export interface AdminUserSkills {
  user_id: string;
  display_name: string;
  skills: AdminUserSkillRow[];
  solves: AdminUserSolve[];
  total: number;
  total_weighted: number;
}

// --- Code judge (#446, ADR-0042) --------------------------------------------

/** Site judge configuration (Admin → Site settings → Code judge). */
export interface JudgeSettings {
  enabled: boolean;
  executor: string;
  endpoint_url: string | null;
  max_concurrent_judgings: number;
  default_time_limit_ms: number;
  default_memory_limit_mb: number;
  default_output_limit_kb: number;
  /** What the form prefills when no endpoint is stored: the instancing proxy
   *  if configured, else the compose default. Never stored by itself. */
  suggested_endpoint_url: string;
  /** Set by the deployment (`JUDGE_ENDPOINT_URL`, from the
   *  docker-compose.judge.yml overlay) — shown as detected, not editable. */
  endpoint_managed: boolean;
}

/** Partial update. `endpoint_url: ""` clears it. */
export interface JudgeSettingsUpdate {
  enabled?: boolean;
  executor?: string;
  endpoint_url?: string;
  max_concurrent_judgings?: number;
  default_time_limit_ms?: number;
  default_memory_limit_mb?: number;
  default_output_limit_kb?: number;
}

/** A language the judge can run: a stock image plus argv compile/run
 *  commands, which may only use the `{source}` and `{work}` placeholders. */
export interface JudgeLanguage {
  id: string;
  key: string;
  name: string;
  image_ref: string;
  source_filename: string;
  compile_command: string[] | null;
  run_command: string[];
  time_multiplier: number;
  enabled: boolean;
}

export interface JudgeLanguageCreate {
  key: string;
  name: string;
  image_ref: string;
  source_filename: string;
  compile_command: string[] | null;
  run_command: string[];
  time_multiplier: number;
  enabled: boolean;
}

/** The key is immutable once created (problems refer to it). An explicit
 *  `compile_command: null` clears the compile step; omitting leaves it. */
export type JudgeLanguageUpdate = Partial<Omit<JudgeLanguageCreate, "key">>;

/** A built-in language definition. Adding one creates an ordinary language
 *  from it; which presets are already added is a join on `key`. */
export interface JudgeLanguagePreset {
  key: string;
  name: string;
  image_ref: string;
  source_filename: string;
  compile_command: string[] | null;
  run_command: string[];
  time_multiplier: number;
}

/** One leg of the setup flow's "Check connection". */
export interface JudgeCheckLeg {
  name: string;
  ok: boolean;
  detail: string;
}

export interface JudgeCheckResult {
  ok: boolean;
  legs: JudgeCheckLeg[];
}

export interface JudgeSetupResult {
  settings: JudgeSettings;
  languages: JudgeLanguage[];
}

// Programming challenges (#447): whether this competition can have them, and in
// which languages (key + display name only).
export interface JudgeStatus {
  module_enabled: boolean;
  judge_enabled: boolean;
  ready: boolean;
  languages: { key: string; name: string }[];
  /** The site default — what an imported package with no limit gets. */
  default_time_limit_ms: number;
}

export type JudgeCompareMode = "token" | "exact" | "float";

export interface JudgeTestcase {
  id: string;
  sample: boolean;
  input_bytes: number;
  answer_bytes: number;
  input_preview: string;
  answer_preview: string;
}

/** One test case in full, for editing. `editable` is false when it's too big
 *  or not text — the editor then offers replacing it by upload instead. */
export interface JudgeTestcaseContent {
  id: string;
  sample: boolean;
  editable: boolean;
  input: string | null;
  answer: string | null;
}

/** A programming problem. Null limits / languages mean "the default", which is
 *  reported alongside so the editor can say what an empty field means. */
export interface JudgeProblem {
  time_limit_ms: number | null;
  memory_limit_mb: number | null;
  output_limit_kb: number | null;
  compare_mode: JudgeCompareMode;
  float_tolerance: number | null;
  /** Letters compare regardless of case (#451). */
  case_insensitive: boolean;
  allowed_languages: string[] | null;
  testcases: JudgeTestcase[];
  default_time_limit_ms: number;
  default_memory_limit_mb: number;
  default_output_limit_kb: number;
}

/** Partial update — an explicit null resets a field to its default. */
export type JudgeProblemUpdate = Partial<
  Pick<
    JudgeProblem,
    | "time_limit_ms"
    | "memory_limit_mb"
    | "output_limit_kb"
    | "compare_mode"
    | "float_tolerance"
    | "case_insensitive"
    | "allowed_languages"
  >
>;

export interface JudgeTestcaseInput {
  input: string;
  answer: string;
  sample: boolean;
}

// --- solving programming challenges (#448/#449) ----------------------------------------

/** `reference` is an author's check of the problem (#450), never a
 *  competitor's — see ReferenceCheck. */
export type CodeSubmissionKind = "submit" | "run" | "reference";
export type JudgingStatus = "queued" | "running" | "done" | "failed";
export type JudgingVerdict =
  | "accepted"
  | "wrong_answer"
  | "time_limit"
  | "memory_limit"
  | "output_limit"
  | "runtime_error"
  | "compile_error"
  | "internal_error";

/** One test's result. For a hidden test only `index` and `verdict` are set. */
export interface JudgingRun {
  index: number;
  sample: boolean;
  verdict: JudgingVerdict;
  time_ms: number | null;
  memory_kb: number | null;
  output: string | null;
}

export type JudgingOrigin = "submission" | "rejudge" | "override";

export interface Judging {
  id: string;
  code_submission_id: string;
  origin: JudgingOrigin;
  /** Staff only: who asked for a rejudge/override, and an override's reason. */
  requested_by_name?: string | null;
  note?: string | null;
  error?: string | null;
  challenge_id: string;
  user_id: string;
  team_id: string | null;
  kind: CodeSubmissionKind;
  language_key: string;
  language_name: string;
  status: JudgingStatus;
  verdict: JudgingVerdict | null;
  queue_position: number | null;
  created_at: string;
  finished_at: string | null;
  compile_output: string | null;
  max_time_ms: number | null;
  max_memory_kb: number | null;
  tests_passed: number | null;
  tests_total: number | null;
  tests: JudgingRun[];
}

export interface CodeSubmitInput {
  language: string;
  source: string;
  kind: "submit" | "run";
}

/** What a problem-package import did (#451). */
export interface PackageImportResult {
  created: { name: string; challenge_id: string; tests: number; warnings: string[] }[];
  skipped: { name: string; reason: string }[];
  refused: { name: string; reason: string }[];
}

/** A problem's latest reference-solution check (#450): every test's result,
 *  plus the source so it can be run again. `stale` — the test cases or limits
 *  changed after it ran. */
export interface ReferenceCheck {
  judging: Judging | null;
  run_by_name: string | null;
  language_key: string | null;
  source: string | null;
  stale: boolean;
}

/** What a competitor needs beside the statement — never the hidden tests. */
export interface ProblemView {
  time_limit_ms: number;
  memory_limit_mb: number;
  output_limit_kb: number;
  compare_mode: JudgeCompareMode;
  float_tolerance: number | null;
  languages: { key: string; name: string; time_limit_ms: number; extension: string }[];
  examples: { index: number; input: string; answer: string; truncated: boolean }[];
  judge_ready: boolean;
}

// --- the jury console (#450) -------------------------------------------------------------

export interface StaffJudgingRow {
  id: string;
  code_submission_id: string;
  challenge_id: string;
  challenge_title: string;
  user_id: string;
  user_name: string;
  team_id: string | null;
  team_name: string | null;
  kind: CodeSubmissionKind;
  origin: JudgingOrigin;
  language_name: string;
  status: JudgingStatus;
  verdict: JudgingVerdict | null;
  submitted_at: string;
  created_at: string;
  finished_at: string | null;
  max_time_ms: number | null;
  max_memory_kb: number | null;
  tests_passed: number | null;
  tests_total: number | null;
  requested_by_name: string | null;
  note: string | null;
}

export interface StaffJudgingPage {
  items: StaffJudgingRow[];
  total: number;
}

export interface JudgingQueue {
  queued: number;
  running: number;
  site_queued: number;
  site_running: number;
  judge_enabled: boolean;
  /** Programming problems in the competition, drafts included. */
  problems: number;
}

export interface JudgingListFilters {
  challenge_id?: string;
  verdict?: string;
  status?: string;
  kind?: CodeSubmissionKind;
}

export type RejudgeScope = "all" | "accepted" | "not_accepted";
