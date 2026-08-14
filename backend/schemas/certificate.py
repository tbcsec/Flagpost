"""Certificate schemas (#219, ADR-0027).

The element union is the main input-hardening surface: positions are clamped to
percentages, text length and element count are capped, fonts/tokens/colours are
whitelisted — so a saved template can never be turned into a giant or malformed
render. Kept separate from the SQLAlchemy models (a route never returns a model).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from plugins.certificates.assets import (
    DEFAULT_COLOR,
    DEFAULT_FONT,
    FONT_IDS,
    FONT_SIZE_MAX,
    FONT_SIZE_MIN,
    MAX_ELEMENTS,
    MAX_IMAGE_ELEMENTS,
    MAX_TEXT_LEN,
    PRESET_IDS,
    TOKEN_KEYS,
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# An element may reference an organiser-uploaded font as ``custom:<uuid>``. The
# schema can't know a competition's fonts (it's DB-free), so it only shape-checks
# the ref; the route validates the font actually exists in this competition.
_CUSTOM_FONT_RE = re.compile(
    r"^custom:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# A week is plenty for an "end + N minutes" release; caps an absurd schedule.
MAX_RELEASE_DELAY_MINUTES = 10_080


def _validate_hex(value: str) -> str:
    if not _HEX_RE.match(value):
        raise ValueError("colour must be a 6-digit hex like #1a2b3c")
    return value.lower()


# --- Layout elements (discriminated union on `type`) ------------------------


class _BaseElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Anchor: top-left of the element box, as a percentage of the canvas.
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    # Box width as a percentage of canvas width; text aligns/wraps within it.
    width: float = Field(default=40.0, gt=0, le=100)


class _TextualElement(_BaseElement):
    font: str = DEFAULT_FONT
    # Font size as a percentage of canvas height, so it scales with the render.
    font_size: float = Field(default=6.0, ge=FONT_SIZE_MIN, le=FONT_SIZE_MAX)
    color: str = "#111827"
    align: Literal["left", "center", "right"] = "center"
    bold: bool = False
    italic: bool = False

    @field_validator("font")
    @classmethod
    def _known_font(cls, v: str) -> str:
        if v in FONT_IDS or _CUSTOM_FONT_RE.match(v):
            return v
        raise ValueError(f"unknown font {v!r}")

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        return _validate_hex(v)


class TokenElement(_TextualElement):
    type: Literal["token"] = "token"
    token: str

    @field_validator("token")
    @classmethod
    def _known_token(cls, v: str) -> str:
        if v not in TOKEN_KEYS:
            raise ValueError(f"unknown token {v!r}")
        return v


class TextElement(_TextualElement):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=MAX_TEXT_LEN)


class ImageElement(_BaseElement):
    type: Literal["image"] = "image"
    # Object-storage key of a previously-uploaded image (signature/sponsor mark).
    image_key: str = Field(min_length=1, max_length=512)


CertificateElement = Annotated[
    Union[TokenElement, TextElement, ImageElement],
    Field(discriminator="type"),
]


# --- Template I/O -----------------------------------------------------------


class CertificateTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background_kind: Literal["color", "preset", "upload"] = "color"
    background_preset: str | None = None
    background_color: str = DEFAULT_COLOR
    # Optional per-preset colour overrides (hex); null = the preset default.
    preset_accent: str | None = None
    preset_base: str | None = None
    elements: list[CertificateElement] = Field(
        default_factory=list, max_length=MAX_ELEMENTS
    )
    recipient_rule: Literal["all", "solvers"] = "all"
    release_mode: Literal["manual", "on_end", "end_delay"] = "manual"
    release_delay_minutes: int = Field(
        default=0, ge=0, le=MAX_RELEASE_DELAY_MINUTES
    )

    @field_validator("background_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        return _validate_hex(v)

    @field_validator("preset_accent", "preset_base")
    @classmethod
    def _opt_hex(cls, v: str | None) -> str | None:
        return None if v is None else _validate_hex(v)

    @field_validator("background_preset")
    @classmethod
    def _known_preset(cls, v: str | None) -> str | None:
        if v is not None and v not in PRESET_IDS:
            raise ValueError(f"unknown preset {v!r}")
        return v

    @field_validator("elements")
    @classmethod
    def _image_cap(cls, v: list) -> list:
        # Bound image elements specifically (each is a decode at render), not just
        # the total element count — the manifest advertises this cap.
        if sum(1 for e in v if getattr(e, "type", None) == "image") > MAX_IMAGE_ELEMENTS:
            raise ValueError(f"at most {MAX_IMAGE_ELEMENTS} image elements are allowed")
        return v


class CertificateTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    background_kind: str
    background_preset: str | None
    background_color: str
    preset_accent: str | None
    preset_base: str | None
    has_background_image: bool
    elements: list
    recipient_rule: str
    release_mode: str
    release_delay_minutes: int
    released_at: datetime | None
    released: bool


class CertificateFontOut(BaseModel):
    """An organiser-uploaded custom font, referenced by an element as
    ``font="custom:<id>"``. ``format`` is ``"ttf"``/``"otf"``."""

    id: str
    name: str
    format: str


# --- Template export / import ----------------------------------------------
# The import shape is deliberately permissive at the outer layer (extra keys
# ignored for forward-compat); the design is re-validated through
# CertificateTemplateUpdate after asset references are rewritten (see the router).


class CertificateImportAsset(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: str  # base64
    format: str = ""
    name: str | None = None  # font display label


class CertificateImportAssets(BaseModel):
    model_config = ConfigDict(extra="ignore")

    background_image: CertificateImportAsset | None = None
    images: dict[str, CertificateImportAsset] = Field(default_factory=dict)
    fonts: dict[str, CertificateImportAsset] = Field(default_factory=dict)


class CertificateTemplateImport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    flagpost_certificate_template: int
    template: dict = Field(default_factory=dict)
    assets: CertificateImportAssets = Field(default_factory=CertificateImportAssets)


# --- Participant-facing + admin release list --------------------------------


class MyCertificateOut(BaseModel):
    """One released certificate a participant can download (cross-competition)."""

    competition_id: str
    competition_name: str
    released_at: datetime


class CertificateAvailabilityOut(BaseModel):
    """Whether the current user has a downloadable certificate here."""

    available: bool
    released_at: datetime | None = None
    competition_name: str | None = None


# --- Bulk export job --------------------------------------------------------


class CertificateExportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    total: int
    rendered: int
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    # Present only when status == "done": a short-lived signed URL to the ZIP.
    download_url: str | None = None
