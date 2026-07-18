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
