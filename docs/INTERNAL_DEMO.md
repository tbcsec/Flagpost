# Running an internal demo (custom baseline + scheduled reset)

The public demo (demo.flagpost.io) resets every hour by wiping every volume and
letting `DEMO_MODE` re-seed a hardcoded sample competition and well-known
accounts — its baseline is *code* (`backend/auth/demo.py`), and it isn't meant
to be customised.

An **internal demo** flips that around: you configure a normal Flagpost
instance exactly the way you want it — your branding and theme, your
competitions and challenges, your users and teams — capture that state as a
**baseline snapshot**, and a timer restores the snapshot on a schedule. The
reset is a byte-level volume restore, so *everything* comes back: SSO
providers, SMTP settings, uploaded attachments, the works.

Nothing here touches the public demo stack; this rides the production
`docker-compose.yml` — including any `docker-compose.override.yml` and `.env`
you use, which the scripts honour exactly like your own `docker compose up -d`.

## 1. Deploy the production stack

Follow the README's "Deploying to production" section — the standard
`docker compose up -d` stack with a real `.env`. Everything below assumes the
repo lives at `/opt/flagpost`. If it doesn't, pass the location explicitly
when running the scripts (`sudo` strips a plain `export`):

```bash
sudo FLAGPOST_DIR=/srv/flagpost /srv/flagpost/deploy/internal-demo/snapshot.sh
```

## 2. Configure the baseline in the UI

Complete the first-run setup wizard, then set the instance up as the demo you
want people to see: branding + theme, competitions, challenges, users, teams,
module toggles, pages — anything. Whatever the instance looks like when you
snapshot is exactly what every reset returns to.

Two settings deserve deliberate choices *before* you snapshot, because they
ride the baseline:

- **Turn update checks off** (the setup wizard offers it; later it's Admin →
  Settings). The daily check's "when did I last check" bookkeeping lives in
  the database, so a restored baseline is always a check-due state — left on,
  an hourly-reset instance would phone home ~24×/day and inflate the
  project's anonymous adoption count. Turning it off in-app stores the
  choice *inside* the baseline, so it survives every reset by construction.
  (The `UPDATE_CHECK_URL: ""` environment kill-switch in
  [PRIVACY.md](../PRIVACY.md) works too, as belt and braces.)
- **Leave `DEMO_MODE` off** — see the warning below.

## 3. Capture it

```bash
sudo /opt/flagpost/deploy/internal-demo/snapshot.sh
```

The script stops the volume-writing services (backend, MinIO, Postgres — the
front door keeps answering, with errors, instead of the port going dead),
tars the three data volumes into `deploy/internal-demo/baseline/`, verifies
the tarballs, starts the stack again, and only then swaps the new baseline in
— a failed capture leaves the previous baseline exactly where it was, and one
older baseline is always kept at `baseline.prev/`.

Re-run it any time the baseline should change. Budget disk for roughly twice
your instance's data size, and **treat the baseline directory as secrets**:
it contains the full database (password hashes, provider secrets) and the
instance's JWT-signing and encryption keys. It's `.gitignore`d — don't copy
it anywhere you wouldn't copy a database dump.

## 4. Schedule the reset

```bash
sudo cp /opt/flagpost/deploy/internal-demo/flagpost-internal-demo-reset.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flagpost-internal-demo-reset.timer
systemctl list-timers flagpost-internal-demo-reset.timer   # confirm the next run
```

Hourly on the hour by default; the cadence is one `OnCalendar` line in the
timer, and relocating the checkout is one `Environment=FLAGPOST_DIR=` line in
the service. Run `sudo systemctl start flagpost-internal-demo-reset.service`
to test a reset immediately, and read
`journalctl -u flagpost-internal-demo-reset` when something looks off — the
restore gates on the backend's own container healthcheck and fails the unit
visibly if the stack doesn't come back healthy.

Before any volume is touched, `restore.sh` verifies the baseline is complete,
the tarballs are intact, and the baseline was captured for this compose
project — anything else is a clean refusal that leaves the stack running. It
deliberately never pulls the repo or the app images. To upgrade: stop the
timer, pull new images, `docker compose up -d` (migrations run on boot),
verify, **re-run `snapshot.sh`**, start the timer. (A concurrent
snapshot/restore is also blocked by a lock file, so a mid-snapshot timer tick
refuses rather than tearing the capture.)

## Do not use `DEMO_MODE` for this

`DEMO_MODE=true` is for the public demo instance and CLAUDE.md's warning
holds here: **it seeds public credentials**. On every boot where the stock
sample competition is absent, the seed (re)creates the well-known accounts —
including `admin`, a **global Administrator with the password `password`** —
on an instance whose baseline may carry your SSO and SMTP secrets. The login
page would also advertise those stock accounts, and the banner's "resets
every hour" wording is fixed regardless of your actual cadence.

An internal demo therefore runs with `DEMO_MODE=false` (the default). The
trade-off is cosmetic: no demo banner or credentials card. If you want an
in-app hint, put it in an announcement or a custom page — those ride the
baseline like everything else.

## Notes / limits

- **What "reset" means for logged-in users:** unexpired access tokens keep
  validating across a reset (the JWT secret rides the baseline), but refresh
  sessions are stateful database rows that roll back with everything else —
  so anyone who logged in (or whose session rotated) after the snapshot is
  signed out within ~15 minutes of a reset. Don't promise uninterrupted
  sessions on an hourly cadence.
- **Keep the compose project name stable.** Both scripts resolve it from
  `docker compose config` (the file pins `name: flagpost`), snapshot records
  it in the baseline's `MANIFEST`, and restore refuses a baseline captured
  under a different project.
- If the compose file (or your override) ever declares a data volume the
  scripts don't know, they refuse until `deploy/internal-demo/common.sh`'s
  volume list is updated — a new stateful volume must be a deliberate
  baseline decision, not a silent gap in the reset.
- Caddy's volumes (TLS certificates, config cache) are intentionally outside
  the baseline: certificates renew on their own schedule and would only go
  stale inside a snapshot.
- The reset's brief outage is the writer services' stop+start time; there is
  no zero-downtime variant.
- The activity simulator (`docker-compose.demo.yml`'s `simulator` service)
  only understands the stock demo seed and is demo-guarded — it doesn't apply
  to internal demos.
