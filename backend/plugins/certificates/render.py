"""Certificate renderer — Pillow compositing → PNG (#219, ADR-0027).

Deliberately **pure**: no DB, no object-storage I/O. The caller resolves a
recipient's token values and any image bytes and passes them in, so rendering is
deterministic and unit-testable, and the same code path serves the admin preview
(sample tokens) and a participant's real download. The branding footer is
composited *below* the design area by this module — the client only ever
receives the finished PNG, so it is structurally un-removable (ADR-0027).

Rendering is CPU-bound; callers run it via ``asyncio.to_thread`` so the event
loop is never blocked.
"""

from __future__ import annotations

import colorsys
import io
import logging
import math
import random
from collections.abc import Mapping
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger("certificates")

# Hard cap on the *source* pixels of any image we decode at render time. The
# upload routes already pixel-budget-check, but that gate fails open on an
# unreadable header, so this is the render-boundary backstop against a
# decompression bomb (a small file that decodes to gigabytes of RGBA). Aligned
# with the upload budget (utils.image_sniff.MAX_IMAGE_PIXELS).
MAX_RENDER_SOURCE_PIXELS = 40_000_000

from plugins.certificates.assets import (
    CANVAS_H,
    CANVAS_W,
    DEFAULT_COLOR,
    font_path,
    ordinal,
    placement_label,
    preset_colors,
)

__all__ = ["render_certificate_png", "draw_preset_background", "ordinal", "placement_label"]

_LINE_HEIGHT = 1.25  # mirrored in the editor CSS for preview↔render parity


@lru_cache(maxsize=512)
def load_font(family: str, bold: bool, italic: bool, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        str(font_path(family, bold=bold, italic=italic)), max(1, size_px)
    )


