# Deploying the Flagpost demo (demo.flagpost.io)

The demo runs prebuilt GHCR images behind a **Cloudflare Tunnel** (no host ports
exposed), in **demo mode**, and resets **every hour, on the hour**.

```
browser ──HTTPS──▶ Cloudflare ──tunnel──▶ cloudflared ─▶ caddy:80 ─▶ frontend / backend
```

## 1. Publish the images to GHCR

The [`Build demo images`](../.github/workflows/demo-images.yml) workflow builds
and pushes `ghcr.io/tbcsec/flagpost-backend:demo` and `…/flagpost-frontend:demo`.

- It runs automatically on pushes to `main` under `backend/**` or `frontend/**`,
  or manually: **Actions → Build demo images → Run workflow**.
- The frontend image bakes `NEXT_PUBLIC_API_URL=https://demo.flagpost.io` (the
  browser-facing origin). Override it via the "Run workflow" input if the origin
  changes.
- If the first run fails with `denied: installation not allowed`, enable
  **Settings → Actions → General → Workflow permissions → Read and write**.

### Make the packages public (one time, per package)

New GHCR packages are private. For **each** of `flagpost-backend` and
`flagpost-frontend` (find them at `github.com/tbcsec?tab=packages`):

1. Package → **Package settings** → **Danger Zone** → **Change visibility** → **Public**.
2. On the same page, under **Manage Actions access**, confirm the `flagpost`
   repo is listed with **Write** (so future runs can push updates).

Verify anonymous pull works:

```bash
docker logout ghcr.io
docker pull ghcr.io/tbcsec/flagpost-backend:demo
```

## 2. Set up the Cloudflare Tunnel

In **Cloudflare Zero Trust → Networks → Tunnels**:

1. Create a tunnel; copy its **token**.
2. Add a **public hostname**: `demo.flagpost.io` → service `HTTP` → `caddy:80`.
   (`cloudflared` runs in the same Docker network as Caddy, so `caddy` resolves.)

Cloudflare terminates TLS, so make sure **WebSockets** are enabled (default) for
the zone — the live scoreboard/notifications ride `wss://demo.flagpost.io/ws`.

## 3. Run it on the box (Hetzner)

Put the repo (or at least `docker-compose.demo.yml` + `Caddyfile`) at
`/opt/flagpost`, then:

```bash
cd /opt/flagpost
export TUNNEL_TOKEN=<your-cloudflare-tunnel-token>   # e.g. in /opt/flagpost/.env
docker compose -f docker-compose.demo.yml pull
docker compose -f docker-compose.demo.yml up -d
```

No `docker login` on the box — that's what making the packages public bought you.
No ports are published; all inbound traffic arrives via the tunnel.

## 4. Automate the hourly reset

Install the provided timer (edit `FLAGPOST_DIR` in the unit if you deployed
elsewhere):

```bash
chmod +x /opt/flagpost/deploy/demo-reset.sh
sudo cp /opt/flagpost/deploy/flagpost-demo-reset.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flagpost-demo-reset.timer
systemctl list-timers flagpost-demo-reset.timer   # confirm next run is on the hour
```

Each firing runs `pull → down -v → up -d`: it pulls the latest images **and**
wipes the DB/object/secret volumes, so demo mode re-seeds a clean instance.

## Notes / limits

- **Attachments don't download** on the demo — MinIO isn't exposed (no ports),
  and the seed adds no attachments, so nothing user-facing depends on it. If you
  want them, add an MinIO ingress to the tunnel and set `MINIO_PUBLIC_ENDPOINT`.
- Demo mode disables outbound automation actions (webhooks, email) and seeds the
  public accounts `admin` / `judge` / `participant` (password `password`).
- **Never** point a real deployment at this file — `DEMO_MODE=true` seeds
  well-known credentials.
