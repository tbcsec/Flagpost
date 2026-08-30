# Deploying challenge instances

Challenge instancing gives each team (or each user, in individual mode) an
isolated, running copy of a challenge with live connection details — the
`docker` provisioner kind, TCP exposure, and either a shared flag or a
[unique per-instance flag](#unique-per-instance-flags). It is the optional
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
- `flagpost-instances`, a **normal bridge** network. It is deliberately *not*
  `internal: true`: Docker can't publish a TCP port from a container that's only
  on an internal network, so an internal network would break TCP challenges.
  Egress-deny is therefore a **host-firewall** job (see below), not the Docker
  internal flag.

> **Egress control (do this for a real event).** A normal bridge lets instances
> reach the internet and the host by default. Block outbound from the
> `flagpost-instances` subnet with host firewall rules — drop forwarded traffic
> from that subnet except to the ports competitors need, and always block the
> cloud metadata IP `169.254.169.254`. Keep the control plane
> (Postgres/Redis/MinIO/API) off any address the instance subnet can reach. The
> `network_isolation` leg of Test connection reminds you of this; it can't verify
> your firewall rules for you.

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
**challenge host's** daemon (`docker network create flagpost-instances`, a normal
bridge — then apply the egress firewall rules described above on that host).
Everything else — the admin fields, Test connection, authoring — is identical.

## HTTP subdomain routing (#319, ADR-0036 §4)

Web challenges are exposed over HTTPS at a **per-instance subdomain** rather than
a raw TCP port: an instance is reached at `https://<token>.<chal_base_domain>`,
where `<token>` is a short unguessable id minted per instance. A **label-driven
ingress** on the instance host does the routing — the provisioner sets
`caddy` / `caddy.reverse_proxy` labels at container-create and a
[caddy-docker-proxy](https://github.com/lucaslorentz/caddy-docker-proxy)
sidecar reconfigures itself from them. There is no control-plane round-trip per
request, the behaviour is identical same-host and remote, and the platform's own
Caddy is untouched.

**Two prerequisites — you provide these, once, per host:**

1. **Wildcard DNS.** `*.<chal_base_domain>` must resolve to the instance host.
2. **Wildcard TLS cert.** A cert for `*.<chal_base_domain>` on the ingress.

**Bootstrap.** Bring the ingress up alongside the socket proxy:

```
docker compose -f docker-compose.yml -f docker-compose.instances.yml \
  -f docker-compose.instances-http.yml up -d
```

Then in **Admin → Site settings → Instances** set **HTTP base domain** to your
`chal.<domain>` and save. `Test connection` gains an **HTTP** leg that checks the
wildcard resolves and the ingress answers on `:443`; an `exposure: http`
challenge can't launch until the base domain is set.

**Local dev / CI-of-the-mind.** No domain or real cert needed:

- **DNS** — [sslip.io](https://sslip.io): set the base domain to
  `chal.127.0.0.1.sslip.io` and `<anything>.chal.127.0.0.1.sslip.io` resolves to
  `127.0.0.1` with no DNS server to run.
- **TLS** — Caddy's **internal CA** (`local_certs` in
  `caddy/instances-ingress.Caddyfile`), so instance certs are issued locally.
- `scripts/e2e-instances-http.sh` stands the ingress up, launches a `whoami`
  container with the exact labels the provisioner emits, and asserts the
  subdomain serves 200 over TLS — the end-to-end proof of the routing path.

**Production.** Delete `local_certs` from `caddy/instances-ingress.Caddyfile` and
issue real certs via **ACME DNS-01** — the global option `acme_dns <provider> …`
(e.g. `acme_dns cloudflare {env.CF_API_TOKEN}`). Each instance subdomain is then
issued a cert through a DNS challenge, with no inbound ACME HTTP challenge exposed
on the ingress. (Note: `tls { dns … }` is a *site-level* directive — it is not
valid in the global-options block, which is all the base Caddyfile is.)

## Authoring an instanced challenge

On a challenge, open its deployment spec (staff, `challenge_edit`):

- **Backend**: `docker` (or `shared-static` for an always-on shared endpoint
  with no lifecycle).
- **Image reference**: e.g. `ghcr.io/you/chal-web:latest`.
- **Exposure / ports**: `tcp` with the container port(s) the image listens on,
  `http` for a web challenge reached over a per-instance subdomain (the first
  port is the ingress upstream; defaults to 80 — see *HTTP subdomain routing*),
  or `none` for a self-contained challenge with no published endpoint.
- **Env**: non-secret environment for the container.
- **Resource limits / lifetime / per-subject cap**: override the site defaults
  as needed.
- **Flag mode**: `static` (the challenge's own flag applies — everyone submits
  the same flag) or `unique_per_instance` (see below).

Staff can test-launch before publishing and while the competition is
`not_started`; competitors launch, extend and stop from the challenge modal once
the competition is `running`. Launch is force-disabled in demo mode.

## Unique per-instance flags

Set **flag mode** to `unique_per_instance` and give a **flag template** — a flag
string containing the placeholder `<random>`, e.g. `flag{pwned-<random>}`. At
provision time the provisioner substitutes a fresh random token for `<random>`,
injects the rendered flag into the container **once** (env var `FLAG`), and
stores only its salted hash on the instance row (ADR-0036 §3) — the same
never-plaintext posture as a static flag, so staff can't read a live instance's
flag and the remedy for a lost one is re-provisioning.

- The challenge itself needs **no static flag**: grading compares a submission
  against the submitting subject's own live instance flag(s). Publishing such a
  challenge is allowed even though it has no static flag.
- **Flag sharing is provable and detected.** A wrong submission that matches
  *another* subject's live instance flag emits `challenge.flag_shared_detected`
  (staff + automation, gated on `view_submissions`). There is **no automatic
  penalty** — policy stays human; it is a signal, not an enforcement action.
- First blood and dynamic decay are unchanged — they key on which subject
  solved and how many solves exist, not on flag identity.
- `unique_per_instance` requires a per-instance backend (`docker`); it is
  rejected for `shared-static`, whose one shared endpoint can't hold a
  per-subject flag.

## Guardrails and reaping

- **Caps**: per-subject (deployment), per-competition (`instance_max_alive`),
  and a global concurrency ceiling (site settings). Port-range exhaustion is a
  clean, evented refusal.
- **Reaping** rides the existing scheduler tick — no new process: TTL expiry,
  stuck-provision cleanup, and orphan GC (containers with no live row, reaped
  under a two-tick safety rule).
- **Egress** is a host-firewall responsibility (see the network note above), not
  a Docker internal-network setting — an internal network can't publish TCP
  ports. The per-competition `egress_policy` records your intent (`deny` is the
  default and makes the `network_isolation` leg remind you to add firewall rules;
  `allow` drops the reminder for challenges that legitimately need the internet).

## Troubleshooting

- **`privilege_posture` fails** — the endpoint isn't a restricted proxy (a
  dangerous verb returned something other than 403). Do not point Flagpost at a
  raw `/var/run/docker.sock`.
- **`network_isolation` fails** — `flagpost-instances` doesn't exist. Create it
  (`docker network create flagpost-instances`, a normal bridge). The leg passes
  once it exists; under `egress_policy: deny` it also *advises* firewall rules
  (it can't verify them) — that's a note, not a failure.
- **`public_reachable` fails** — the firewall is closed on the port range, or
  the public host is wrong. This is the leg that catches the failure competitors
  would otherwise hit as a dead connection string on event day.