def _resolve_font(
    family: str,
    bold: bool,
    italic: bool,
    size_px: int,
    font_bytes: Mapping[str, bytes],
    cache: dict,
) -> ImageFont.FreeTypeFont:
    """A bundled font (cached by name) or an organiser's uploaded ``custom:<id>``
    font (parsed from its bytes). An unresolved custom id — one whose font was
    deleted, or that isn't supplied for this render — falls through to the bundled
    fallback in :func:`font_path`, so a missing font degrades to a default rather
    than failing the element."""
    if family.startswith("custom:") and family in font_bytes:
        key = (family, size_px)
        font = cache.get(key)
        if font is None:
            font = ImageFont.truetype(io.BytesIO(font_bytes[family]), max(1, size_px))
            cache[key] = font
        return font
    return load_font(family, bold, italic, size_px)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = (value or DEFAULT_COLOR).lstrip("#")
    if len(h) != 6:
        h = "ffffff"
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    """Greedy word-wrap to fit ``max_w`` px. A single over-long word overflows
    rather than being force-split (acceptable for short certificate lines)."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for word in words[1:]:
        if font.getlength(f"{cur} {word}") <= max_w:
            cur = f"{cur} {word}"
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


# Ink colours for the brand mark footer (adapts to background luminance).
_C_FG = "#f1f5f8"    # near-white, for the mark on dark grounds
_C_INK = "#0f161f"   # near-black, for the mark on light grounds


def _mix(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    """Blend ``a`` over ``b`` by fraction ``t`` (opaque result)."""
    return tuple(round(a[i] * t + b[i] * (1 - t)) for i in range(3))


def _glow(img: Image.Image, cx: float, cy: float, radius: float, rgb: tuple, strength: float) -> None:
    """Alpha-blend a soft radial glow of ``rgb`` onto ``img`` (login-screen look).
    The falloff is squared so the glow fades fully to transparent before the tile
    edge — otherwise the radial gradient's non-zero edge midpoints read as square
    banding."""
    radius = int(radius)
    if radius <= 0:
        return
    base = ImageOps.invert(Image.radial_gradient("L")).resize((radius * 2, radius * 2))
    mask = base.point(lambda a: int((a / 255) ** 3 * 255 * strength))
    img.paste(Image.new("RGB", mask.size, rgb), (int(cx - radius), int(cy - radius)), mask)


def _flag_mark(draw: ImageDraw.ImageDraw, ox: float, oy: float, size: float, post, flag, *, ground=True) -> None:
    """Draw the Flagpost mark (LOGO-SPEC: flag on a post) at (ox, oy), scaled to
    ``size`` px, in the given post/flag colours. Geometry mirrors flagpost-mark.tsx."""
    s = size / 64.0

    def P(x, y):
        return (ox + x * s, oy + y * s)

    if ground:
        draw.ellipse([P(22 - 12, 55 - 3.2), P(22 + 12, 55 + 3.2)], fill=post)
    draw.rounded_rectangle([P(19, 6), P(25, 55)], radius=3 * s, fill=post)
    draw.polygon([P(25, 9), P(46, 9), P(40.5, 16), P(46, 23), P(25, 23)], fill=flag)


def _shift_hue(rgb: tuple, degrees: float) -> tuple[int, int, int]:
    """Rotate a colour's hue (the login backgrounds derive their second glow as
    the accent hue-shifted +150°; presets do the same so one accent recolours
    the whole scheme)."""
    hh, ll, ss = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    r, g, b = colorsys.hls_to_rgb((hh + degrees / 360.0) % 1.0, ll, ss)
    return (round(r * 255), round(g * 255), round(b * 255))


# The five drawn presets. Each takes resolved (accent, base) RGB tuples so the
# colours are customisable per template; the second glow tint is derived from the
# accent by hue-shift.
def _preset_signal(w: int, h: int, accent: tuple, base: tuple) -> Image.Image:
    """Brand: a clean certificate with an accent trim + a subtle flag watermark."""
    img = Image.new("RGB", (w, h), base)
    draw = ImageDraw.Draw(img)
    _flag_mark(draw, int(w * 0.60), int(h * 0.34), int(h * 0.62),
               _mix(accent, base, 0.09), _mix(accent, base, 0.11), ground=False)
    draw.rectangle([0, 0, w, int(h * 0.015)], fill=accent)  # top accent bar
    m = int(w * 0.032)
    draw.rectangle([m, m, w - m, h - m], outline=accent, width=max(2, int(h * 0.0022)))
    return img


def _preset_aurora(w: int, h: int, accent: tuple, base: tuple) -> Image.Image:
    """Login 'aurora': soft accent + hue-partner glows on the base, calm centre."""
    img = Image.new("RGB", (w, h), base)
    sec = _shift_hue(accent, 150)
    r = max(w, h)
    _glow(img, w * 0.16, h * 0.18, r * 0.40, accent, 0.50)
    _glow(img, w * 0.86, h * 0.80, r * 0.42, sec, 0.38)
    _glow(img, w * 0.72, h * 0.16, r * 0.24, accent, 0.28)
    _glow(img, w * 0.22, h * 0.88, r * 0.26, accent, 0.24)
    draw = ImageDraw.Draw(img)
    m = int(w * 0.03)
    draw.rectangle([m, m, w - m, h - m], outline=_mix(accent, base, 0.5),
                   width=max(2, int(h * 0.0022)))
    return img


def _preset_mesh(w: int, h: int, accent: tuple, base: tuple) -> Image.Image:
    """Login 'gradient': a soft two-tone mesh (accent + its hue partner)."""
    img = Image.new("RGB", (w, h), base)
    sec = _shift_hue(accent, 150)
    r = max(w, h)
    _glow(img, w * 0.26, h * 0.28, r * 0.72, accent, 0.46)
    _glow(img, w * 0.78, h * 0.74, r * 0.72, sec, 0.34)
    return img


def _preset_circuit(w: int, h: int, accent: tuple, base: tuple) -> Image.Image:
    """Login 'constellation': an accent node/line network on the base (CTF vibe).
    Seeded so a certificate renders identically every time (ADR-0027)."""
    img = Image.new("RGB", (w, h), base)
    _glow(img, w * 0.5, h * -0.05, max(w, h) * 0.5, accent, 0.16)
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(7)
    nodes = [(rng.uniform(0, w), rng.uniform(0, h)) for _ in range(28)]
    link = max(w, h) * 0.17
    lw = max(1, int(w * 0.0009))
    for i, (ax, ay) in enumerate(nodes):
        for bx, by in nodes[i + 1:]:
            d = math.hypot(ax - bx, ay - by)
            if d < link:
                draw.line([(ax, ay), (bx, by)], fill=(*accent, int(90 * (1 - d / link))), width=lw)
    r = max(2, int(w * 0.0026))
    for x, y in nodes:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(*accent, 210))
    m = int(w * 0.03)
    draw.rectangle([m, m, w - m, h - m], outline=(*accent, 90), width=max(2, int(h * 0.0022)))
    return img


def _preset_terminal(w: int, h: int, accent: tuple, base: tuple) -> Image.Image:
    """Brand: a dark hacker 'terminal' — faint scanlines, accent frame + prompt."""
    img = Image.new("RGB", (w, h), base)
    _glow(img, w * 0.5, h * -0.04, max(w, h) * 0.45, accent, 0.12)
    draw = ImageDraw.Draw(img, "RGBA")
    step = max(3, int(h * 0.008))
    for y in range(0, h, step):  # CRT scanlines
        draw.line([(0, y), (w, y)], fill=(255, 255, 255, 6), width=1)
    m = int(w * 0.03)
    draw.rectangle([m, m, w - m, h - m], outline=(*accent, 150), width=max(2, int(h * 0.0026)))
    prompt = load_font("code", False, False, max(12, int(h * 0.018)))
    draw.text((int(w * 0.055), int(h * 0.05)), "> flagpost:~$ _", font=prompt, fill=(*accent, 210))
    return img


_PRESET_FUNCS = {
    "signal": _preset_signal,
    "aurora": _preset_aurora,
    "mesh": _preset_mesh,
    "circuit": _preset_circuit,
    "terminal": _preset_terminal,
}


def draw_preset_background(
    preset: str, w: int, h: int, accent: str | None = None, base: str | None = None
) -> Image.Image:
    """A bundled, code-drawn background style (no committed image assets), in the
    preset's colours — ``accent``/``base`` override the preset's defaults."""
    acc_hex, base_hex = preset_colors(preset, accent, base)
    acc, bas = _hex_to_rgb(acc_hex), _hex_to_rgb(base_hex)
    if preset in _PRESET_FUNCS:
        return _PRESET_FUNCS[preset](w, h, acc, bas)

    img = Image.new("RGB", (w, h), bas)
    draw = ImageDraw.Draw(img)
    if preset == "classic":
        m1, m2 = int(w * 0.030), int(w * 0.044)
        lw = max(2, int(h * 0.006))
        draw.rectangle([m1, m1, w - m1, h - m1], outline=acc, width=lw)
        draw.rectangle([m2, m2, w - m2, h - m2], outline=acc, width=max(1, lw // 2))
    elif preset == "modern":
        bar = int(w * 0.05)
        draw.rectangle([0, 0, bar, h], fill=acc)
    elif preset == "elegant":
        m = int(w * 0.035)
        draw.rectangle([m, m, w - m, h - m], outline=acc, width=max(2, int(h * 0.004)))
        c = int(w * 0.012)
        for cx, cy in [(m, m), (w - m, m), (m, h - m), (w - m, h - m)]:
            draw.rectangle([cx - c, cy - c, cx + c, cy + c], fill=acc)
    elif preset == "dark":
        m = int(w * 0.030)
        draw.rectangle([m, m, w - m, h - m], outline=acc, width=max(2, int(h * 0.004)))
    return img


def draw_brand_mark(img: Image.Image) -> None:
    """Composite the subtle, always-present Flagpost mark along the bottom of the
    certificate (ADR-0027 branding — kept universal, but understated: a small flag
    + 'flagpost.io', not a band). Drawn over the content in an ink that adapts to
    the background luminance so it stays legible on any preset, colour, or upload."""
    w, h = img.width, img.height
    # Sit in the bottom margin, *below* any preset border frame (whose bottom edge
    # is at ~h - 0.035·w) so the mark never overlaps it. Ink adapts to the strip's
    # luminance so it stays legible on any preset, colour, or upload.
    cy = h - int(h * 0.028)
    strip = img.crop((0, cy - int(h * 0.02), w, h)).resize((24, 4)).convert("L")
    light_bg = (sum(strip.getdata()) / (24 * 4)) > 128
    ink = _hex_to_rgb(_C_INK if light_bg else _C_FG)
    alpha = 175  # clearly visible, still understated

    size = max(13, int(h * 0.019))
    font = load_font("sans", False, False, size)
    text = "flagpost.io"
    flag_box = size * 0.95
    gap = size * 0.34
    total = flag_box + gap + font.getlength(text)
    x = (w - total) / 2

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    _flag_mark(od, x, cy - flag_box * 0.5, flag_box, (*ink, alpha), (*ink, alpha), ground=False)
    od.text((x + flag_box + gap, cy), text, font=font, fill=(*ink, alpha), anchor="lm")
    img.paste(overlay, (0, 0), overlay)


def render_certificate_png(
    spec: Mapping,
    tokens: Mapping[str, str],
    *,
    background_bytes: bytes | None = None,
    image_bytes: Mapping[str, bytes] | None = None,
    font_bytes: Mapping[str, bytes] | None = None,
    branding: bool = True,
) -> bytes:
    """Composite a certificate PNG from ``spec`` (background config + elements)
    and resolved ``tokens``. ``background_bytes`` supplies an uploaded background;
    ``image_bytes`` maps an image element's key → its bytes; ``font_bytes`` maps a
    ``custom:<id>`` font ref → the uploaded TTF/OTF bytes."""
    image_bytes = image_bytes or {}
    font_bytes = font_bytes or {}
    font_cache: dict = {}  # per-render cache for custom fonts (bundled use lru_cache)
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (255, 255, 255))

    kind = spec.get("background_kind", "color")
    if kind == "upload" and background_bytes:
        bg = _safe_open(background_bytes)
        if bg is not None:
            canvas.paste(_cover(bg.convert("RGB"), CANVAS_W, CANVAS_H), (0, 0))
        else:
            canvas.paste(_hex_to_rgb(DEFAULT_COLOR), (0, 0, CANVAS_W, CANVAS_H))
    elif kind == "preset" and spec.get("background_preset"):
        canvas.paste(
            draw_preset_background(
                spec["background_preset"],
                CANVAS_W,
                CANVAS_H,
                accent=spec.get("preset_accent"),
                base=spec.get("preset_base"),
            ),
            (0, 0),
        )
    else:  # "color" (or a preset/upload that didn't resolve)
        color = spec.get("background_color") or DEFAULT_COLOR
        canvas.paste(_hex_to_rgb(color), (0, 0, CANVAS_W, CANVAS_H))

    draw = ImageDraw.Draw(canvas)
    for el in spec.get("elements", []):
        try:
            _draw_element(canvas, draw, el, tokens, image_bytes, font_bytes, font_cache)
        except Exception:
            # A single malformed element must never break the whole render, but
            # log it so a genuine renderer bug isn't invisible in the field.
            logger.debug("certificate element render failed: %r", el, exc_info=True)
            continue

    if branding:
        draw_brand_mark(canvas)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _safe_open(raw: bytes) -> Image.Image | None:
    """Open image bytes, rejecting a decompression bomb by checking the header
    dimensions *before* decoding. Returns the (un-decoded) image, or None if it
    can't be read or exceeds the source-pixel cap."""
    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > MAX_RENDER_SOURCE_PIXELS:
            logger.debug("certificate image rejected: %dx%d over cap", img.width, img.height)
            return None
        return img
    except Exception:
        return None


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale + centre-crop ``img`` to exactly cover ``w×h`` (CSS background-size:
    cover), so an uploaded background fills the canvas without distortion."""
    scale = max(w / img.width, h / img.height)
    resized = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
    left = (resized.width - w) // 2
    top = (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _draw_element(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    el: Mapping,
    tokens: Mapping[str, str],
    image_bytes: Mapping[str, bytes],
    font_bytes: Mapping[str, bytes],
    font_cache: dict,
) -> None:
    bx = el["x"] / 100 * CANVAS_W
    by = el["y"] / 100 * CANVAS_H
    bw = el.get("width", 40) / 100 * CANVAS_W
    etype = el.get("type")

    if etype == "image":
        raw = image_bytes.get(el.get("image_key", ""))
        if not raw:
            return
        opened = _safe_open(raw)
        if opened is None:
            return
        img = opened.convert("RGBA")
        # Clamp the drawn size to the canvas so an extreme aspect ratio can't
        # blow up the resize target (target_h grows with img.height/img.width).
        target_w = min(max(1, round(bw)), CANVAS_W)
        target_h = min(max(1, round(img.height * target_w / img.width)), CANVAS_H)
        img = img.resize((target_w, target_h))
        canvas.paste(img, (round(bx), round(by)), img)
        return

    # token / text
    if etype == "token":
        text = str(tokens.get(el.get("token", ""), ""))
    else:
        text = str(el.get("text", ""))
    if not text:
        return

    size_px = max(1, round(el.get("font_size", 6) / 100 * CANVAS_H))
    font = _resolve_font(
        el.get("font", "serif"),
        bool(el.get("bold")),
        bool(el.get("italic")),
        size_px,
        font_bytes,
        font_cache,
    )
    fill = _hex_to_rgb(el.get("color", "#111827"))
    align = el.get("align", "center")
    line_h = size_px * _LINE_HEIGHT
    y = by
    for line in _wrap(text, font, bw):
        line_w = draw.textlength(line, font=font)
        if align == "left":
            x = bx
        elif align == "right":
            x = bx + (bw - line_w)
        else:
            x = bx + (bw - line_w) / 2
        draw.text((x, y), line, font=font, fill=fill, anchor="la")
        y += line_h
