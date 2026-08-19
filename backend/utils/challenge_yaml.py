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
