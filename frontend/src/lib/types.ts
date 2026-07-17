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

export interface Competition {
  id: string;
  name: string;
  description: string;
  start_at: string | null;
  end_at: string | null;
  participation_mode: ParticipationMode;
  created_at: string;
}

export interface CompetitionCreate {
  name: string;
  description?: string;
  participation_mode?: ParticipationMode;
  start_at?: string | null;
  end_at?: string | null;
}
