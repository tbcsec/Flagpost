# Contributing to Flagpost

Thanks for your interest in improving Flagpost! This guide covers how to get set
up, the conventions the codebase follows, and how to get a change merged.

## Ground rules

- **Read the docs first.** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) is
  binding — it's how the system is designed, not aspirational. The
  [`docs/adr/`](docs/adr/) records explain *why* past decisions were made; check
  them before proposing an alternative to something already settled.
- **Security issues are different.** Do **not** open a public issue or PR for a
  vulnerability — follow [`SECURITY.md`](SECURITY.md).
- Be respectful; this project follows the
  [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs & requesting features

- **Found a bug?** Open a
  [bug report](https://github.com/tbcsec/flagpost/issues/new?template=bug_report.yml) —
  the form asks for the version, repro steps, and how you're running it. Search
  [existing issues](https://github.com/tbcsec/flagpost/issues) first.
- **Want a feature?** A small, well-defined idea → open a
  [feature request](https://github.com/tbcsec/flagpost/issues/new?template=feature_request.yml).
  A large or open-ended idea → start a
  [Discussion](https://github.com/tbcsec/flagpost/discussions) so the scope can be
  shaped before it becomes a tracked issue.
- **Question or need help?** Use
  [Discussions](https://github.com/tbcsec/flagpost/discussions), not an issue.
- **Security vulnerability?** Never a public issue — follow
  [`SECURITY.md`](SECURITY.md).

New issues start labelled `needs-triage`; a maintainer confirms, labels, and — if
it's slated for a release — adds it to a milestone and the public roadmap.

## Getting set up

The fastest way to a running stack is Docker (see the README). For iterating on
the code you'll usually run each side directly:

```bash
# Backend — the host Python is often externally-managed, so use a venv
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head          # against a reachable Postgres
.venv/bin/uvicorn main:app --reload

# Frontend — requires Node 20+
cd frontend && npm install && npm run dev
```

The backend test suite is SQLite-backed and needs no infrastructure.

## Before you open a pull request

Run the same checks CI does — all four must pass:

```bash
cd backend  && .venv/bin/pytest                 # backend tests
cd frontend && npm run test                     # frontend unit tests (vitest)
cd frontend && npx tsc --noEmit                 # type-check
cd frontend && npx eslint .                     # lint
```

If your change is observable in the UI, run it in the browser and confirm it
works — don't rely on tests alone for user-facing behaviour.

## Conventions the codebase enforces

These aren't style preferences; they're architectural rules (ARCHITECTURE.md §1,
some enforced by ESLint):

- **Every mutation emits an event** through the event bus, using the
  `<entity>.<verb>` past-tense vocabulary in §3.2. Add a new event type there
  before using it.
- **Every tenant-scoped query and route is scoped by `competition_id`** at the
  data-access layer (§6.2).
- **Permission checks go through `require_permission`**, never an inline role
  check (§7.6). New capability? Add it to the catalog in §7.1 first.
- **One hook module per frontend domain** under `frontend/src/lib/hooks/`;
  components never call the API client directly.
- **Colours and spacing come from design tokens**, never a raw hex or magic
  number in a component (§9).
- Backend: Pydantic schemas are separate from SQLAlchemy models; one router per
  domain. One migration per PR, named `YYYY-MM-DD_<revid>_<desc>.py`.

## Pull request flow

1. Fork and branch from `main`.
2. Keep the change focused; unrelated cleanups belong in their own PR.
3. Make sure the four checks above pass locally.
4. Open the PR with a clear description of *what* and *why*. Reference any issue
   it closes.
5. A maintainer will review. Expect questions — the goal is a codebase that
   stays coherent, not just code that works.

## Cutting a release (maintainers)

Releases are tags. Pushing a `v*` tag builds and publishes the versioned GHCR
images, so the tag *is* the release artefact — there's nothing to build by hand.

1. **Bump the source-build version.** In [`backend/config.py`](backend/config.py),
   set `app_version` to the version you're about to tag, keeping the `-src`
   suffix — e.g. `"1.3.0-src"` for `v1.3.0`. Commit it.
2. Tag and push: `git tag v1.3.0 && git push origin v1.3.0`.
3. Write the GitHub Release notes.

Step 1 is easy to forget and matters more than it looks. Release *images* get
their version baked from the tag automatically, but the README's headline
quickstart is `git clone` + `docker compose up`, so most deployments run from
source and report this default instead. Miss the bump and every one of them
reports the previous release — silently, for as long as it takes someone to
notice the numbers look wrong.

You won't get that far: a check in `release-images.yml` compares the default
against the tag and fails the release if they disagree, before any image is
published. If it fires, fix the default, delete the tag, and re-tag.

The `-src` marker is deliberate. A clone of `main` isn't the release — `main`
starts accumulating the next version's work the moment you tag — so the value
means "a source tree based on that release". It also keeps source builds
distinguishable from release images in the adoption data (#111), which is worth
knowing when deciding where to spend effort on packaging.

## Licensing of contributions

Flagpost is licensed under the **GNU AGPL-3.0** (see [`LICENSE`](LICENSE)). By
submitting a contribution, you agree that it is licensed under the same terms.
