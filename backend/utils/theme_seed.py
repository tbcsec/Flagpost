"""Shipped example brand themes (#323, ADR-0011).

Two-to-three complete custom themes seeded on first boot so the feature ships
with variety, demonstrates the exact uploadable token format, and gives admins
starting points to clone. They are ordinary ``source="builtin"`` rows — editable
and deletable like any custom theme.

Seed policy: **seed only when the table is empty** (``seed_builtin_themes``), so
an admin who edits or deletes a seed keeps that decision across restarts. The one
edge — deleting *every* theme, then restarting — re-adds the examples, which is
benign (an empty library is exactly when the examples are useful again).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.theme_preset import ThemePreset
from utils.theme_tokens import validate_theme_tokens

# Each is a complete pack of every THEME_TOKENS key; validated at seed time so a
# malformed example fails loudly rather than shipping a broken theme.
_BUILTIN_THEMES: tuple[dict, ...] = (
    {
        "id": "corporate-blue",
        "name": "Corporate blue",
        "mode": "light",
        "tokens": {
            "background": "#f4f7fb", "foreground": "#16233d",
            "card": "#ffffff", "card-foreground": "#16233d",
            "popover": "#ffffff", "popover-foreground": "#16233d",
            "primary": "#0b57d0", "primary-foreground": "#ffffff",
            "secondary": "#e6edf7", "secondary-foreground": "#16233d",
            "muted": "#eef2f8", "muted-foreground": "#5b6b85",
            "accent": "#e6edf7", "accent-foreground": "#16233d",
            "destructive": "#d92d20", "destructive-foreground": "#ffffff",
            "success": "#1a7f4b", "success-foreground": "#ffffff",
            "warning": "#b25e09", "warning-foreground": "#ffffff",
            "border": "#d5deea", "input": "#d5deea", "ring": "#0b57d0",
        },
    },
    {
        "id": "midnight",
        "name": "Midnight",
        "mode": "dark",
        "tokens": {
            "background": "#0f1420", "foreground": "#e6ebf5",
            "card": "#151b2b", "card-foreground": "#e6ebf5",
            "popover": "#151b2b", "popover-foreground": "#e6ebf5",
            "primary": "#4f8cff", "primary-foreground": "#0f1420",
            "secondary": "#1e2740", "secondary-foreground": "#e6ebf5",
            "muted": "#1a2233", "muted-foreground": "#8a99b8",
            "accent": "#1e2740", "accent-foreground": "#e6ebf5",
            "destructive": "#f2555a", "destructive-foreground": "#0f1420",
            "success": "#34d399", "success-foreground": "#0f1420",
            "warning": "#fbbf24", "warning-foreground": "#0f1420",
            "border": "#263149", "input": "#263149", "ring": "#4f8cff",
        },
    },
    {
        "id": "neon",
        "name": "Neon",
        "mode": "dark",
        "tokens": {
            "background": "#0c0710", "foreground": "#f6edff",
            "card": "#17101f", "card-foreground": "#f6edff",
            "popover": "#17101f", "popover-foreground": "#f6edff",
            "primary": "#ff2d8e", "primary-foreground": "#1a0410",
            "secondary": "#241633", "secondary-foreground": "#f6edff",
            "muted": "#1c1327", "muted-foreground": "#a98fc4",
            "accent": "#241633", "accent-foreground": "#f6edff",
            "destructive": "#ff4d67", "destructive-foreground": "#1a0410",
            "success": "#2ce6a0", "success-foreground": "#0c0710",
            "warning": "#ffb020", "warning-foreground": "#0c0710",
            "border": "#2e2140", "input": "#2e2140", "ring": "#ff2d8e",
        },
    },
)


async def seed_builtin_themes(db: AsyncSession) -> int:
    """Insert the example themes iff ``theme_presets`` is empty. Returns how many
    were inserted (0 once any theme exists). Idempotent and safe to call on every
    boot."""
    existing = await db.scalar(select(func.count()).select_from(ThemePreset))
    if existing:
        return 0
    for spec in _BUILTIN_THEMES:
        db.add(
            ThemePreset(
                id=spec["id"],
                name=spec["name"],
                mode=spec["mode"],
                tokens=validate_theme_tokens(spec["tokens"]),
                source="builtin",
            )
        )
    await db.commit()
    return len(_BUILTIN_THEMES)
