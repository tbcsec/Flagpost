"""Certificate asset registry — fonts, tokens, presets, bounds (#219, ADR-0027).

The **single source of truth** the renderer (``render.py``) and the editor
manifest (served to the frontend) both read from, so the WYSIWYG editor and the
server render agree on the font set, the token vocabulary, the canvas geometry,
and the input bounds (ADR-0027's parity contract). Deliberately **PIL-free** —
pure data + filesystem paths — so importing it (for the manifest, or for schema
validation bounds) never pulls in Pillow.
"""

from __future__ import annotations

from pathlib import Path

FONTS_DIR = Path(__file__).parent / "assets" / "fonts"

# --- Canvas geometry (ADR-0027) --------------------------------------------
# Landscape A4 at ~212 DPI; 2480/1754 = √2, the A4 aspect ratio. The finished PNG
# is exactly this — the branding is a subtle mark composited along the bottom
# *inside* the canvas (draw_brand_mark), not a separate band.
CANVAS_W = 2480
CANVAS_H = 1754

# --- Input bounds (imported by schemas.certificate) ------------------------
# A template can't be weaponised into a giant render: cap element count, text
# length, and font size. Positions are percentages, clamped to [0, 100].
MAX_ELEMENTS = 60
MAX_TEXT_LEN = 240
MAX_IMAGE_ELEMENTS = 8
FONT_SIZE_MIN = 1.0   # % of canvas height (~17px)
FONT_SIZE_MAX = 30.0  # % of canvas height (~526px)

# --- Fonts (bundled, SIL OFL — Liberation 2.1) -----------------------------
# id → display label + the four variant files. The editor loads the *same* files
# via @font-face and Pillow loads them by path, so preview == render.
FONTS: dict[str, dict] = {
    "serif": {
        "label": "Liberation Serif",
        "variants": {
            (False, False): "LiberationSerif-Regular.ttf",
            (True, False): "LiberationSerif-Bold.ttf",
            (False, True): "LiberationSerif-Italic.ttf",
            (True, True): "LiberationSerif-BoldItalic.ttf",
        },
    },
    "sans": {
        "label": "Liberation Sans",
        "variants": {
            (False, False): "LiberationSans-Regular.ttf",
            (True, False): "LiberationSans-Bold.ttf",
            (False, True): "LiberationSans-Italic.ttf",
            (True, True): "LiberationSans-BoldItalic.ttf",
        },
    },
    # Noto Serif Display (OFL) — a high-contrast display serif for elegant
    # certificate headings, distinct from the workhorse Liberation Serif.
    "display": {
        "label": "Noto Serif Display",
        "variants": {
            (False, False): "NotoSerifDisplay-Regular.ttf",
            (True, False): "NotoSerifDisplay-Bold.ttf",
            (False, True): "NotoSerifDisplay-Italic.ttf",
            (True, True): "NotoSerifDisplay-BoldItalic.ttf",
        },
    },
    # Lato (OFL) — a clean, friendly humanist sans for professional certificates.
    "lato": {
        "label": "Lato",
        "variants": {
            (False, False): "Lato-Regular.ttf",
            (True, False): "Lato-Bold.ttf",
            (False, True): "Lato-Italic.ttf",
            (True, True): "Lato-BoldItalic.ttf",
        },
    },
    "mono": {
        "label": "Liberation Mono",
        "variants": {
            (False, False): "LiberationMono-Regular.ttf",
            (True, False): "LiberationMono-Bold.ttf",
            (False, True): "LiberationMono-Italic.ttf",
            (True, True): "LiberationMono-BoldItalic.ttf",
        },
    },
    # Fira Code (OFL) — the coding font with ligatures; the CTF/hacker touch.
    # Ships regular + bold only (a monospace has no true italic); the fallback
    # in font_path maps italic requests to the nearest upright weight.
    "code": {
        "label": "Fira Code",
        "variants": {
            (False, False): "FiraCode-Regular.ttf",
            (True, False): "FiraCode-Bold.ttf",
        },
    },
    # Rajdhani (OFL) — condensed, squared, tactical/HUD; a cyber display face.
    "rajdhani": {
        "label": "Rajdhani",
        "variants": {
            (False, False): "Rajdhani-Regular.ttf",
            (True, False): "Rajdhani-Bold.ttf",
        },
    },
    # Orbitron (OFL) — wide geometric sci-fi; the most overtly "cyber" face.
    "orbitron": {
        "label": "Orbitron",
        "variants": {
            (False, False): "Orbitron-Regular.ttf",
            (True, False): "Orbitron-Bold.ttf",
        },
    },
}
DEFAULT_FONT = "serif"
FONT_IDS = frozenset(FONTS)


