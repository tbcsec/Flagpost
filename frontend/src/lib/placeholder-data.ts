// -----------------------------------------------------------------------------
// PLACEHOLDER DATA — NOT WIRED TO A BACKEND.
//
// These sample rows come straight from the design handoff mock. They exist so
// the not-yet-built sections (admin global dashboard) render as the design
// intends while their features are still on the roadmap. Every consumer of this
// module is a screen that needs a real endpoint before it does anything.
//
// See docs/UI-INTEGRATION-NOTES.md for the wired-vs-placeholder breakdown and
// which roadmap phase lights each of these up for real.
// -----------------------------------------------------------------------------

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
