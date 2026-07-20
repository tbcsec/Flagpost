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

export interface ScoreRow {
  id: string;
  name: string;
  points: number;
  lastSolve: string;
  mine?: boolean;
}

export const SCOREBOARD: ScoreRow[] = [
  { id: "t1", name: "Segfault Society", points: 1850, lastSolve: "14:22" },
  { id: "t2", name: "Null Terminators", points: 1600, lastSolve: "13:58", mine: true },
  { id: "t3", name: "The Buffer Overflowers", points: 1450, lastSolve: "13:40" },
  { id: "t4", name: "Rubber Duck Debuggers", points: 1200, lastSolve: "12:55" },
  { id: "t5", name: "Kernel Panic", points: 1050, lastSolve: "12:10" },
  { id: "t6", name: "0x1337", points: 900, lastSolve: "11:48" },
  { id: "t7", name: "Cache Money", points: 800, lastSolve: "11:20" },
  { id: "t8", name: "Byte Me", points: 650, lastSolve: "10:55" },
  { id: "t9", name: "Ping Pong Panda", points: 500, lastSolve: "10:30" },
  { id: "t10", name: "Root Access", points: 400, lastSolve: "09:58" },
];

export interface ActivityEvent {
  id: string;
  text: string;
  time: string;
}

export const ACTIVITY: ActivityEvent[] = [
  { id: "a1", text: 'Segfault Society solved "ROP Chain Gang" (+500)', time: "2 min ago" },
  { id: "a2", text: 'Null Terminators solved "Baby RSA" (+250)', time: "8 min ago" },
  { id: "a3", text: 'Kernel Panic submitted an incorrect flag for "Stack Smash"', time: "11 min ago" },
  { id: "a4", text: "New team registered: Cache Money", time: "26 min ago" },
  { id: "a5", text: 'The Buffer Overflowers solved "JWT None Algorithm" (+200)', time: "34 min ago" },
];

export interface Announcement {
  id: string;
  title: string;
  body: string;
  time: string;
}

export const ANNOUNCEMENTS: Announcement[] = [
  { id: "an1", title: "Scoring freeze at T-1h", body: "The scoreboard will freeze one hour before the end.", time: "1h ago" },
  { id: "an2", title: "Forensics category live", body: "Two new forensics challenges are now published.", time: "3h ago" },
  { id: "an3", title: "Welcome", body: "Good luck — read the rules before you start.", time: "1d ago" },
];

export interface Ticket {
  id: string;
  subject: string;
  team: string;
  challenge: string;
  status: "Open" | "Closed";
}

export const TICKETS: Ticket[] = [
  { id: "tk1", subject: "Instance not spawning for Stack Smash", team: "Kernel Panic", challenge: "Stack Smash", status: "Open" },
  { id: "tk2", subject: "Invite code not working", team: "Cache Money", challenge: "", status: "Open" },
  { id: "tk3", subject: "Scoreboard shows wrong rank", team: "Byte Me", challenge: "", status: "Closed" },
  { id: "tk4", subject: "Flag format question", team: "0x1337", challenge: "Baby RSA", status: "Closed" },
];

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

export interface AppNotification {
  id: string;
  from: string;
  text: string;
  time: string;
  unread: boolean;
}

export const NOTIFICATIONS: AppNotification[] = [
  { id: "n1", from: "Grace Hopper (judge)", text: 'Replied to your ticket "Invite code not working".', time: "4 min ago", unread: true },
  { id: "n2", from: "Spring CTF 2026", text: "New announcement: Scoring freeze at T-1h.", time: "1h ago", unread: true },
  { id: "n3", from: "Flagpost", text: 'Your solve on "Baby RSA" was confirmed.', time: "3h ago", unread: false },
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
