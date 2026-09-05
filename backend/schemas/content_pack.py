"""Content-pack install result (Tier 0 marketplace, #387, ADR-0040)."""

from __future__ import annotations

from pydantic import BaseModel


class ContentPackInstallOut(BaseModel):
    """Summary of an installed content pack. ``result`` is type-specific:
    ``{created, skipped, errors}`` for a challenge pack, ``{installed, skipped}``
    for a theme pack."""

    id: str
    name: str
    version: str
    pack_type: str
    target: str  # a competition id, or "site" for site-wide packs
    result: dict
