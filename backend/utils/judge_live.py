"""Live judging updates for the submitter (#449).

A small ``{"type": "judging", …}`` frame on the submitter's own ``user`` room
(the per-user channel notifications already ride, ``plugins/notifications``)
whenever one of their judgings changes state — queued, running, done, failed —
so the problem page refetches the judging instead of polling for it. Ids and
state only: what the competitor may see is decided by the REST read, which the
frame merely prompts.

Best-effort by design: a lost frame costs a refresh, never a verdict, so a
broadcast failure is logged and swallowed rather than allowed to break the
judging that triggered it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def push_judging(
    *,
    competition_id: str,
    challenge_id: str,
    judging_id: str,
    user_id: str,
    status: str,
    verdict: str | None = None,
) -> None:
    from realtime import manager

    frame = {
        "type": "judging",
        "competition_id": competition_id,
        "challenge_id": challenge_id,
        "judging_id": judging_id,
        "status": status,
        "verdict": verdict,
    }
    try:
        await manager.broadcast("user", user_id, frame)
    except Exception:  # noqa: BLE001 — a missed frame costs a refresh, nothing more
        logger.warning("couldn't push judging %s to its submitter", judging_id, exc_info=True)