def font_path(family: str, *, bold: bool = False, italic: bool = False) -> Path:
    """Absolute path to a bundled font file. Falls back gracefully: an unknown
    family → the default; a missing italic → the same weight upright; a missing
    bold-italic → bold, then regular — so a font that ships only regular+bold
    (Fira Code, Orbitron, Rajdhani) still honours a bold request."""
    spec = FONTS.get(family) or FONTS[DEFAULT_FONT]
    variants = spec["variants"]
    filename = (
        variants.get((bold, italic))
        or variants.get((bold, False))
        or variants[(False, False)]
    )
    return FONTS_DIR / filename


# --- Token vocabulary (v1) --------------------------------------------------
# key → (label, sample). Samples drive both the admin preview and the editor's
# live canvas, so an organiser sees realistic output before the event ends.
TOKENS: list[dict[str, str]] = [
    {"key": "recipient_name", "label": "Recipient name", "sample": "Ada Lovelace"},
    {"key": "competition_name", "label": "Competition name", "sample": "Flagpost CTF"},
    {"key": "placement", "label": "Placement", "sample": "3rd place"},
    {"key": "points", "label": "Points", "sample": "1,250"},
    {"key": "solve_count", "label": "Solves", "sample": "18"},
    {"key": "bracket", "label": "Bracket", "sample": "University"},
    {"key": "participant_count", "label": "Participants", "sample": "240"},
    {"key": "competition_end_date", "label": "Competition end date", "sample": "13 August 2026"},
    {"key": "issue_date", "label": "Issue date", "sample": "13 August 2026"},
]
TOKEN_KEYS = frozenset(t["key"] for t in TOKENS)
SAMPLE_TOKENS: dict[str, str] = {t["key"]: t["sample"] for t in TOKENS}

# --- Background presets (code-drawn by render.draw_preset_background) --------
# No committed image assets: the renderer draws these, and the editor shows them
# through the asset endpoint, so there is one source of truth and no CSS drift.
# Each preset exposes two adjustable colours (like the site-branding accent/base):
# `accent` (trim / glow / lines) and `base` (the ground). These are the built-in
# defaults; a template may override either (preset_accent / preset_base).
PRESETS: list[dict[str, str]] = [
    # Flagpost-branded + login-screen-inspired styles (drawn in render.py).
    {"id": "signal", "label": "Signal", "accent": "#1f9e6b", "base": "#f7f9fb"},
    {"id": "aurora", "label": "Aurora", "accent": "#2cb57c", "base": "#111b28"},
    {"id": "mesh", "label": "Mesh", "accent": "#2cb57c", "base": "#111b28"},
    {"id": "circuit", "label": "Circuit", "accent": "#2cb57c", "base": "#111b28"},
    {"id": "terminal", "label": "Terminal", "accent": "#2cb57c", "base": "#111b28"},
    # Neutral originals.
    {"id": "classic", "label": "Classic", "accent": "#b8985a", "base": "#fbf8f1"},
    {"id": "elegant", "label": "Elegant", "accent": "#1f2937", "base": "#f7f7f5"},
    {"id": "modern", "label": "Modern", "accent": "#2563eb", "base": "#ffffff"},
    {"id": "dark", "label": "Dark", "accent": "#94a3b8", "base": "#0f172a"},
]
PRESET_IDS = frozenset(p["id"] for p in PRESETS)
PRESET_DEFAULTS: dict[str, tuple[str, str]] = {p["id"]: (p["accent"], p["base"]) for p in PRESETS}
DEFAULT_COLOR = "#ffffff"


def preset_colors(
    preset_id: str, accent: str | None = None, base: str | None = None
) -> tuple[str, str]:
    """Resolve a preset's (accent, base) — a template override wins over the
    preset's built-in default."""
    default_accent, default_base = PRESET_DEFAULTS.get(preset_id, ("#1f2937", "#ffffff"))
    return (accent or default_accent, base or default_base)


def ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def placement_label(rank: int, *, is_scorer: bool) -> str:
    """"3rd place" for a scorer; "Participant" for a non-scorer (ADR-0027 —
    everyone gets a shareable certificate, podium or not)."""
    return f"{ordinal(rank)} place" if is_scorer else "Participant"


def build_manifest() -> dict:
    """The editor's configuration payload (fonts, tokens, presets, geometry,
    bounds). Served unauthenticated — none of it is sensitive."""
    return {
        "canvas": {
            "width": CANVAS_W,
            "height": CANVAS_H,
            "aspect_ratio": round(CANVAS_W / CANVAS_H, 4),
        },
        "fonts": [
            {"id": fid, "label": spec["label"]} for fid, spec in FONTS.items()
        ],
        "default_font": DEFAULT_FONT,
        "tokens": TOKENS,
        "presets": PRESETS,
        "default_color": DEFAULT_COLOR,
        "bounds": {
            "max_elements": MAX_ELEMENTS,
            "max_text_len": MAX_TEXT_LEN,
            "max_image_elements": MAX_IMAGE_ELEMENTS,
            "font_size_min": FONT_SIZE_MIN,
            "font_size_max": FONT_SIZE_MAX,
        },
    }
