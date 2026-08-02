"""Magic-byte image sniffing for uploaded ticket attachments (issue #80).

A browser-supplied ``Content-Type`` is a *claim*, not evidence — anything can be
labelled ``image/png``. So rather than validate the claim, we **derive** the
type from the leading bytes and store that; the client's header is discarded.
What we serve back is then always what the file actually is, which is what makes
the ``nosniff`` header on the download path meaningful.

Deliberately narrow: the three still-image formats a screenshot arrives as. No
GIF (animation isn't a screenshot) and no SVG (it's a script-bearing document,
not an image) — the owner's call on issue #80.

**Dimensions are checked too, not just the byte count.** A byte-size cap alone
doesn't bound the cost of *viewing* an image: a 20000x20000 PNG of flat colour
compresses to about 1 MB but decodes to ~1.5 GB of RGBA in the viewer's browser.
Ticket thumbnails render as soon as staff open a thread, so an attachment like
that would be a one-click memory bomb aimed at the support queue. We therefore
read the dimensions out of each format's header and refuse anything beyond a
generous screenshot budget. Nothing is decoded server-side — this is header
arithmetic, so it can't itself be turned into a decode bomb.
"""

from __future__ import annotations

import re
import struct

# Longest prefix we need is WebP's 12 bytes ("RIFF" + size + "WEBP").
_SNIFF_BYTES = 12

# ~40 megapixels: far above any real screenshot (a 4K grab is 8.3 MP, a long
# scrolling phone capture ~18 MP) while refusing the 400 MP flat-colour bombs
# that fit comfortably under the byte cap.
MAX_IMAGE_PIXELS = 40_000_000


def sniff_image_type(data: bytes) -> str | None:
    """Return the image MIME type ``data`` actually is, or ``None`` if it isn't
    one of the three allowed still-image formats."""
    if len(data) < _SNIFF_BYTES:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # JPEG: SOI marker. The trailing \xff starts the next marker, which is
    # \xe0/\xe1/\xdb/… depending on the encoder, so don't over-constrain it.
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # WebP is a RIFF container: "RIFF" <4-byte little-endian size> "WEBP".
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# A single leading XML prolog, DOCTYPE, or comment — peeled off (repeatedly, in
# any order) before we check that the first real element is the SVG root.
_SVG_SKIP = re.compile(
    r"^\s*(?:"
    r"<\?xml\b[^>]*\?>"                      # <?xml ... ?>
    r"|<!DOCTYPE\b[^>[]*(?:\[[^\]]*\])?\s*>"  # DOCTYPE, optional internal subset
    r"|<!--.*?-->"                            # comment
    r")",
    re.IGNORECASE | re.DOTALL,
)
_SVG_ROOT = re.compile(r"^\s*<svg[\s/>]", re.IGNORECASE)


def _looks_like_svg(data: bytes) -> bool:
    """Whether ``data`` is structurally an SVG document.

    SVG has no magic bytes — it's XML text — so "magic-byte" validation means a
    structural one: the payload must decode as UTF-8 and its first element,
    after any BOM / XML prolog / DOCTYPE / comments, must be the ``<svg>`` root.
    That's enough to reject a renamed binary or a bare script masquerading as a
    logo. It does **not** try to prove the SVG is script-free — an ``<svg>`` that
    also carries a ``<script>`` still passes here; that residual risk is
    contained on the serve path, which returns the logo under a sandboxed,
    ``nosniff`` CSP (see routers/site_settings read_logo). Parsing is avoided
    entirely (regex, not an XML parser), so this can't be turned into an
    entity-expansion bomb.
    """
    try:
        text = data.decode("utf-8-sig")  # -sig strips a leading BOM if present
    except UnicodeDecodeError:
        return False
    prev = None
    while prev != text:  # peel prolog / doctype / comments, in any order
        prev = text
        text = _SVG_SKIP.sub("", text, count=1)
    return _SVG_ROOT.match(text) is not None


def sniff_logo_type(data: bytes) -> str | None:
    """The image type a **logo** upload actually is, or ``None`` if unrecognised.

    Broader than :func:`sniff_image_type` (which is screenshot-only): a logo may
    also be a GIF or an SVG. Raster formats are identified by magic bytes; SVG,
    having none, is validated structurally. The client's ``Content-Type`` is
    never consulted — this result is the authoritative type, stored and served.
    """
    raster = sniff_image_type(data)  # PNG / JPEG / WebP
    if raster is not None:
        return raster
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if _looks_like_svg(data):
        return "image/svg+xml"
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    # IHDR is mandated to be the first chunk: 8-byte signature, 4-byte length,
    # 4-byte "IHDR", then width and height as big-endian uint32.
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    # Walk the marker segments to the start-of-frame, which carries the size.
    # SOF0-SOF15 are 0xC0-0xCF except the huffman/arithmetic/restart markers.
    i = 2
    end = len(data)
    while i + 3 < end:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        # Padding fill bytes between segments are legal.
        if marker == 0xFF:
            i += 1
            continue
        # Standalone markers carry no length payload.
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if length < 2:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > end:
                return None
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X":  # extended: 24-bit canvas size, stored minus one
        if len(data) < 30:
            return None
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    if chunk == b"VP8 ":  # lossy: 14-bit dimensions in the frame header
        if len(data) < 30:
            return None
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return w, h
    if chunk == b"VP8L":  # lossless: 14-bit each, packed, stored minus one
        if len(data) < 25:
            return None
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def image_dimensions(data: bytes, content_type: str) -> tuple[int, int] | None:
    """Read (width, height) out of the header, or ``None`` if unreadable."""
    try:
        if content_type == "image/png":
            return _png_dimensions(data)
        if content_type == "image/jpeg":
            return _jpeg_dimensions(data)
        if content_type == "image/webp":
            return _webp_dimensions(data)
    except (struct.error, IndexError):
        return None
    return None


def exceeds_pixel_budget(data: bytes, content_type: str) -> bool:
    """True if the image is too large to be safely decoded by a viewer.

    Unreadable dimensions are treated as **safe** rather than rejected: the
    bytes already passed the magic-byte check, and a header this parser can't
    follow is far more likely to be an unusual-but-valid encoder than an attack
    (the attack needs *large declared dimensions*, which means a header we can
    read). Failing closed here would reject legitimate uploads.
    """
    size = image_dimensions(data, content_type)
    if size is None:
        return False
    width, height = size
    if width <= 0 or height <= 0:
        return True
    return width * height > MAX_IMAGE_PIXELS
