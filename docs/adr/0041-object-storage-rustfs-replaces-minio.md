# ADR-0041: Object storage server — RustFS replaces MinIO, vendor-neutral `S3_*` configuration

**Status:** Accepted
**Date:** 2026-10-11
**Architecture reference:** `ARCHITECTURE.md` §2 (the fixed stack table — amended by this ADR), §13.3 (file storage & access control). Relates to ADR-0031 (IAM-role auth for AWS deployments); the storage abstraction is `backend/storage/`.

## Context

Flagpost's object storage — challenge attachments, ticket attachments, logos,
certificates, reports, backups — has been **MinIO** since Tier 0. `ARCHITECTURE.md`
§2 fixed it as the S3-compatible server, and every compose stack
(`docker-compose.yml` for production, `docker-compose.dev.yml`,
`docker-compose.demo.yml`) pulled `minio/minio:latest`.

**This change is necessary, not elective.** In 2026 MinIO withdrew its open-source
edition from general availability: the upstream repository was archived
(read-only — no further releases or security patches), community images stopped
being published, and on ~2026-09-11 the `minio/minio` and `minio/mc` repositories
were **removed from Docker Hub entirely** (the repository itself now answers 404;
the `quay.io` copy is not anonymously pullable either). The last community release
ships with unpatched security issues. Running Flagpost instances survived only on
images cached before the removal: **any fresh `docker compose up` fails**, and the
public demo's hourly reset silently stopped for a month because its
`docker compose pull` could no longer succeed.

That strikes directly at a core product promise. `VISION.md` and the README sell
Flagpost on a **simple, self-contained deployment**: one `docker compose up --build`
brings up the whole stack with no external accounts, registries, or
infrastructure. A base image that no longer exists breaks that promise for every
new operator. To **continue offering the simple deployment structure, the object
storage server has to be replaced** with one that is maintained and reliably
distributed.

