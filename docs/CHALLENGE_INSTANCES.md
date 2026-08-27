# Deploying challenge instances

Challenge instancing gives each team (or each user, in individual mode) an
isolated, running copy of a challenge with live connection details — the
`docker` provisioner kind, TCP exposure, shared flags. It is the optional
**Challenge Instances** module (#266, ADR-0036), off by default and toggled per
competition.

This guide is the one-time infrastructure setup. Everything after it is done in
the admin UI, and the **Test connection** button on
*Admin → Site settings → Instances* is the source of truth that your topology
actually works — it probes reachability, the socket-proxy allowlist, network
isolation and end-to-end public reachability, and reports each as a labelled
pass/fail.

> **Security note.** Instances run deliberately-vulnerable containers. The
> platform never mounts the raw Docker socket; it talks to a least-privilege
> **socket proxy** that only allows the container/image/network verbs the
> provisioner needs. The app composes every container-create payload itself
> (dropped capabilities, `no-new-privileges`, read-only rootfs, cpu/mem/pids
> limits, an isolated network, no volume mounts); authors supply an image and
> ports, never raw Docker options.

## Topologies

Same-host and remote-host are the **same code path** — the only difference is
the endpoint URL you configure. Pick one:

- **Same host** — instances run on the Docker daemon of the box running
  Flagpost. Simplest; the blast radius is that box. Use the shipped compose
  overlay below.
- **Remote host** — a sacrificial challenge host runs its own daemon and the
  identical socket proxy, reached over a private path (VPC / WireGuard /
  TLS-fronted). Recommended for large or high-risk events so exploited
  instances never share a kernel with the control plane.

## Same-host bootstrap

The one out-of-band step is bringing up the socket-proxy sidecar and the
isolated instance network. The repo ships both as an overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.instances.yml up -d
```

This adds:

- `socket-proxy` (tecnativa/docker-socket-proxy) in front of the host daemon,
  **not published to any host interface** — only the backend reaches it over an
  internal `flagpost-control` network. Allowed: `CONTAINERS`, `IMAGES`,
  `NETWORKS`, `POST`, `PING`, `VERSION`. Denied: `EXEC`, `VOLUMES`, `BUILD`,
  `SWARM`, and the rest.
- `flagpost-instances`, a bridge network created `internal: true`: instances
  can't reach Postgres/Redis/MinIO/the API or the internet, but their published
  TCP ports still route to competitors.

Then in **Admin → Site settings → Instances**:

1. Backend: **Docker**.
2. Endpoint URL: `http://socket-proxy:2375`.
3. Public host: the hostname/IP competitors connect to (e.g. `chal.example.org`).
4. TCP port range: the host ports you've opened in your firewall for instances
   (default `30000–32767`). Only this range needs to be reachable from the
   internet; the socket proxy must **not** be.
5. Leave the registry credential blank for public images; set it (base64
   `{"username","password","serveraddress"}` for `X-Registry-Auth`) for private
   ones. It is write-only and encrypted at rest.
6. Click **Test connection**. Fix any red leg before enabling — a failing leg
   names what to change.
7. Enable the module (site master switch), then toggle it on for each
   competition that needs it.

## Remote-host bootstrap

On the challenge host, run the same socket proxy beside its daemon and expose it
only on the private path to Flagpost (never the public internet). Then set the
endpoint URL to that private address (e.g. `http://10.0.0.5:2375` or a
TLS-fronted `https://…`). Create the `flagpost-instances` network on the
**challenge host's** daemon (`docker network create --internal flagpost-instances`).
Everything else — the admin fields, Test connection, authoring — is identical.

## Authoring an instanced challenge

On a challenge, open its deployment spec (staff, `challenge_edit`):

- **Backend**: `docker` (or `shared-static` for an always-on shared endpoint
  with no lifecycle).
- **Image reference**: e.g. `ghcr.io/you/chal-web:latest`.
- **Exposure / ports**: `tcp` with the container port(s) the image listens on.
- **Env**: non-secret environment for the container.
- **Resource limits / lifetime / per-subject cap**: override the site defaults
  as needed.

Staff can test-launch before publishing and while the competition is
`not_started`; competitors launch, extend and stop from the challenge modal once
the competition is `running`. Launch is force-disabled in demo mode.

## Guardrails and reaping

- **Caps**: per-subject (deployment), per-competition (`instance_max_alive`),
  and a global concurrency ceiling (site settings). Port-range exhaustion is a
  clean, evented refusal.
- **Reaping** rides the existing scheduler tick — no new process: TTL expiry,
  stuck-provision cleanup, and orphan GC (containers with no live row, reaped
  under a two-tick safety rule).
- **Egress** defaults to deny (the internal network). A challenge that genuinely
  needs the internet uses the per-competition egress opt-in; the network
  isolation validate leg is skipped for those.

## Troubleshooting

- **`privilege_posture` fails** — the endpoint isn't a restricted proxy (a
  dangerous verb returned something other than 403). Do not point Flagpost at a
  raw `/var/run/docker.sock`.
- **`network_isolation` fails** — `flagpost-instances` is missing or wasn't
  created `internal: true`. Recreate it.
- **`public_reachable` fails** — the firewall is closed on the port range, or
  the public host is wrong. This is the leg that catches the failure competitors
  would otherwise hit as a dead connection string on event day.
