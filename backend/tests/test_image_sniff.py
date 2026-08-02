"""Magic-byte / structural sniffing (issues #80, #114).

`sniff_image_type` is the screenshot sniffer (PNG/JPEG/WebP only). `sniff_logo_type`
is the broader logo sniffer (adds GIF + structural SVG). These unit tests cover
the SVG structural check's edges, which the endpoint tests don't reach.
"""

from utils.image_sniff import sniff_image_type, sniff_logo_type

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6360000002000154a24f8f0000000049454e44ae426082"
)
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 8
_WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
_GIF = b"GIF89a" + b"\x00" * 8


def test_raster_magic_bytes():
    assert sniff_logo_type(_PNG) == "image/png"
    assert sniff_logo_type(_JPEG) == "image/jpeg"
    assert sniff_logo_type(_WEBP) == "image/webp"
    assert sniff_logo_type(b"GIF87a" + b"\x00" * 8) == "image/gif"
    assert sniff_logo_type(_GIF) == "image/gif"


def test_screenshot_sniffer_still_excludes_gif_and_svg():
    # The ticket-attachment contract must not change: GIF/SVG are not screenshots.
    assert sniff_image_type(_GIF) is None
    assert sniff_image_type(b"<svg xmlns='x'></svg>" + b" " * 12) is None


def test_svg_accepted_forms():
    forms = [
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"<svg/>",
        b"   \n  <svg>\n</svg>",  # leading whitespace
        b'<?xml version="1.0" encoding="UTF-8"?><svg></svg>',  # prolog
        b"\xef\xbb\xbf<svg></svg>",  # UTF-8 BOM
        b"<!-- a comment --><svg></svg>",  # leading comment
        b"<?xml version='1.0'?>\n<!-- hi -->\n<svg></svg>",  # prolog + comment
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd"><svg></svg>',
        b"<SVG></SVG>",  # case-insensitive tolerance
    ]
    for f in forms:
        assert sniff_logo_type(f) == "image/svg+xml", f


def test_svg_rejected_forms():
    rejected = [
        b"<script>alert(1)</script>",       # bare script, no svg root
        b"<html><body><svg></svg></body></html>",  # svg not the root element
        b"not xml at all",
        b"\x00\x01\x02\x03 binary",          # non-text
        b"\xff\xfe<\x00s\x00v\x00g\x00",     # UTF-16 (not valid utf-8)
        b"<?xml version='1.0'?>",            # prolog only, no root
        b"<svgfake></svgfake>",              # element name isn't exactly svg
        b"",                                  # empty
    ]
    for r in rejected:
        assert sniff_logo_type(r) is None, r


def test_svg_carrying_a_script_still_passes_the_structural_check():
    # Documented limitation: the structural check proves "is an SVG document",
    # not "is script-free". A well-formed <svg> with a <script> inside passes
    # here; the serve path's sandbox CSP is what contains it. This test pins that
    # behaviour so a future reader doesn't mistake it for a bug.
    payload = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    assert sniff_logo_type(payload) == "image/svg+xml"


def test_unrecognised_returns_none():
    assert sniff_logo_type(b"") is None
    assert sniff_logo_type(b"\x00\x00\x00\x00") is None
