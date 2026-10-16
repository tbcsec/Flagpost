Competitions are the tenancy unit: each has its own challenges, roster,
teams, scoreboard, settings and staff. **Admin → Competitions** manages them
site-wide; **Admin → Dashboard** shows each one's status and health.

![Competitions](assets/competitions.png)
*Every competition on the instance, with its mode, visibility and lifecycle
actions.*

## Creating

**New competition** asks for a name and description, the **Participation
mode** (team or individual), **Visibility** (*Private* by default, or
*Public*), whether to publish a **public scoreboard**, an optional
**Starts** / **Ends** schedule, and which optional **Modules** the event
runs — AI Assistants, Analytics, Automations, Certificates, Challenge
Instances, Code Judge, Feedback & Surveys, Post-Event Reports. All start on;
switch off what the event won't use (judges can change this later in the
competition's Settings → Modules). Rules, divisions, registration fields and
the registration window are configured on the competition afterwards,
usually by its judges.

!!! note "Three modules need site setup first"
    AI Assistants, Challenge Instances and Code Judge do nothing until you've
    configured them under Site settings (AI — chapter 2; Instances and Code
    judge — chapter 6). The per-competition toggle alone isn't enough.

## Access

A **public** competition is listed in the lobby and the competition switcher
and joinable by anyone signed in. A **private** one is entered only with
its invite code or a **join link** the judges mint (Settings → Sharing).
Public registration being open or closed (chapter 2) composes with this: a
closed site with a private competition is a fully provisioned, private
event. If email verification is on, it gates joining too.

## Cloning

**Clone** copies a competition's settings, categories, challenges (with
their flags), hints, files, surveys and module toggles into a fresh event —
without participants, scores, tickets or a schedule. It's the fast path for
recurring events, and the safe place for staff to rehearse flag submissions
(their solves on the live event are real).

## Archiving and deletion

- **Archive** closes a finished event and hides it from the switcher and
  lobby; everything is retained and it can be unarchived at any time —
  unless **data retention** (chapter 2) is on, in which case the archive
  dialog shows the exact date it will be purged.
- **Delete** is immediate and permanent — challenges, teams, submissions,
  scores, tickets, surveys. Prefer archive unless you genuinely need the data
  gone; if you might ever want the history, export a backup first (chapter
  7).
