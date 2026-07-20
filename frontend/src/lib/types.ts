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
  created_at: string;
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
