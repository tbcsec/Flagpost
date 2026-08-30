"""Bulk challenge import/export in the ctfcli ``challenge.yml`` format (Phase 9).

A CTFd-compatible authoring interchange: a **zip** with one
``<slug>/challenge.yml`` per challenge (plus its attachment files under the same
folder), the layout ``ctfcli`` uses. Lets an organiser author challenges offline
in YAML and import a whole set, or export a competition's challenges to edit/back
up as text.

**Flag caveat:** static flags are stored salted-hashed and can't be recovered, so
export omits them (regex patterns *are* stored plaintext and round-trip). Import
hashes the plaintext flags the YAML supplies, so authoring→import is lossless.

Field mapping (ctfcli ⇄ Flagpost):
- ``name`` ⇄ ``title``; ``category`` ⇄ category name (created on import);
  ``description`` ⇄ plain text of the TipTap doc; ``value`` ⇄ ``points``;
  ``type: dynamic`` + ``extra.{initial,decay,minimum}`` ⇄ dynamic scoring;
  ``flags`` (static string / ``{type: regex, content}``) ⇄ the flag config;
  ``tags`` ⇄ ``tags`` (unioned into the competition vocab on import);
  ``extra.difficulty`` ⇄ ``difficulty``; ``hints`` ⇄ hints; ``files`` ⇄
  attachments; ``state`` (visible/hidden) ⇄ published/draft;
  ``prerequisites`` (challenge *titles*) ⇄ the prerequisite ids;
  ``connection_info`` ⇄ ``connection_info`` (top-level in the ctfcli spec, so
  it round-trips with real ctfcli/CTFd bundles — *not* under ``extra``).
"""

from __future__ import annotations

import io
import re
import zipfile
from uuid import uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.attachment import Attachment
from models.challenge import Category, Challenge
from models.challenge_instancing import ChallengeDeployment
from models.competition import Competition
from models.hint import Hint
from storage.base import ObjectStorage
from utils.flags import hash_static_flag, make_salt
from utils.richtext import doc_to_text


# --- TipTap ⇄ plain text -----------------------------------------------------

# The doc→text direction now lives in utils.richtext (shared with the competitor
# assistant tools); re-exported here under the module-private name its callers use.
_doc_to_text = doc_to_text


def _text_to_doc(text: str) -> dict:
    """Wrap plain text in a minimal TipTap doc (one paragraph per line)."""
    paras = [
        {
            "type": "paragraph",
            "content": ([{"type": "text", "text": line}] if line else []),
        }
        for line in (text or "").split("\n")
    ]
    return {"type": "doc", "content": paras or [{"type": "paragraph"}]}


