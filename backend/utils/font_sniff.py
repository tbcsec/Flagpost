"""Magic-byte sniffing for uploaded certificate fonts (#219).

Same philosophy as :mod:`utils.image_sniff`: a browser-supplied ``Content-Type``
is a claim, not evidence, so we **derive** the format from the file's own
signature and keep only that. We accept the two bare desktop font containers a
company's brand typeface actually ships as — TrueType (``.ttf``) and OpenType
(``.otf``) — and reject the web-only wrappers (WOFF/WOFF2) and TrueType
collections, which Pillow's FreeType binding can't be relied on to load by a
plain path/handle.

The signature check is cheap and structural; the *authoritative* validation is
the caller actually parsing the bytes with Pillow at upload time (a renamed or
truncated file passes the magic check but fails to open), so a bad font is
rejected at the boundary and never reaches the render thread.
"""

from __future__ import annotations

# id → CSS ``format()`` hint used by the editor's @font-face so the browser
# preview loads the same bytes the server renders with (ADR-0027 parity).
FONT_CSS_FORMAT = {"ttf": "truetype", "otf": "opentype"}


def sniff_font_format(data: bytes) -> str | None:
    """Return ``"ttf"``/``"otf"`` if ``data`` is a bare TrueType/OpenType font,
    else ``None``. TrueType-outline OpenType is ``\\x00\\x01\\x00\\x00`` (same as
    TTF); CFF-outline OpenType is ``OTTO``; ``true`` is the legacy Mac TrueType
    tag. WOFF/WOFF2 (``wOFF``/``wOF2``) and collections (``ttcf``) are refused."""
    if len(data) < 4:
        return None
    sig = data[:4]
    if sig in (b"\x00\x01\x00\x00", b"true"):
        return "ttf"
    if sig == b"OTTO":
        return "otf"
    return None
