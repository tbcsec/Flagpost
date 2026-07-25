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

In **Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel** (pick the
**Cloudflared / token** connector). The current wizard makes you run the
connector *before* it will let you add a route, so the order is:

1. Name the tunnel and **copy its token** (shown on the "install a connector"
   step). Ignore the install commands it prints — `cloudflared` runs as a
   container from `docker-compose.demo.yml`, not on the host.
2. Put the token on the box and bring the stack up (§3) so the `cloudflared`
   container connects. The wizard won't advance until it sees a live connector.
3. Once the dashboard shows the connector **connected**, add the route (the
   **"Add published application" / Public Hostname** step):
   - **Subdomain** `demo`, **Domain** `flagpost.io` → `demo.flagpost.io`
   - **Path** — leave empty (match all paths; Caddy does the `/api`+`/ws`
     routing internally)
   - **Service URL** — `http://caddy:80`. Note **`http://`** (Cloudflare
     terminates TLS, so Caddy serves plain HTTP) and the service name **`caddy`**
     (`cloudflared` shares the compose network, so `caddy` resolves).

WebSockets pass through automatically, so the live scoreboard/notifications ride
`wss://demo.flagpost.io/ws` with no extra toggle.

## 3. Run it on the box (Hetzner)

Get the deploy files onto the box at `/opt/flagpost` (the systemd units and the
`./Caddyfile` mount assume that exact path). Only `docker-compose.demo.yml`,
`Caddyfile`, and `deploy/` are actually needed — the app is pulled as images, so
you don't need to build anything:

```bash
sudo mkdir -p /opt/flagpost && sudo chown "$USER" /opt/flagpost
git clone https://github.com/tbcsec/flagpost.git /opt/flagpost
cd /opt/flagpost
```

Then set the tunnel token and bring the stack up:

```bash
echo "TUNNEL_TOKEN=<your-cloudflare-tunnel-token>" >> .env   # never commit this
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
