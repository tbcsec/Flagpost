// -----------------------------------------------------------------------------
// PLACEHOLDER DATA — NOT WIRED TO A BACKEND.
//
// These sample rows come straight from the design handoff mock. They exist so
// the not-yet-built sections (admin global dashboard, admin users) render as the
// design intends while their features are still on the roadmap. Every consumer
// of this module is a
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