def _slug(title: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "challenge"
    slug = base
    i = 2
    while slug in taken:
        slug = f"{base}-{i}"
        i += 1
    taken.add(slug)
    return slug


# --- export ------------------------------------------------------------------


async def export_challenges(
    db: AsyncSession, competition: Competition, storage: ObjectStorage
) -> bytes:
    """Zip the competition's challenges as ctfcli ``challenge.yml`` folders."""
    challenges = (
        await db.scalars(
            select(Challenge)
            .where(Challenge.competition_id == competition.id)
            .order_by(Challenge.created_at)
        )
    ).all()
    categories = {
        c.id: c.name
        for c in (
            await db.scalars(
                select(Category).where(Category.competition_id == competition.id)
            )
        ).all()
    }
    title_by_id = {c.id: c.title for c in challenges}
    deployments = {
        d.challenge_id: d
        for d in (
            await db.scalars(
                select(ChallengeDeployment).where(
                    ChallengeDeployment.competition_id == competition.id
                )
            )
        ).all()
    }

    buf = io.BytesIO()
    taken: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ch in challenges:
            slug = _slug(ch.title, taken)
            data: dict = {
                "name": ch.title,
                "category": categories.get(ch.category_id, "") or "",
                "description": _doc_to_text(ch.description),
                "value": ch.points,
                "state": "visible" if ch.state == "published" else "hidden",
            }
            # Top-level key, exactly as ctfcli/CTFd spell it — deliberately not
            # inside `extra` (the dynamic-scoring bag plus our `difficulty`
            # escape hatch), so real ctfcli bundles round-trip.
            if ch.connection_info:
                data["connection_info"] = ch.connection_info
            if ch.scoring_type == "dynamic":
                data["type"] = "dynamic"
                data["extra"] = {
                    "initial": ch.points,
                    "decay": ch.decay,
                    "minimum": ch.min_points,
                }
            else:
                data["type"] = "standard"
            # Flags: regex round-trips; static is hashed (omitted, noted).
            if ch.flag_type == "regex" and ch.flag_regex:
                data["flags"] = [{"type": "regex", "content": ch.flag_regex}]
            if ch.difficulty:
                data.setdefault("extra", {})["difficulty"] = ch.difficulty
            if ch.tags:
                data["tags"] = list(ch.tags)
            if ch.prerequisites:
                data["prerequisites"] = [
                    title_by_id[p] for p in ch.prerequisites if p in title_by_id
                ]
            # Deployment spec (instancing) under extra.deployment.
            dep = deployments.get(ch.id)
            if dep is not None:
                data.setdefault("extra", {})["deployment"] = _deployment_to_yaml(dep)
            # Hints.
            hints = (
                await db.scalars(
                    select(Hint).where(Hint.challenge_id == ch.id).order_by(Hint.id)
                )
            ).all()
            if hints:
                data["hints"] = [{"content": h.body, "cost": h.cost} for h in hints]
            # Attachment files (bundled under the challenge folder).
            attachments = (
                await db.scalars(
                    select(Attachment).where(Attachment.challenge_id == ch.id)
                )
            ).all()
            files: list[str] = []
            for att in attachments:
                try:
                    blob = storage.get(att.object_key)
                except Exception:
                    continue  # a missing object shouldn't sink the whole export
                zf.writestr(f"{slug}/{att.filename}", blob)
                files.append(att.filename)
            if files:
                data["files"] = files

            zf.writestr(
                f"{slug}/challenge.yml",
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            )
    return buf.getvalue()


# --- import ------------------------------------------------------------------


# --- deployment spec (instancing, #266/#320, ADR-0036) ⇄ extra.deployment ----
# A Flagpost-specific block under ``extra`` (like ``difficulty``), so real
# ctfcli/CTFd bundles that don't have it round-trip untouched and one that does
# is clearly a Flagpost extension. Carries the authoring fields only — image,
# exposure, ports, env, flag mode/template, caps, lifetime (ADR-0036 §5) — never
# a rendered flag or a credential (those aren't on the deployment).


def _deployment_to_yaml(dep: ChallengeDeployment) -> dict:
    out: dict = {
        "backend": dep.backend,
        "exposure": dep.exposure,
        "flag_mode": dep.flag_mode,
    }
    if dep.image_ref:
        out["image"] = dep.image_ref
    if dep.ports:
        out["ports"] = list(dep.ports)
    if dep.env:
        out["env"] = dict(dep.env)
    if dep.manifest:
        out["manifest"] = dep.manifest
    if dep.resource_limits:
        out["resource_limits"] = dep.resource_limits
    if dep.lifetime_s is not None:
        out["lifetime_s"] = dep.lifetime_s
    if dep.per_subject_cap != 1:
        out["per_subject_cap"] = dep.per_subject_cap
    if dep.flag_template:
        out["flag_template"] = dep.flag_template
    return out


def _deployment_from_yaml(
    spec: dict, competition_id: str, challenge_id: str
) -> tuple[ChallengeDeployment | None, str | None]:
    """Build a validated ``ChallengeDeployment`` from a YAML ``extra.deployment``
    block, or ``(None, error)``. Runs the same ``DeploymentUpdate.validate_shape``
    the authoring route uses, so an inconsistent spec from an untrusted zip is
    rejected at the boundary rather than persisted (the import bypasses the
    route)."""
    from pydantic import ValidationError

    from schemas.instances import DeploymentUpdate

    # YAML is human-authored and loose, so coerce leniently — but a malformed
    # container value must become a per-challenge error string (author feedback),
    # never an uncaught AttributeError that 500s the whole import nor a silent
    # drop that loses the author's intent. per_subject_cap uses a None-test, not
    # ``or``, so an explicit 0 is validated (and rejected by Field ge=1) rather
    # than silently rewritten to 1.
    _env = spec.get("env")
    _ports = spec.get("ports")
    if _env is not None and not isinstance(_env, dict):
        return None, "env must be a mapping"
    if _ports is not None and not isinstance(_ports, list):
        return None, "ports must be a list"
    try:
        upd = DeploymentUpdate(
            backend=str(spec.get("backend") or "docker"),
            image_ref=spec.get("image"),
            manifest=spec.get("manifest") if isinstance(spec.get("manifest"), dict) else None,
            exposure=str(spec.get("exposure") or "tcp"),
            ports=[int(p) for p in (_ports or [])],
            env={str(k): str(v) for k, v in (_env or {}).items()},
            resource_limits=spec.get("resource_limits")
            if isinstance(spec.get("resource_limits"), dict) else None,
            lifetime_s=int(spec["lifetime_s"]) if spec.get("lifetime_s") is not None else None,
            per_subject_cap=int(spec["per_subject_cap"]) if spec.get("per_subject_cap") is not None else 1,
            flag_mode=str(spec.get("flag_mode") or "static"),
            flag_template=spec.get("flag_template"),
        )
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        return None, str(exc)
    err = upd.validate_shape()
    if err:
        return None, err
    return (
        ChallengeDeployment(
            competition_id=competition_id,
            challenge_id=challenge_id,
            backend=upd.backend,
            image_ref=upd.image_ref,
            manifest=upd.manifest,
            exposure=upd.exposure,
            ports=upd.ports,
            env=upd.env,
            resource_limits=upd.resource_limits,
            lifetime_s=upd.lifetime_s,
            per_subject_cap=upd.per_subject_cap,
            flag_mode=upd.flag_mode,
            flag_template=upd.flag_template,
        ),
        None,
    )


def _parse_flags(raw: object) -> tuple[str, str | None, str | None]:
    """Return (flag_type, static_flag, regex_pattern) from a ctfcli ``flags`` list."""
    for entry in raw or []:
        if isinstance(entry, str):
            return "static", entry, None
        if isinstance(entry, dict):
            if entry.get("type") == "regex" and entry.get("content"):
                return "regex", None, entry["content"]
            if entry.get("content"):
                return "static", entry["content"], None
    return "static", None, None


async def import_challenges(
    db: AsyncSession,
    competition: Competition,
    zip_bytes: bytes,
    storage: ObjectStorage,
) -> dict:
    """Create challenges from a ctfcli zip. Additive: a challenge whose title
    already exists is skipped. Returns ``{created, skipped, errors}``."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Not a valid zip file") from exc

    existing_titles = {
        t
        for (t,) in (
            await db.execute(
                select(Challenge.title).where(
                    Challenge.competition_id == competition.id
                )
            )
        ).all()
    }
    categories = {
        c.name: c.id
        for c in (
            await db.scalars(
                select(Category).where(Category.competition_id == competition.id)
            )
        ).all()
    }
    vocab_tags = set(competition.challenge_tags or [])
    vocab_tiers = set(competition.difficulty_tiers or [])

    created = 0
    skipped = 0
    errors: list[str] = []
    # Remember prerequisite titles to resolve after all challenges exist.
    pending_prereqs: list[tuple[str, list[str]]] = []  # (challenge_id, titles)
    title_to_id: dict[str, str] = {}

    for name in sorted(zf.namelist()):
        if not name.endswith("challenge.yml"):
            continue
        folder = name.rsplit("/", 1)[0] if "/" in name else ""
        try:
            spec = yaml.safe_load(zf.read(name)) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{name}: {exc}")
            continue
        title = str(spec.get("name") or "").strip()
        if not title:
            errors.append(f"{name}: missing name")
            continue
        if title in existing_titles:
            skipped += 1
            continue

        # Category (create if new).
        category_id = None
        cat_name = str(spec.get("category") or "").strip()
        if cat_name:
            if cat_name not in categories:
                cat = Category(competition_id=competition.id, name=cat_name)
                db.add(cat)
                await db.flush()
                categories[cat_name] = cat.id
            category_id = categories[cat_name]

        extra = spec.get("extra") or {}
        is_dynamic = str(spec.get("type") or "standard") == "dynamic"
        flag_type, static_flag, regex_pattern = _parse_flags(spec.get("flags"))

        challenge = Challenge(
            competition_id=competition.id,
            title=title,
            description=_text_to_doc(str(spec.get("description") or "")),
            category_id=category_id,
            points=int(spec.get("value") or extra.get("initial") or 0),
            scoring_type="dynamic" if is_dynamic else "static",
            min_points=int(extra["minimum"]) if is_dynamic and extra.get("minimum") is not None else None,
            decay=int(extra["decay"]) if is_dynamic and extra.get("decay") is not None else None,
            flag_type=flag_type,
            state="published" if str(spec.get("state")) == "visible" else "draft",
            # Coerced + clamped here because this path never sees the Pydantic
            # schema: `connection_info: 1337` parses as an int (SQLite accepts
            # it, Postgres rejects it), and an unbounded string from an
            # untrusted zip would otherwise land straight in the column. Mirrors
            # ChallengeCreate's max_length=500.
            connection_info=str(spec.get("connection_info") or "").strip()[:500] or None,
        )
        # Flag material.
        if flag_type == "regex":
            challenge.flag_regex = regex_pattern
        elif static_flag:
            challenge.flag_salt = make_salt()
            challenge.flag_hash = hash_static_flag(static_flag, challenge.flag_salt, False)
        # Tags/difficulty — union into the competition vocab so they validate.
        tags = [str(t) for t in (spec.get("tags") or [])]
        if tags:
            challenge.tags = tags
            vocab_tags.update(tags)
        difficulty = extra.get("difficulty")
        if difficulty:
            challenge.difficulty = str(difficulty)
            vocab_tiers.add(str(difficulty))

        db.add(challenge)
        await db.flush()
        title_to_id[title] = challenge.id
        existing_titles.add(title)
        created += 1

        # Deployment spec (instancing) from extra.deployment, validated like the
        # authoring route. A bad spec is reported per-challenge, not fatal.
        dep_spec = extra.get("deployment")
        if isinstance(dep_spec, dict):
            deployment, dep_err = _deployment_from_yaml(
                dep_spec, competition.id, challenge.id
            )
            if dep_err:
                errors.append(f"{title}: deployment: {dep_err}")
            else:
                db.add(deployment)

        # Hints.
        for h in spec.get("hints") or []:
            body = h if isinstance(h, str) else h.get("content", "")
            cost = 0 if isinstance(h, str) else int(h.get("cost") or 0)
            if body:
                db.add(
                    Hint(
                        competition_id=competition.id,
                        challenge_id=challenge.id,
                        body=body,
                        cost=cost,
                    )
                )
        # Attachment files bundled in the zip.
        for fname in spec.get("files") or []:
            path = f"{folder}/{fname}" if folder else fname
            try:
                blob = zf.read(path)
            except KeyError:
                errors.append(f"{title}: file {fname} not in zip")
                continue
            key = f"{competition.id}/{challenge.id}/{uuid4().hex}_{fname}"
            storage.put(key, blob, "application/octet-stream")
            db.add(
                Attachment(
                    competition_id=competition.id,
                    challenge_id=challenge.id,
                    filename=fname,
                    object_key=key,
                    content_type="application/octet-stream",
                    size_bytes=len(blob),
                )
            )

        if spec.get("prerequisites"):
            pending_prereqs.append(
                (challenge.id, [str(t) for t in spec["prerequisites"]])
            )

    # Resolve prerequisite titles → ids (across imported + existing challenges).
    if pending_prereqs:
        all_titles = dict(title_to_id)
        for t, cid in (
            await db.execute(
                select(Challenge.title, Challenge.id).where(
                    Challenge.competition_id == competition.id
                )
            )
        ).all():
            all_titles.setdefault(t, cid)
        for challenge_id, titles in pending_prereqs:
            ids = [all_titles[t] for t in titles if t in all_titles]
            if ids:
                (await db.get(Challenge, challenge_id)).prerequisites = ids

    # Persist any vocab additions so imported tags/difficulty validate later.
    competition.challenge_tags = sorted(vocab_tags) or None
    competition.difficulty_tiers = sorted(vocab_tiers) or None

    await db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}
