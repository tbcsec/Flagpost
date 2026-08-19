"""Competition cloning (ROADMAP Phase 9 — owner ask).

Copies a competition's *configuration* into a fresh one so an admin can set up
several near-identical events from a baseline. What's copied is the config an
organiser builds; what's deliberately **not** copied is the run's live data —
the clone starts as a clean slate.

Copied: settings (name is caller-supplied; schedule cleared; new invite code),
categories, challenges (incl. the stored flag), hints, challenge file attachments
(the stored objects are duplicated), feedback surveys + their questions (as a
closed template, no responses), and the per-competition module on/off state.

Not copied: participants / teams / role assignments, submissions / scores /
adjustments / achievements, hint reveals, tickets, announcements, notifications,
survey *responses*, automation rules, and the audit log.

Ids are regenerated and cross-references remapped (a challenge's category, a
hint's challenge, etc.). One function, run inside the caller's transaction.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.attachment import Attachment
from models.challenge import Category, Challenge
from models.competition import Competition, generate_invite_code
from models.competition_module import CompetitionModule
from models.feedback import Survey, SurveyQuestion
from models.hint import Hint
from storage.base import ObjectStorage


async def clone_competition(
    db: AsyncSession,
    source: Competition,
    new_name: str,
    storage: ObjectStorage,
) -> Competition:
    """Create and return a clone of ``source`` named ``new_name``. The caller
    commits; nothing here touches live/participant data (§ module docstring)."""
    clone = Competition(
        name=new_name,
        description=source.description,
        participation_mode=source.participation_mode,
        visibility=source.visibility,
        mc_guess_limit=source.mc_guess_limit,
        mc_penalty_pct=source.mc_penalty_pct,
        challenge_ratings_enabled=source.challenge_ratings_enabled,
        challenge_tags=source.challenge_tags,
        difficulty_tiers=source.difficulty_tiers,
        public_scoreboard=source.public_scoreboard,
        ctftime_enabled=source.ctftime_enabled,
        brackets=source.brackets,
        max_team_size=source.max_team_size,
        # Rules override travels as config (#57); acceptances are per-user run
        # state and stay behind, like scores — the clone's joiners re-accept.
        rules_override=source.rules_override,
        rules_display_only=source.rules_display_only,
        invite_code=generate_invite_code(),
        # Schedule is intentionally left unset — the admin sets fresh dates so
        # two competitions don't accidentally run on the same window.
    )
    db.add(clone)
    await db.flush()  # assign clone.id before children reference it

    # Categories: old id -> new id.
    category_map: dict[str, str] = {}
    categories = (
        await db.scalars(
            select(Category).where(Category.competition_id == source.id)
        )
    ).all()
    for cat in categories:
        new_cat = Category(
            competition_id=clone.id, name=cat.name
        )
        db.add(new_cat)
        await db.flush()
        category_map[cat.id] = new_cat.id

    # Challenges: old id -> new id (flag config + state copied verbatim).
    challenge_map: dict[str, str] = {}
    challenges = (
        await db.scalars(
            select(Challenge).where(Challenge.competition_id == source.id)
        )
    ).all()
    prereq_sources: dict[str, list] = {}
    for chal in challenges:
        new_chal = Challenge(
            competition_id=clone.id,
            title=chal.title,
            description=chal.description,
            category_id=category_map.get(chal.category_id) if chal.category_id else None,
            points=chal.points,
            scoring_type=chal.scoring_type,
            min_points=chal.min_points,
            decay=chal.decay,
            state=chal.state,
            # release_at intentionally dropped — the clone's schedule is cleared.
            flag_type=chal.flag_type,
            case_insensitive=chal.case_insensitive,
            flag_hash=chal.flag_hash,
            flag_salt=chal.flag_salt,
            flag_regex=chal.flag_regex,
            choices=chal.choices,
            tags=chal.tags,
            difficulty=chal.difficulty,
            # Copied, unlike release_at: a clone usually re-runs the same event
            # against the same infrastructure, and it's editable afterwards —
            # dropping it silently would lose authored data (#262).
            connection_info=chal.connection_info,
        )
        db.add(new_chal)
        await db.flush()
        challenge_map[chal.id] = new_chal.id
        if chal.prerequisites:
            prereq_sources[new_chal.id] = list(chal.prerequisites)

    # Second pass: remap each cloned challenge's prerequisites to the new ids now
    # that every challenge exists (they can reference each other).
    for new_id, old_prereqs in prereq_sources.items():
        remapped = [challenge_map[p] for p in old_prereqs if p in challenge_map]
        if remapped:
            (await db.get(Challenge, new_id)).prerequisites = remapped

    # Hints (per challenge).
    hints = (
        await db.scalars(select(Hint).where(Hint.competition_id == source.id))
    ).all()
    for hint in hints:
        db.add(
            Hint(
                competition_id=clone.id,
                challenge_id=challenge_map[hint.challenge_id],
                body=hint.body,
                cost=hint.cost,
                # Preserve the publish state (#213) — a hidden/scheduled hint must
                # not become visible in the clone.
                hidden=hint.hidden,
                release_at=hint.release_at,
            )
        )

    # Attachments: duplicate the stored object under a fresh key.
    attachments = (
        await db.scalars(
            select(Attachment).where(Attachment.competition_id == source.id)
        )
    ).all()
    for att in attachments:
        new_challenge_id = challenge_map[att.challenge_id]
        new_key = f"{clone.id}/{new_challenge_id}/{uuid4().hex}_{att.filename}"
        try:
            storage.put(new_key, storage.get(att.object_key), att.content_type)
        except Exception:  # noqa: BLE001 — a missing source object shouldn't abort the clone
            continue
        db.add(
            Attachment(
                competition_id=clone.id,
                challenge_id=new_challenge_id,
                filename=att.filename,
                object_key=new_key,
                content_type=att.content_type,
                size_bytes=att.size_bytes,
            )
        )

    # Surveys + questions — cloned closed (no responses copied).
    surveys = (
        await db.scalars(select(Survey).where(Survey.competition_id == source.id))
    ).all()
    for survey in surveys:
        new_survey = Survey(
            competition_id=clone.id,
            title=survey.title,
            description=survey.description,
            is_open=False,
        )
        db.add(new_survey)
        await db.flush()
        questions = (
            await db.scalars(
                select(SurveyQuestion).where(SurveyQuestion.survey_id == survey.id)
            )
        ).all()
        for q in questions:
            db.add(
                SurveyQuestion(
                    competition_id=clone.id,
                    survey_id=new_survey.id,
                    prompt=q.prompt,
                    type=q.type,
                    options=list(q.options),
                    required=q.required,
                    position=q.position,
                )
            )

    # Per-competition module on/off overrides.
    modules = (
        await db.scalars(
            select(CompetitionModule).where(
                CompetitionModule.competition_id == source.id
            )
        )
    ).all()
    for mod in modules:
        db.add(
            CompetitionModule(
                competition_id=clone.id, module_id=mod.module_id, enabled=mod.enabled
            )
        )

    return clone
