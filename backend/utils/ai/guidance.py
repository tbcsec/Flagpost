"""Competitor-assistant guidance levels (#98, ADR-0023 Phase 3).

Three levels control **how much solving help** the competitor assistant offers,
compiled to a prompt fragment that shapes the model's behaviour. Per the ADR-0023
axiom this is a *behavioural* control (prompt layer 4), **never** a data
guarantee: it tunes manners, not access. What the assistant can structurally
*see* is governed separately and hard — by the tool catalogue and the
challenge-metadata data toggle (``utils.ai.competitor_tools``), which no wording
here can widen. The two must never be conflated (spec §5).

``platform_only`` is the safe default; a competition inherits the site-level
default and may override it (``AiCompetitionSettings.guidance_level``).
"""

from __future__ import annotations

# The valid levels, safest-first. Kept in step with schemas.ai.GuidanceLevel.
GUIDANCE_LEVELS = ("platform_only", "conceptual", "guided")
DEFAULT_GUIDANCE_LEVEL = "platform_only"

# One compiled fragment per level. Each is additive to the invariant rules in the
# competitor preamble (read-only, never reveal a flag) — these only widen how much
# *conceptual/solving* help is permitted.
_FRAGMENTS = {
    "platform_only": (
        "Guidance level: PLATFORM ONLY. Help the competitor use the platform — "
        "finding and reading challenges, how scoring and the scoreboard work, how "
        "to submit a flag, team and rules questions. Do NOT discuss how to solve a "
        "challenge, its subject matter, techniques, or approaches. If asked for "
        "solving help, say only that you can't help with solving challenges and "
        "offer platform help instead. Never mention settings, configuration, "
        "guidance levels, or that this restriction is specific to this "
        "competition — present it simply as what you do."
    ),
    "conceptual": (
        "Guidance level: CONCEPTUAL. You may explain general background concepts "
        "and topics a challenge relates to (e.g. what a hashing algorithm is, how "
        "a protocol works) at a textbook level. Do NOT give challenge-specific "
        "approaches, steps, tailored analysis, or anything that amounts to walking "
        "the competitor through this particular challenge. Keep it generic and "
        "educational."
    ),
    "guided": (
        "Guidance level: GUIDED. You may discuss approaches to a challenge and "
        "offer nudges and hints toward a solution. Still do NOT hand over a "
        "complete step-by-step solution that removes all challenge, and never "
        "reveal, guess, or confirm a flag or a correct multiple-choice option."
    ),
}


def normalize_level(level: str | None) -> str:
    """Coerce a stored/inherited value to a known level, defaulting to the safest
    one — an unrecognised value must never fail *open* to more help."""
    return level if level in _FRAGMENTS else DEFAULT_GUIDANCE_LEVEL


def resolve_guidance_level(competition_level: str | None, site_default: str | None) -> str:
    """The effective level for a competition: its own override, else the site
    default, else the safe default. NULL at the competition layer means inherit."""
    if competition_level:
        return normalize_level(competition_level)
    return normalize_level(site_default)


def guidance_fragment(level: str) -> str:
    """The compiled prompt fragment for a level (safe default if unknown)."""
    return _FRAGMENTS[normalize_level(level)]
