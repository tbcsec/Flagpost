"""Competition lifecycle status — the gameplay gate (#221).

``Competition.status`` is ``not_started`` → ``running`` → ``ended`` (reversible: a
judge may re-start an ended competition). It is the single gate on competitor
access: challenge viewing/submission and the scoreboard are open only while
``running``; staff with ``challenge_edit`` bypass so they can build challenges
before the start and review after the end.

Both the scheduler (at ``start_at`` / ``end_at``) and a manual judge Start/Stop
drive the status. A manual action is authoritative and marks the corresponding
boundary handled via the ``*_event_fired`` dedup flags, so the scheduler won't
override the decision (`emit_lifecycle_events` only auto-transitions a boundary
whose flag is still unset). Kept separate from ``paused`` (a temporary halt
*within* a running competition) and the scoreboard freeze — orthogonal axes.
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status

from auth.deps import user_has_permission
from models.competition import Competition

NOT_STARTED = "not_started"
RUNNING = "running"
ENDED = "ended"
STATUSES = (NOT_STARTED, RUNNING, ENDED)


def is_playable(competition: Competition) -> bool:
    """Whether competitors may currently *play* — view/open challenges and submit
    flags. Only while ``running``."""
    return competition.status == RUNNING


def has_started(competition: Competition) -> bool:
    """Whether the competition has begun — ``running`` or ``ended``. The
    **results** surfaces (scoreboard, solve ticker) open once it starts and stay
    visible after it ends (the final board is read-only, not closed); they're
    closed only while ``not_started``."""
    return competition.status != NOT_STARTED


def gate_message(status_value: str) -> str:
    """The competitor-facing reason play is closed, for the given status."""
    if status_value == NOT_STARTED:
        return "This competition hasn't started yet."
    if status_value == ENDED:
        return "This competition has ended."
    return "This competition isn't open."


async def require_playable(db, competition: Competition, user_id: str) -> None:
    """Raise 403 (with a status-appropriate message) unless the competition is
    running or the caller is staff (``challenge_edit``). For play — challenge
    viewing/submission."""
    if is_playable(competition):
        return
    if await user_has_permission(db, user_id, "challenge_edit", competition.id):
        return
    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail=gate_message(competition.status),
    )


async def require_started(db, competition: Competition, user_id: str) -> None:
    """Raise 403 unless the competition has started (``running``/``ended``) or the
    caller is staff. For the **results** surfaces whose final view stays readable
    after the end — so the only closed state is ``not_started``."""
    if has_started(competition):
        return
    if await user_has_permission(db, user_id, "challenge_edit", competition.id):
        return
    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail=gate_message(competition.status),
    )


def _lifecycle_event(name: str, competition: Competition) -> tuple[str, dict]:
    return (name, {"competition_id": competition.id, "name": competition.name})


# The `*_event_fired` flags track whether the *lifecycle event* has been emitted
# over this competition's lifetime — `competition.started`/`ended` each fire
# exactly once (first occurrence, manual or scheduled). The reversible gate can
# re-open/close `status` freely without re-emitting, so a re-start / stop→start→
# stop never re-runs side-effecting lifecycle automations (there's no per-rule
# dedup in the automation engine). The scheduler consults the same flags, so a
# manual action also pre-empts the scheduled transition.


def start_transition(competition: Competition) -> tuple[str, dict] | None:
    """Open the gate: ``status → running`` (from ``not_started`` or a reversible
    ``ended``). Returns the ``competition.started`` event to emit **after commit**,
    or None when nothing to emit — either already running, or re-opening after the
    start event already fired once (the gate still flips; no duplicate event).
    Mutates in place; the caller commits."""
    if competition.status == RUNNING:
        return None
    competition.status = RUNNING
    if competition.started_event_fired:
        return None  # gate re-opened; the lifecycle event already fired once
    competition.started_event_fired = True
    return _lifecycle_event("competition.started", competition)


def stop_transition(competition: Competition) -> tuple[str, dict] | None:
    """Close the gate: ``status → ended`` (from ``running``, or cancelling a
    ``not_started``). Claims the **start** boundary too, so cancelling a not-yet-
    started competition can't later emit a spurious ``competition.started`` after
    the end. Returns the ``competition.ended`` event to emit after commit, or None
    when nothing to emit (already ended, or the end event already fired)."""
    if competition.status == ENDED:
        return None
    competition.status = ENDED
    competition.started_event_fired = True
    if competition.ended_event_fired:
        return None
    competition.ended_event_fired = True
    return _lifecycle_event("competition.ended", competition)
