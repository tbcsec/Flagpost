"""Custom brand themes — the token vocabulary and its validator (#323, ADR-0011).

A custom theme is a **pack of the design tokens** the UI already runs on (the
same CSS variables the built-in palettes set in ``globals.css``), stored as a
``theme_presets`` row and injected onto ``<html>`` at runtime by the frontend
theme layer — exactly generalising the existing custom-accent-hex path.

Security note: the validator here is the whole safety boundary. Values are
constrained to ``#RRGGBB`` and keys to a fixed allowlist, so a token map can
never carry CSS control characters (``;``, ``{``, ``url(``, …) — injecting it
as inline ``--token: <h s% l%>`` (after the frontend's hex→HSL conversion) can't
break out of the property value. The server format-validates and never
interprets, the same posture as ``default_palette`` / ``accent`` / rich text.
"""

from __future__ import annotations

import re

# The complete token set a custom theme must define — the CSS custom properties
# every ``[data-palette]`` block in frontend/src/app/globals.css sets, minus the
# ``--`` prefix. A theme is a *complete* pack (all keys required, no extras), so
# there is never an undefined token at runtime; the editor/seeds pre-fill from a
# base palette so an author never starts blank. Keep in sync with globals.css.
THEME_TOKENS: tuple[str, ...] = (
    "background", "foreground",
    "card", "card-foreground",
    "popover", "popover-foreground",
    "primary", "primary-foreground",
    "secondary", "secondary-foreground",
    "muted", "muted-foreground",
    "accent", "accent-foreground",
    "destructive", "destructive-foreground",
    "success", "success-foreground",
    "warning", "warning-foreground",
    "border", "input", "ring",
)
_TOKEN_SET = frozenset(THEME_TOKENS)

# A theme declares which mode it is (surfaces are dark or light); drives the
# ``data-mode`` attribute so mode-dependent behaviour stays correct.
THEME_MODES: tuple[str, ...] = ("dark", "light")

# Built-in palette ids (defined in code — globals.css + lib/theme.ts). A custom
# theme's id must not collide with these, or ``default_palette`` becomes
# ambiguous. Kept here as the reservation guard; keep in sync with the frontend
# PALETTES registry (the frontend owns the canonical list).
RESERVED_PALETTE_IDS: frozenset[str] = frozenset(
    {"harbor", "eclipse", "umbra", "daybreak", "sandstone"}
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeValidationError(ValueError):
    """A theme payload is malformed; the router maps it to a 400/422."""


def validate_theme_tokens(tokens: object) -> dict[str, str]:
    """Return the tokens normalised (lowercased hex), or raise
    :class:`ThemeValidationError`. Requires **exactly** the allowlisted keys,
    each a ``#RRGGBB`` value — nothing else is representable, so nothing else can
    be injected."""
    if not isinstance(tokens, dict):
        raise ThemeValidationError("tokens must be an object of token → #RRGGBB")
    keys = set(tokens.keys())
    missing = _TOKEN_SET - keys
    if missing:
        raise ThemeValidationError(
            f"missing token(s): {', '.join(sorted(missing))}"
        )
    unknown = keys - _TOKEN_SET
    if unknown:
        raise ThemeValidationError(
            f"unknown token(s): {', '.join(sorted(unknown))}"
        )
    out: dict[str, str] = {}
    for key in THEME_TOKENS:
        value = tokens[key]
        if not isinstance(value, str) or not _HEX_RE.match(value):
            raise ThemeValidationError(
                f"token '{key}' must be a #RRGGBB hex colour"
            )
        out[key] = value.lower()
    return out


def validate_theme_mode(mode: object) -> str:
    if mode not in THEME_MODES:
        raise ThemeValidationError(
            f"mode must be one of {', '.join(THEME_MODES)}"
        )
    return mode  # type: ignore[return-value]
