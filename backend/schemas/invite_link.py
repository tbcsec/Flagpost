"""Pydantic schemas for competition invite links (#427).

Kept separate from the ``InviteLink`` model (code convention). Three shapes:
``InviteLinkCreate`` (organiser write), ``InviteLinkOut`` (organiser read — the
token is returned only to the manager who already holds ``manage_invite_links``),
and ``InviteLinkResolved`` (the public landing payload — deliberately minimal, no
token, no internal counters).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Capability = Literal["join", "view"]


class InviteLinkJoinRequest(BaseModel):
    """Body for completing a join through a link. Mirrors the invite-code path:
    ``accept_rules`` lets the competitor accept the (possibly first-seen) rules in
    the same request, and ``field_values`` carries individual-mode registration
    answers."""

    model_config = ConfigDict(extra="forbid")

    accept_rules: bool = False
    field_values: dict[str, Any] | None = None


class InviteLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: Capability
    label: str | None = Field(default=None, max_length=200)
    # NULL = no limit. A past expiry or max_uses < 1 would create a dead link, so
    # both are bounded here rather than silently accepted.
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)


class InviteLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    token: str
    capability: Capability
    label: str | None
    expires_at: datetime | None
    max_uses: int | None
    use_count: int
    # When the link last admitted someone (new-join semantics, like use_count).
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    # Computed (utils.invite_links.is_active): usable right now — not revoked, not
    # expired, uses remaining. A view link that's gone un-shareable (competition
    # turned private / scoreboard hidden) is still "active" here but resolves 404
    # publicly; this flag is the lifecycle state the organiser controls.
    active: bool


class InviteLinkResolved(BaseModel):
    """What a recipient's landing page gets back for a valid link — no token, no
    counters. For a ``join`` link the competition name is disclosed because the
    token authorizes it; for a ``view`` link it only resolves when the
    competition is publicly visible anyway."""

    capability: Capability
    competition_id: str
    competition_name: str
    competition_status: Literal["not_started", "running", "ended"]
    participation_mode: Literal["team", "individual"]
    # join: can this link still admit someone. view: whether the public
    # spectator board is currently available.
    actionable: bool
    # Why a join link isn't actionable (#427 Phase 4) — lets the landing explain
    # the block honestly instead of a generic "can't join". None when actionable
    # (and always None for view links).
    reason: Literal["ended", "registration_not_open", "registration_closed"] | None = (
        None
    )
    # join links require sign-in to complete; view links do not.
    requires_login: bool
