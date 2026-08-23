"""Avatar upload processing: validate, then **re-encode** — never store what
was uploaded.

An avatar is attacker-supplied bytes rendered into every other user's page, so
the stored artifact must be one we produced, not one we accepted. The pipeline:

1. **Sniff** the real type from magic bytes (``utils/image_sniff``) — the
   client's ``Content-Type`` is a claim, not evidence. PNG/JPEG/WebP only;
   no SVG (a script-bearing document), no GIF (no animated avatars).
2. **Bound the decode** before it happens: the byte cap is enforced at the
   read (``read_upload_capped``), and the header-declared dimensions are
   checked against the pixel budget so a 1 MB flat-colour bomb can't expand
   to gigabytes of RGBA inside Pillow.
3. **Re-encode with Pillow** to a fixed-size square WebP: EXIF orientation is
   applied, then *all* metadata is dropped (GPS coordinates in a phone photo
   must never reach other competitors), polyglot payloads don't survive
   transcoding, and every stored avatar is a small known-shape file.

The result is what ``GET /api/users/{id}/avatar`` serves, byte-for-byte.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from utils.image_sniff import exceeds_pixel_budget, sniff_image_type

# Generous for a source photo, tiny next to the attachment cap; the stored
# re-encode is ~10-40 KB regardless of what comes in.
AVATAR_MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# Output edge length. 256px covers every rendered size (the shell shows 32px,
# profile ~96px) at 2x displays without shipping wallpaper-sized blobs.
AVATAR_SIZE = 256

AVATAR_CONTENT_TYPE = "image/webp"


class AvatarError(ValueError):
    """The upload isn't a usable avatar image; ``str(exc)`` is user-facing."""


def process_avatar(data: bytes) -> bytes:
    """Validate ``data`` and return the normalised square WebP to store.

    Raises :class:`AvatarError` with a user-facing message when the upload
    isn't an allowed image or can't be decoded.
    """
    kind = sniff_image_type(data)
    if kind is None:
        raise AvatarError("Upload a PNG, JPEG, or WebP image.")
    if exceeds_pixel_budget(data, kind):
        raise AvatarError("Image dimensions are too large.")

    try:
        with Image.open(io.BytesIO(data)) as img:
            # Photos carry their rotation in EXIF; bake it in before we strip
            # metadata, or portrait phone shots come out sideways.
            img = ImageOps.exif_transpose(img)
            # Flatten to a mode WebP encodes: keep alpha when present (PNG/WebP
            # logos), everything else to RGB.
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            # Centre-crop to square, then downscale.
            img = ImageOps.fit(
                img, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS
            )
            out = io.BytesIO()
            # ``save`` writes no EXIF unless asked — the re-encode *is* the
            # metadata strip.
            img.save(out, format="WEBP", quality=82, method=4)
            return out.getvalue()
    except AvatarError:
        raise
    except Exception as exc:  # truncated/corrupt file, decoder error
        raise AvatarError("That image can't be read — try a different file.") from exc
