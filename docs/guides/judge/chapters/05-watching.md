## Reading the room

The dashboard's widgets are your event telemetry:

- **Challenge health** — solves vs. attempts per challenge. Many attempts
  and no solves can mean *good and hard* — or broken. Zero attempts usually
  means nobody's found the entry point (or the description undersells it).
- **Recent activity** — the live solve stream. A sudden burst on one
  challenge right after a hint tells you the hint priced correctly; a
  first-blood minutes after release tells you it didn't.
- **Support queue** — open count trending up is the earliest warning you
  have an infrastructure or clarity problem.

## Optional instrumentation

If the modules are enabled for your competition (Settings → Modules):

- **Analytics** — solve funnels, category breakdowns, and activity over
  time on the Analytics page.
- **Feedback** — competitors rate challenges after solving; aggregate
  ratings per challenge show which ones earned their points.
- **Automations** — event-driven rules (announce on first blood, notify a
  webhook on solve spikes, release a hint at a time) via the visual builder
  on the Automations page.
- **Certificates** and **Reports** — panels in Settings for participation
  certificates and the post-event report.

## Closing out

When the schedule ends (or you press Stop), submissions close and the board
settles. If you froze the scoreboard, reveal it at your ceremony. Export the
challenge set for next year, skim the feedback ratings while memories are
fresh, and hand the platform-level wrap-up — archiving the competition,
certificates at scale, backups — to your administrator.

The deeper operational reference — deployment, scaling, integrations — lives
at **docs.flagpost.io**.