What Flagpost actually needs from the server is small and generic.
`backend/storage/` uses only plain S3: `bucket_exists`/`make_bucket`,
`put_object`/`get_object`/`remove_object`, and `presigned_get_object` — signed
**offline** against a pinned region through a second client bound to a separate,
browser-reachable public endpoint (#255). Credentials are static keys or AWS IAM
(`IamAwsProvider`, ADR-0031). No MinIO admin API, bucket policies, versioning,
lifecycle, or SSE. The `ObjectStorage` interface (`storage/base.py`, with an
in-memory test backend) already isolates the server. The only MinIO-specific
couplings were the `mc ready local` container healthcheck, the `MINIO_*`
configuration naming, and the dev web-console port.

The naming is its own lesson: configuration that bakes the vendor's name in
(`MINIO_ROOT_USER`, `minio_endpoint`, `storage/minio_storage.py`) turned a server
swap into a forty-file rename. A storage backend is an interchangeable
S3-compatible server and should be named as one.

## Decision

1. **RustFS is the bundled default object storage server.** Pin
   `rustfs/rustfs:1.0.1` (Apache-2.0; GA line; amd64 + arm64) on Docker Hub, with
   `ghcr.io/rustfs/rustfs:1.0.1` documented as the mirror. Two independent
   registries at one pinned tag is the direct lesson of the MinIO removal — a
   single registry is a single point of failure for the deployment chain. A
   pinned version (not `:latest`) keeps a fresh install and the demo reset
   reproducible.

2. **The application layer does not change.** The server is generic S3, so the
   `minio` PyPI package — a generic S3 *client*, unrelated to the retired server —
   and the two-client (internal + presign) design remain, confined inside the
   storage module. The acceptance gate for this decision was a presigned-GET
   round trip against RustFS in the exact production shape (internal endpoint ≠
   public endpoint, pinned `us-east-1`, path-style, static keys): put → sign on
   the public host → fetch → bytes match; `response-content-disposition`
   honoured; expiry enforced (403); a well-formed wrong signature refused with
   403 `SignatureDoesNotMatch` and a malformed one with 400 — AWS-faithful.

3. **Vendor-neutral configuration, as a hard break.** Settings and environment
   variables are renamed `minio_*`/`MINIO_*` → `s3_*`/`S3_*`:
   `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`,
   `S3_BUCKET`, `S3_REGION`, `S3_SECURE`, `S3_IAM_AUTH`. The compose stacks take
   one credential pair, `S3_ACCESS_KEY`/`S3_SECRET_KEY`, and pass it to both the
   server (`RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY`) and the backend — replacing
   the old split between `MINIO_ROOT_*` and `MINIO_ACCESS_KEY`/`SECRET_KEY`. The
   storage module becomes `storage/s3_storage.py` (`S3Storage`); the compose
   service is `rustfs` and its volume `rustfs-data`. **No `MINIO_*` compatibility
   shim is kept**: adoption is low enough that a one-time, clearly documented
   rename beats carrying a deprecated alias layer. The release notes carry the
   upgrade mapping.

4. **Security guard extended.** `config._assert_object_storage_credentials`
   refuses well-known default credentials on a reachable deployment. The
   insecure-defaults set now covers RustFS's documented default (`rustfsadmin`)
   alongside MinIO's (`minioadmin`), so the guard protects an exposed server
   whichever default an operator inherited.

5. **Healthcheck.** `mc ready local` is replaced by RustFS's official endpoint,
   `curl -f http://localhost:9000/health` (the image ships `curl`). The backend's
   `depends_on: condition: service_healthy` gate is unchanged.

## Consequences

- **Positive:** fresh deployments work again on a maintained, Apache-2.0,
  dual-registry image; the deployment promise is restored; the application code
  is untouched; configuration no longer names a vendor, so the *next* server
  swap is a compose change; the dev stack keeps a web console (RustFS serves one
  on `:9001`, as MinIO did).
- **Negative / cost:** RustFS 1.0 reached GA on 2026-09-16 — it is young,
  mitigated by the version pin and the presigned acceptance gate above; the
  `MINIO_*` → `S3_*` rename is a **hard break** for existing deployments. Because
  `Settings` ignores unknown environment variables, a stale `.env` would
  otherwise be dropped *silently* — keys falling back to vendor defaults and, in
  the `SITE_ADDRESS`-only shape, the public endpoint falling back to loopback so
  the default-credential guard sees nothing wrong — so the backend **refuses to
  start while any `MINIO_*` variable is present** and prints the rename mapping;
  the break fails safe in every deployment shape rather than only the
  `PUBLIC_ORIGIN` one. Upgrading also needs `docker compose down
  --remove-orphans`: the retired `minio` service's container is not removed by a
  plain `up -d` and would keep port 9000, so `rustfs` could not bind. Existing
  object data does **not** migrate across the server swap — objects live in the
  old `minio-data` volume, so an install holding attachments copies them across
  (`rclone sync`, S3→S3, while the old server is still reachable) or re-uploads.
- **Forecloses:** little — the storage interface and the vendor-neutral names
  mean a later move to another S3 server, or to a managed bucket via IAM
  (ADR-0031), is a compose/config change.

## Alternatives considered

- **Keep MinIO via a mirror or community rebuild** (`quay.io/minio`,
  `derklaro/minio`, `pgsty/minio`, `bitnamilegacy/minio`). Rejected: upstream is
  archived with unpatched vulnerabilities and no future; a mirror buys time, not
  a supportable default.
- **VersityGW** (Apache-2.0, vendor-backed, dual-registry, POSIX backend). A very
  close second and the more conservative choice; passed over because RustFS is a
  purpose-built MinIO drop-in (same port/console/env shape → smallest migration,
  keeps dev UX). It remains the fallback if RustFS proves immature; the `S3_*`
  naming makes that swap a compose change.
- **SeaweedFS.** Mature and dual-registry, but a documented history of
  presigned-URL/SigV4 regressions — the one feature this platform cannot
  tolerate instability in — and more moving parts than a bundled default needs.
- **Garage.** Well regarded, but AGPL-3.0 (a license shift for a bundled
  default), published to a single registry, and its own quickstart marks
  single-node mode as not for production.
- **A `MINIO_*` compatibility shim.** Considered for upgrade safety; rejected by
  the owner given current adoption — a hard break with clear release notes is
  cheaper than a deprecation cycle.
