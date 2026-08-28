"""Custom brand theme model (#323, ADR-0011).

A **site-level** theme preset: a complete pack of the design tokens the UI runs
on (the same CSS variables the built-in palettes set in ``globals.css``), stored
as data rather than code so an organisation can brand the whole surface without
a rebuild. Site-level, not competition-scoped — theming is site-wide (ADR-0011),
so no ``competition_id`` and no §6.2 tenancy filter.

The active theme is still just ``site_settings.default_palette``: that id may now
name a built-in palette (defined in code) *or* a preset ``id`` here. Presets are
applied by injecting their ``tokens`` onto ``<html>`` at runtime — no
``[data-palette]`` CSS block, unlike the built-ins.

Two or three ``source="builtin"`` example presets are seeded on first run (see
``utils/theme_seed``) to demonstrate the format and act as starting points; they
are ordinary editable/deletable rows thereafter.
"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from db import Base, TimestampMixin

# Where a preset came from — a label only; both kinds are editable and deletable.
THEME_SOURCES: tuple[str, ...] = ("builtin", "custom")


class ThemePreset(Base, TimestampMixin):
    __tablename__ = "theme_presets"

    # The id IS the palette id ``default_palette`` points at and the frontend
    # injects under — a human slug, set at creation and **immutable** (renaming
    # would dangle the active-theme pointer). The display ``name`` is edited
    # instead. Validated against RESERVED_PALETTE_IDS so it can't shadow a
    # built-in palette.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # One of utils.theme_tokens.THEME_MODES.
    mode: Mapped[str] = mapped_column(String, nullable=False)
    # {token: "#rrggbb"} covering the full THEME_TOKENS set. Format-validated on
    # write (utils.theme_tokens.validate_theme_tokens); never interpreted here.
    tokens: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="custom", server_default="custom"
    )
    # Who authored it; SET NULL so deleting the author leaves the theme.
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
