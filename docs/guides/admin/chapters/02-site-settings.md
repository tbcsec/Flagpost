**Admin → Site settings** holds everything platform-wide, in tabs.

![Site settings](assets/site-settings.png)
*Global — platform-wide, not scoped to a competition. General covers
registration, update checks, and data retention; the other tabs are below.*

## General

- **Registration** — open public sign-up, or closed (only administrators
  create accounts). Registration can also be limited to an email **domain
  allowlist**, and email **verification** can be required before sign-in.
- **Update checks** — once a day the site asks whether a newer release
  exists. The request carries **only the running version** — no identifier,
  hostname, or user data. Turn it off entirely if policy demands.
- **Data retention** — when enabled, an *archived* competition is
  permanently purged after the retention period (the archive dialog shows
  the exact date; unarchiving cancels the clock).

## Email

SMTP for outbound mail — password resets, verification, email
notifications. Until it's configured, flows that need mail say so rather
than failing silently.

## Appearance

Site-wide theming (there is deliberately no per-competition theming): the
palette presets (dark and light), the **accent colour** used for actions,
your **logo** replacing the Flagpost mark, and the platform name shown in
the shell. The "Powered by Flagpost" footer stays regardless of branding.

## Rules

The site-wide default rules template competitions start from — each
competition then owns its own copy.

## AI

The optional assistant module's **master switch and provider settings**
(an OpenAI-compatible endpoint you configure). It ships off; nothing calls
out until you configure *and* enable it, and chats flow to the provider you
chose — read the privacy notes before enabling on a site with minors or
sensitive data. Per-competition enablement then lives with the event's
Modules tab.

Backup and Auth have chapters of their own.
