"""Pydantic schemas for rules / code-of-conduct acceptance (issue #57).

``RulesOut`` is what a user (member or prospective joiner) sees: the
*effective* document — the competition's override when set, else the site-wide
text — plus everything the client needs to decide whether to prompt. The raw
facts (``display_only``/``accepted``/``exempt``) drive the pre-join modal;
``required`` is the server's own verdict for the in-app re-acceptance gate
(it additionally requires membership, so a non-member browsing a public
competition is never nagged app-wide).
"""

from typing import Any

from pydantic import BaseModel


class RulesOut(BaseModel):
    # The effective rich-text (ProseMirror JSON) document, or null when no
    # rules are configured at either level.
    rules: dict[str, Any] | None
    # Informational-only mode: shown, never gating (owner follow-up on #57).
    display_only: bool
    # Whether the current user has an acceptance row for this competition.
    accepted: bool
    # Staff exemption: holders of edit_competition here skip the gate entirely.
    exempt: bool
    # Server verdict for the in-app gate: rules exist, mandatory, unaccepted,
    # not exempt, AND the user is already a member of the competition.
    required: bool


class RulesSettingsOut(BaseModel):
    """Site-level authoring shape (Admin → Site settings)."""

    rules_text: dict[str, Any] | None
    rules_display_only: bool


class RulesSettingsUpdate(BaseModel):
    # Null clears the site-wide rules (no document = no gate anywhere).
    rules_text: dict[str, Any] | None = None
    rules_display_only: bool = False
