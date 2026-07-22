// -----------------------------------------------------------------------------
// PLACEHOLDER DATA — NOT WIRED TO A BACKEND.
//
// These sample rows come straight from the design handoff mock. They exist so
// the not-yet-built sections (dashboard widgets, scoreboard, support, analytics,
// admin users/roles/plugins, notifications) render as the design intends while
// their features are still on the roadmap. Every consumer of this module is a
// screen that needs a real endpoint before it does anything.
//
// See docs/UI-INTEGRATION-NOTES.md for the wired-vs-placeholder breakdown and
// which roadmap phase lights each of these up for real.
// -----------------------------------------------------------------------------

export interface DirectoryUser {
  id: string;
  name: string;
  email: string;
  role: "admin" | "judge" | "participant";
  status: "Active" | "Banned";
}

export const DIRECTORY_USERS: DirectoryUser[] = [
  { id: "u1", name: "Ada Lovelace", email: "ada@university.edu", role: "admin", status: "Active" },
  { id: "u2", name: "Grace Hopper", email: "grace@university.edu", role: "judge", status: "Active" },
  { id: "u3", name: "Katherine Johnson", email: "katherine@university.edu", role: "judge", status: "Active" },
  { id: "u4", name: "Alan Turing", email: "alan@university.edu", role: "participant", status: "Active" },
  { id: "u5", name: "Margaret Hamilton", email: "margaret@university.edu", role: "participant", status: "Banned" },
];

export interface AnalyticsRow {
  title: string;
  solves: number;
  completion: string;
  avgTime: string;
  hints: number;
  tickets: number;
}

export const ANALYTICS: AnalyticsRow[] = [
  { title: "SQL Injection 101", solves: 42, completion: "33%", avgTime: "12m", hints: 6, tickets: 0 },
  { title: "Baby RSA", solves: 18, completion: "14%", avgTime: "16m", hints: 7, tickets: 1 },
  { title: "Stack Smash", solves: 6, completion: "5%", avgTime: "20m", hints: 8, tickets: 2 },
  { title: "Hidden in Plain Sight", solves: 31, completion: "24%", avgTime: "24m", hints: 9, tickets: 0 },
  { title: "ROP Chain Gang", solves: 2, completion: "2%", avgTime: "28m", hints: 10, tickets: 1 },
];

export interface PluginRow {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
}

export const PLUGINS: PluginRow[] = [
  { id: "p1", name: "Support Ticket Plugin", description: "Adds the Support module to competitions.", enabled: true },
  { id: "p2", name: "Digital Surveys Plugin", description: "Post-event feedback surveys.", enabled: true },
  { id: "p3", name: "Discord Bridge", description: "Mirrors announcements to a Discord channel.", enabled: false },
];

export const PERMISSION_CATEGORIES = [
  "Competition Management",
  "Challenges",
  "Scoring",
  "Teams",
  "Support Tickets",
  "Announcements",
  "Users & Roles",
  "Analytics",
  "Dashboard",
  "Automations",
];

export const MODULE_STATUS: { name: string; status: string; variant: "success" | "destructive" }[] = [
  { name: "Support tickets", status: "Healthy", variant: "success" },
  { name: "Email delivery", status: "Healthy", variant: "success" },
  { name: "Background jobs", status: "Healthy", variant: "success" },
  { name: "Object storage", status: "Degraded", variant: "destructive" },
];
