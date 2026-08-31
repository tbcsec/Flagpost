# Privacy

Flagpost is self-hosted. Your competitions, challenges, users and submissions
live in **your** database on **your** infrastructure, and none of it is ever
sent anywhere.

There is exactly one thing Flagpost sends out, described in full below. If you'd
rather it sent nothing at all, [turn it off](#turning-it-off) — that's a
supported configuration, not a grudging one.

## The update check

Once every 24 hours, a Flagpost deployment makes one request:

```
GET https://updates.flagpost.io/v1/check?version=1.2.0
 →  {"latest": "1.3.0"}
```

**It sends your version. That is the entire payload.**

It does two jobs at once. The response is what lets Flagpost tell an
administrator a newer release exists. And counting those requests is the only
way the project can tell how many Flagpost deployments are actually running —
GitHub stars and clone counts measure interest, not use.

### What is not sent

No install identifier. No hostname, domain or IP in the payload. No competition
names, counts or contents. No user accounts, emails or any other personal data.
No configuration. Nothing about your challenges, teams or scores.

There is no field for any of it: the request is a single query parameter.

### Why there's no identifier

Counting *unique* installations would require giving each one an ID, which makes
the data pseudonymous — traceable back to a specific deployment over time. We
deliberately don't do that.

Instead, each deployment checks in **at most once per day**, and that timestamp
is stored in your own database so a restart doesn't cause another check. Counting
the requests then gives a usable estimate of active deployments while carrying
nothing that identifies any of them.

The honest trade: without an identifier the count can't be verified or
de-duplicated, so it's a rough signal rather than an exact figure. We think
that's the right way round.

### What we unavoidably see, and don't keep

Any HTTPS request reveals its source IP address to the server receiving it —
that's how the internet works, not a choice Flagpost makes. The update endpoint
therefore *receives* your IP, and **does not log or store it**. It records
aggregate counts (how many requests, broken down by version) and nothing else.

If your deployment's IP address must never reach a third party at all, don't
rely on that promise — turn the check off, and it will never be sent.

## Turning it off

**In the app:** Admin → Site settings → General → *Update checks* → Off.
You're also asked during first-run setup, before the first check can happen.

**In the environment**, which is stronger — no call is attempted at all, ever,
regardless of what's in the database:

```yaml
environment:
  UPDATE_CHECK_URL: ""
```

Use the environment switch for air-gapped installs. It doesn't depend on a
running application or a database value being correct.

With checks off you'll no longer be told about new releases; watch
[Releases](https://github.com/tbcsec/Flagpost/releases) instead.

## What Flagpost never does

- No analytics or tracking in the web interface. No third-party scripts — the
  Content-Security-Policy blocks external scripts outright.
- No crash or error reporting to any external service.
- The optional Prometheus **`/metrics` endpoint is off by default**, and even
  when you enable it, it is operator-scoped — never public (a scrape needs a
  token you set and/or must come from an IP you allowlist; enabling it with no
  gate is refused at startup). It exposes operational numbers only — request
  counts and latencies, WebSocket and instance counts, database-pool depth —
  never competitor content or personal data. It is a surface *your* monitoring
  pulls from; Flagpost sends nothing.
- No outbound connection of any kind beyond the update check, and whatever *you*
  configure: your SMTP server, any external identity provider you set up (OIDC,
  SAML or LDAP), any automation webhooks you create, the container-runtime
  endpoint (a Docker socket proxy, or a Kubernetes API server) if you enable the
  optional challenge-instancing module, and — if you enable the optional AI
  assistant — the AI model endpoint you point it at. All go wherever you tell
  them to.
- The **AI assistant is off by default**. When you enable it, the messages people
  send it (competitor and organiser chat, plus the competition/challenge details
  its read-only tools surface) are sent to the model endpoint you configure.
  Point it at a self-hosted local model and nothing leaves your infrastructure;
  point it at a hosted provider and that content goes to that provider.
  Competitors are shown a disclosure and must accept it before their first chat.

Note that Flagpost also sets `NEXT_TELEMETRY_DISABLED=1`, so the Next.js
framework's own telemetry is off in the shipped images. Turning off someone
else's collection while running our own would be inconsistent if the two were
comparable — they aren't. Next's telemetry collects build and usage metrics; the
above is one version string, once a day, with no identifier, and can be
disabled.

## Data you control

Everything else is yours and stays in your database. Flagpost includes a full
[export](https://github.com/tbcsec/Flagpost/blob/main/docs/adr/0016-platform-export-import.md)
so you can take it elsewhere or keep an off-site backup. Deleting a competition
deletes its data, including stored files.

If you define **custom registration fields** on a competition (affiliation,
t-shirt size, dietary/accessibility needs, emergency contact, and the like),
those answers are personal data that a competitor gives you directly. They are
stored per subject in your database, **never surfaced publicly** (not on the
scoreboard, the spectator board, or any competitor-facing view), and reach you
only through your own authenticated export — the organiser CSV, or the field
*definitions* in the backup. A competitor can edit their own answers. As with
everything else here, they stay on your infrastructure.

## Questions

Open an issue at https://github.com/tbcsec/Flagpost/issues. For anything
security-sensitive, follow [SECURITY.md](SECURITY.md) instead.
