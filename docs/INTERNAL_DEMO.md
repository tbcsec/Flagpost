# Running an internal demo (custom baseline + scheduled reset)

The public demo (demo.flagpost.io) resets every hour by wiping every volume and
letting `DEMO_MODE` re-seed a hardcoded sample competition and well-known
accounts — its baseline is *code* (`backend/auth/demo.py`), and it isn't meant
to be customised.

An **internal demo** flips that around: you configure a normal Flagpost
instance exactly the way you want it — your branding and theme, your
competitions and challenges, your users and teams — capture that state as a
**baseline snapshot**, and a timer restores the snapshot on a schedule. The
reset is a byte-level volume restore, so *everything* survives: SSO providers,
SMTP settings, uploaded attachments, even active sessions (the JWT secret is
part of the baseline, so logged-in browsers stay logged in across resets —
unlike the public demo).

Nothing here touches the public demo stack; this rides the production
`docker-compose.yml`.

## 1. Deploy the production stack

Follow the README's "Deploying to production" section — the standard
`docker compose up -d` stack with a real `.env`. Everything below assumes the
repo lives at `/opt/flagpost`; export `FLAGPOST_DIR` if it doesn't.

## 2. Configure the baseline in the UI

Complete the first-run setup wizard, then set the instance up as the demo you
want people to see: branding + theme, competitions, challenges, users, teams,
module toggles, pages — anything. Whatever the instance looks like when you
snapshot is exactly what every reset returns to.

## 3. Capture it

```bash
chmod +x /opt/flagpost/deploy/internal-demo/{snapshot,restore}.sh
sudo /opt/flagpost/deploy/internal-demo/snapshot.sh
```

The script stops the stack (so Postgres is captured in a clean shutdown
state), tars the three data volumes (`postgres-data`, `minio-data`,
`backend-data`) into `deploy/internal-demo/baseline/`, writes a `MANIFEST`
(timestamp + image list), and starts the stack again. Expect a brief outage
(~the stack's normal start time).

Re-run it any time the baseline should change; the previous baseline is kept
once, at `baseline.prev/`. Budget disk for roughly twice your instance's data
size.

## 4. Schedule the reset

```bash
sudo cp /opt/flagpost/deploy/internal-demo/flagpost-internal-demo-reset.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flagpost-internal-demo-reset.timer
systemctl list-timers flagpost-internal-demo-reset.timer   # confirm the next run
```

Hourly on the hour by default; the cadence is one `OnCalendar` line in the
timer. Run `sudo systemctl start flagpost-internal-demo-reset.service` to test
a reset immediately, and check `journalctl -u flagpost-internal-demo-reset`
when something looks off — `restore.sh` waits for the app's health endpoint
and fails the unit visibly if the stack doesn't come back.

`restore.sh` refuses to run (and touches nothing) unless all three baseline
tarballs exist, and deliberately never pulls the repo or images — an internal
demo pins a stable baseline. To upgrade: pull new images, `up -d` (migrations
run on boot), verify, then **re-run `snapshot.sh`**. A stale baseline still
works — migrations simply re-run after every restore — but re-snapshotting
keeps resets fast and boring.

## Demo mode: on or off?

Both work; it changes the dressing, not the reset.

| | `DEMO_MODE=false` (default) | `DEMO_MODE=true` |
|---|---|---|
| Demo banner | none | shown ("resets every hour, on the hour" — the wording is fixed, so only accurate at the default cadence) |
| Login credentials card | none | shown, but it advertises the **stock** `admin`/`judge`/`participant` accounts — wrong for a custom baseline |
| Outbound automation actions (webhooks/email) | enabled | disabled |
| Sample competition seed | none | the idempotent seed **re-adds the stock sample competition on every boot** unless your baseline already contains it |
| Update check | see below | suppressed |

For a company-internal demo the usual choice is `DEMO_MODE=false` with the
update check disabled (next section). If you want the banner, take the stock
sample competition into your baseline (configure with `DEMO_MODE=true` from
the start) and live with the credentials card naming accounts that may not
match yours.

## Keep the update check honest

Flagpost normally phones home once a day with its version number, and the
"when did I last check" bookkeeping lives in the database — which the reset
keeps restoring to a moment ever further in the past. Once the baseline is a
day old, **every reset boot considers a check due**, inflating the anonymous
adoption count (~24×/day at hourly cadence). `DEMO_MODE=true` already
suppresses the check; with demo mode off, disable it the air-gap way — a
`docker-compose.override.yml` next to `docker-compose.yml` (compose merges it
automatically):

```yaml
services:
  backend:
    environment:
      UPDATE_CHECK_URL: ""
```

## Notes / limits

- **Keep the compose project name stable.** Both scripts resolve it from
  `docker compose config` (the file pins `name: flagpost`), so snapshot and
  restore always agree — just don't set a different `COMPOSE_PROJECT_NAME`
  between the two.
- Caddy's volumes (TLS certificates, config cache) are intentionally outside
  the baseline: certificates renew on their own schedule and would only go
  stale inside a snapshot.
- The restore's brief outage is the stack's stop+start time; there is no
  zero-downtime variant.
- The activity simulator (`docker-compose.demo.yml`'s `simulator` service)
  only understands the stock demo seed and is demo-guarded — it doesn't apply
  to internal demos.
