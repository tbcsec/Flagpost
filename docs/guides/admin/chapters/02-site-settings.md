**Admin → Site settings** holds the platform-wide configuration, in tabs:
General, Email, Auth, Rules, Backup, Appearance, AI, Instances and Code
judge. Auth, AI, Instances and Code judge each need their own grant to
appear (chapter 3).

![Site settings](assets/site-settings.png)
*Global — platform-wide, not scoped to a competition.*

## General

- **Registration** — public sign-up open, or closed (then only
  administrators create accounts, or a closed-policy identity provider
  admits them — chapter 4).
- **Username changes** — whether users may rename themselves (once every 30
  days). Switch it off to pin usernames to what was issued; administrators
  can still rename anyone from Admin → Users.
- **Update checks** — once a day the site asks whether a newer release
  exists. The request carries **only the running version** — no identifier,
  hostname or user data. Turn it off if policy demands.
- **Data retention** — when on, an *archived* competition is permanently
  purged after the retention period. The archive dialog shows the exact
  date; unarchiving cancels the clock.

## Email

**SMTP** for outbound mail — password-reset and email-verification links, the
"your email was changed" notice, and the automation *send email* action
(notifications themselves are in-app only). Without SMTP those flows quietly
do nothing — a password reset still *says* a link is on its way — so
configure it early. The password field is write-only.

Two registration controls live here too: an **email domain allowlist**
(subdomains included; makes email mandatory at sign-up; a rejected sign-up
sees only a generic error; also applies to open-policy providers), and
**email verification** — a self-registered account must confirm its address
before it can *join a competition*. It needs SMTP, and admin-created
accounts are exempt.

## Appearance

Site-wide theming — there is deliberately no per-competition theming. The
**platform name**, a **palette** (five built-in, or a custom theme) and an
**accent**; your **logo** (PNG, SVG, WebP or GIF, up to 1 MB); an animated
**sign-in background** on dark palettes; and a public **sign-in notice**.
**Custom themes** are full colour packs built from your brand colours —
**New theme** or **Upload theme**, with a live preview — selected in the
palette grid like any other. Users may override the palette for themselves
from the top bar's Theme menu. The "Powered by Flagpost" footer stays
regardless of branding.

## Rules

The site-wide **Rules / code of conduct** shown before joining *any*
competition that hasn't set its own override — edit it and every such
competition changes at once. **Display only** shows the rules without
requiring acceptance; empty means no rules and no prompt.

## AI

The optional assistants' provider: any OpenAI-compatible endpoint (**Base
URL**, a **Model** that supports tool calling, an optional **API key**),
**Response limits**, and **Test connection**. It ships **off** and can't be
switched on until a URL and model are saved; nothing calls out until then,
and chats flow to the provider you chose — read the privacy notes before
enabling it on a site with minors or sensitive data. Whether competitors get
an assistant is each competition's choice (Settings → Assistant, Judge
guide).

Backup, Auth, Instances and Code judge have chapters of their own.
