"""Certificate routes (#219, ADR-0027) — optional ``certificates`` module.

Four routers, all mounted by ``plugins.certificates.setup``:

- **competition-scoped** (``/api/competitions/{id}/certificates``): the organiser
  designer (template CRUD, background/image upload, real-renderer preview,
  manual release, bulk export) plus a participant's self-scoped availability +
  download. Every route calls :func:`_guard`, which 404s when the module is
  disabled for that competition (§11.3), the same pattern feedback/analytics use.
- **cross-competition self** (``/api/me/certificates``): a participant's released
  certificates across every competition (the durable Profile → Certificates
  home).
- **assets** (``/api/certificate-assets``): bundled fonts + code-drawn preset
  backgrounds + the editor manifest — unauthenticated, non-sensitive, same-origin
  so the editor's ``@font-face`` / ``<img>`` can load them under the app CSP.

Download scoping is by route shape: a participant can only fetch **their own**
certificate (``/me/download`` resolves the caller's own standing), never another
recipient's — no object id is ever accepted from the client.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import re
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from config import settings
from db import get_db, utcnow
from models.certificate import CertificateExportJob, CertificateFont, CertificateTemplate
from models.competition import Competition
from models.role import RoleAssignment
from models.team import TeamMembership
from models.user import User
from plugins.certificates.assets import (
    DEFAULT_FONT,
    FONT_IDS,
    MAX_ELEMENTS,
    MAX_IMAGE_ELEMENTS,
    PRESET_IDS,
    SAMPLE_TOKENS,
    build_manifest,
    font_path,
)
from plugins.certificates.render import draw_preset_background, render_certificate_png
from plugins.loader import is_module_enabled
from schemas.certificate import (
    CertificateAvailabilityOut,
    CertificateExportJobOut,
    CertificateFontOut,
    CertificateTemplateImport,
    CertificateTemplateOut,
    CertificateTemplateUpdate,
    MyCertificateOut,
)
from storage import get_storage
from storage.base import ObjectStorage
from utils.certificate_release import (
    CUSTOM_FONT_RE,
    custom_font_ids,
    gather_image_bytes,
    load_custom_font_bytes,
    release_template,
    resolve_one,
    spec_from_template,
)
from utils.event_bus import event_bus
from utils.font_sniff import FONT_CSS_FORMAT, sniff_font_format
from utils.image_sniff import exceeds_pixel_budget, image_dimensions, sniff_image_type
from utils.notifications import broadcast_notifications
from utils.uploads import read_upload_capped

MAX_CUSTOM_FONTS = 20
MAX_CERT_FONT_BYTES = 4 * 1024 * 1024

router = APIRouter(
    prefix="/api/competitions/{competition_id}/certificates", tags=["certificates"]
)
me_router = APIRouter(prefix="/api/me/certificates", tags=["certificates"])
assets_router = APIRouter(prefix="/api/certificate-assets", tags=["certificates"])

MAX_CERT_BG_BYTES = 8 * 1024 * 1024
MAX_CERT_IMAGE_BYTES = 2 * 1024 * 1024
_EXT_BY_TYPE = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


# --- shared helpers ---------------------------------------------------------


async def _guard(db: AsyncSession, competition_id: str) -> Competition:
    """The competition exists and the certificates module is on for it (§11.3)."""
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await is_module_enabled(db, "certificates", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The certificates module is disabled for this competition",
        )
    return competition


async def _get_template(db: AsyncSession, competition_id: str) -> CertificateTemplate | None:
    return await db.scalar(
        select(CertificateTemplate).where(
            CertificateTemplate.competition_id == competition_id
        )
    )


def _template_out(t: CertificateTemplate) -> CertificateTemplateOut:
    return CertificateTemplateOut(
        id=t.id,
        competition_id=t.competition_id,
        background_kind=t.background_kind,
        background_preset=t.background_preset,
        background_color=t.background_color,
        preset_accent=t.preset_accent,
        preset_base=t.preset_base,
        has_background_image=bool(t.background_object_key),
        elements=t.elements or [],
        recipient_rule=t.recipient_rule,
        release_mode=t.release_mode,
        release_delay_minutes=t.release_delay_minutes,
        released_at=t.released_at,
        released=t.released_at is not None,
    )


def _default_out(competition_id: str) -> CertificateTemplateOut:
    """A not-yet-saved template (id="") so the editor loads defaults; the first
    PUT/upload persists it."""
    return CertificateTemplateOut(
        id="",
        competition_id=competition_id,
        background_kind="color",
        background_preset=None,
        background_color="#ffffff",
        preset_accent=None,
        preset_base=None,
        has_background_image=False,
        elements=[],
        recipient_rule="all",
        release_mode="manual",
        release_delay_minutes=0,
        released_at=None,
        released=False,
    )


def _scope_prefix(competition_id: str) -> str:
    return f"{competition_id}/certificates/"


def _validate_image_keys(competition_id: str, elements: list) -> None:
    """Every image element's key must live under THIS competition's storage
    namespace (§6.2 tenancy at the storage layer). The key is client-supplied on
    PUT/preview, so without this a manager could composite another competition's
    object into a certificate."""
    prefix = _scope_prefix(competition_id)
    for el in elements:
        if el.get("type") == "image":
            key = el.get("image_key") or ""
            if not key.startswith(prefix):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="An image element references an out-of-scope key",
                )


async def _validate_font_refs(
    db: AsyncSession, competition_id: str, elements: list
) -> None:
    """Every ``custom:<id>`` font an element uses must be a font uploaded to THIS
    competition. The id is client-supplied on PUT/preview, so without this a
    manager could point a template at another competition's font (or a
    non-existent one). A referenced-but-deleted font would render as a default;
    rejecting here surfaces the mistake instead of silently swapping the type."""
    refs = custom_font_ids(elements)
    if not refs:
        return
    ids = [m.group(1) for f in refs if (m := CUSTOM_FONT_RE.match(f))]
    found = set(
        (
            await db.execute(
                select(CertificateFont.id).where(
                    CertificateFont.competition_id == competition_id,
                    CertificateFont.id.in_(ids),
                )
            )
        ).scalars().all()
    )
    if len(found) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An element references an unknown custom font",
        )


def _spec_from_body(body: CertificateTemplateUpdate) -> dict:
    return {
        "background_kind": body.background_kind,
        "background_preset": body.background_preset,
        "background_color": body.background_color,
        "preset_accent": body.preset_accent,
        "preset_base": body.preset_base,
        "elements": [e.model_dump() for e in body.elements],
    }


async def _render(
    spec: dict, tokens, storage: ObjectStorage, db: AsyncSession, competition_id: str
) -> bytes:
    """Resolve storage-backed bytes (background, image elements, custom fonts)
    then render off the event loop (CPU-bound)."""
    bg_bytes = None
    if spec.get("background_kind") == "upload" and spec.get("background_object_key"):
        try:
            bg_bytes = storage.get(spec["background_object_key"])
        except Exception:
            bg_bytes = None
    images = gather_image_bytes(storage, spec.get("elements", []), competition_id)
    fonts = await load_custom_font_bytes(db, storage, competition_id, spec.get("elements", []))
    return await asyncio.to_thread(
        render_certificate_png,
        spec,
        tokens,
        background_bytes=bg_bytes,
        image_bytes=images,
        font_bytes=fonts,
        branding=not settings.certificate_branding_removable,
    )


def _safe_filename(name: str) -> str:
    cleaned = name.replace('"', "").replace("\r", "").replace("\n", "").strip()
    return cleaned or "certificate.png"


# --- organiser: template + assets ------------------------------------------


@router.get("/template", response_model=CertificateTemplateOut)
async def get_template(
    competition_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
) -> CertificateTemplateOut:
    await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    return _template_out(t) if t else _default_out(competition_id)


@router.put("/template", response_model=CertificateTemplateOut)
async def put_template(
    competition_id: str,
    body: CertificateTemplateUpdate,
    current_user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
) -> CertificateTemplateOut:
    await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    if t is None:
        t = CertificateTemplate(competition_id=competition_id)
        db.add(t)
    if body.background_kind == "upload" and not t.background_object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a background image before selecting it",
        )
    elements = [e.model_dump() for e in body.elements]
    _validate_image_keys(competition_id, elements)
    await _validate_font_refs(db, competition_id, elements)
    t.background_kind = body.background_kind
    t.background_preset = body.background_preset
    t.background_color = body.background_color
    t.preset_accent = body.preset_accent
    t.preset_base = body.preset_base
    t.elements = elements
    t.recipient_rule = body.recipient_rule
    t.release_mode = body.release_mode
    t.release_delay_minutes = body.release_delay_minutes
    await db.commit()
    await event_bus.emit(
        "certificate.template_updated",
        {
            "competition_id": competition_id,
            "certificate_template_id": t.id,
            "user_id": current_user.id,
        },
    )
    return _template_out(t)


@router.post("/background", response_model=CertificateTemplateOut)
async def upload_background(
    competition_id: str,
    file: UploadFile,
    current_user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CertificateTemplateOut:
    await _guard(db, competition_id)
    data = await read_upload_capped(file, MAX_CERT_BG_BYTES)
    content_type = _validate_raster(data, landscape=True)
    key = (
        f"{competition_id}/certificates/backgrounds/"
        f"{uuid4().hex}.{_EXT_BY_TYPE.get(content_type, 'img')}"
    )
    storage.put(key, data, content_type)

    t = await _get_template(db, competition_id)
    if t is None:
        t = CertificateTemplate(competition_id=competition_id)
        db.add(t)
    old_key = t.background_object_key
    t.background_object_key = key
    t.background_kind = "upload"
    await db.commit()
    # Drop the superseded background so it doesn't orphan in storage.
    if old_key and old_key != key:
        try:
            storage.delete(old_key)
        except Exception:
            pass
    await event_bus.emit(
        "certificate.template_updated",
        {
            "competition_id": competition_id,
            "certificate_template_id": t.id,
            "user_id": current_user.id,
        },
    )
    return _template_out(t)


@router.post("/images")
async def upload_image(
    competition_id: str,
    file: UploadFile,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> dict[str, str]:
    """Upload an image element (signature / sponsor mark); returns its storage
    key to place on an ``image`` element via PUT /template."""
    await _guard(db, competition_id)
    data = await read_upload_capped(file, MAX_CERT_IMAGE_BYTES)
    content_type = _validate_raster(data, landscape=False)
    key = (
        f"{competition_id}/certificates/images/"
        f"{uuid4().hex}.{_EXT_BY_TYPE.get(content_type, 'img')}"
    )
    storage.put(key, data, content_type)
    return {"image_key": key}


@router.get("/media")
async def get_media(
    competition_id: str,
    key: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Stream a certificate image (background or element) for the editor canvas.
    Scoped to this competition's key prefix so it can't read another tenant's
    objects. Served with nosniff + a sandbox CSP, like ticket attachments."""
    await _guard(db, competition_id)
    if not key.startswith(f"{competition_id}/certificates/"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Out of scope")
    try:
        data = storage.get(key)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return Response(
        content=data,
        media_type=sniff_image_type(data) or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/background-image")
async def get_background_image(
    competition_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Stream the current uploaded background for the editor canvas — keyless, so
    the storage path never leaves the backend."""
    await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    if t is None or t.background_kind != "upload" or not t.background_object_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No background image")
    try:
        data = storage.get(t.background_object_key)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No background image")
    return Response(
        content=data,
        media_type=sniff_image_type(data) or "application/octet-stream",
        headers={
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


# --- organiser: custom fonts -----------------------------------------------


def _validate_font(data: bytes) -> str:
    """Shared font-upload hardening: non-empty, a TTF/OTF signature, and actually
    parseable by Pillow — a renamed or truncated file passes the magic check but
    fails to open, so the parse is the authoritative gate before bytes ever reach
    the render thread. Returns the format id (``"ttf"``/``"otf"``)."""
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    fmt = sniff_font_format(data)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Font must be a TrueType (.ttf) or OpenType (.otf) file",
        )
    from PIL import ImageFont

    try:
        ImageFont.truetype(io.BytesIO(data), 20)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Font file could not be read",
        )
    return fmt


def _font_label(name: str | None, filename: str | None) -> str:
    """A display label from the supplied name, else the filename with its
    extension stripped; bounded so it stays a tidy picker entry."""
    label = (name or (filename or "").rsplit("/", 1)[-1] or "").strip()
    label = re.sub(r"\.(ttf|otf|ttc|woff2?)$", "", label, flags=re.IGNORECASE).strip()
    return label[:80] or "Custom font"


def _font_out(f: CertificateFont) -> CertificateFontOut:
    return CertificateFontOut(id=f.id, name=f.name, format=f.format)


@router.get("/fonts", response_model=list[CertificateFontOut])
async def list_fonts(
    competition_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
) -> list[CertificateFontOut]:
    await _guard(db, competition_id)
    rows = (
        await db.execute(
            select(CertificateFont)
            .where(CertificateFont.competition_id == competition_id)
            .order_by(CertificateFont.created_at)
        )
    ).scalars().all()
    return [_font_out(f) for f in rows]


@router.post("/fonts", response_model=CertificateFontOut, status_code=status.HTTP_201_CREATED)
async def upload_font(
    competition_id: str,
    file: UploadFile,
    name: str | None = Form(default=None),
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CertificateFontOut:
    """Upload a proprietary/brand font (TTF/OTF) for this competition's
    certificates. The operator is responsible for holding a licence to use it —
    the font is stored only for this competition and never redistributed."""
    await _guard(db, competition_id)
    count = await db.scalar(
        select(func.count())
        .select_from(CertificateFont)
        .where(CertificateFont.competition_id == competition_id)
    )
    if count >= MAX_CUSTOM_FONTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {MAX_CUSTOM_FONTS} custom fonts per competition",
        )
    data = await read_upload_capped(file, MAX_CERT_FONT_BYTES)
    fmt = _validate_font(data)
    fid = str(uuid4())
    key = f"{competition_id}/certificates/fonts/{fid}.{fmt}"
    storage.put(key, data, f"font/{fmt}")
    row = CertificateFont(
        id=fid,
        competition_id=competition_id,
        name=_font_label(name, file.filename),
        object_key=key,
        format=fmt,
    )
    db.add(row)
    await db.commit()
    return _font_out(row)


@router.delete("/fonts/{font_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_font(
    competition_id: str,
    font_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Delete a custom font. Any element still referencing it falls back to a
    bundled default at render (the ref is resolved, not embedded), so this never
    breaks an existing design — it just changes the type."""
    await _guard(db, competition_id)
    row = await db.get(CertificateFont, font_id)
    if row is None or row.competition_id != competition_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Font not found")
    key = row.object_key
    await db.delete(row)
    await db.commit()
    try:
        storage.delete(key)
    except Exception:
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/fonts/{font_id}/file")
async def get_font_file(
    competition_id: str,
    font_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Stream a custom font's bytes for the editor's @font-face (fetched as an
    auth'd blob, like element images), so the canvas previews the same font the
    server renders with. Scoped to this competition's own rows."""
    await _guard(db, competition_id)
    row = await db.get(CertificateFont, font_id)
    if row is None or row.competition_id != competition_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Font not found")
    try:
        data = storage.get(row.object_key)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Font not found")
    return Response(
        content=data,
        media_type=f"font/{row.format}",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/preview")
async def preview(
    competition_id: str,
    body: CertificateTemplateUpdate,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Render the in-progress design with sample tokens through the *real*
    renderer (ADR-0027 parity), so the preview equals the downloaded PNG."""
    await _guard(db, competition_id)
    spec = _spec_from_body(body)
    _validate_image_keys(competition_id, spec["elements"])
    await _validate_font_refs(db, competition_id, spec["elements"])
    if body.background_kind == "upload":
        t = await _get_template(db, competition_id)
        spec["background_object_key"] = t.background_object_key if t else None
    png = await _render(spec, SAMPLE_TOKENS, storage, db, competition_id)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


# --- organiser: template export / import -----------------------------------
# A self-contained, portable design: the JSON carries the layout *and* every
# referenced binary (uploaded background, image elements, custom fonts) as
# base64, so a company can save a certificate one year and re-import it into a
# brand-new instance the next — assets and all. Import re-uploads the assets into
# the target competition and rewrites the references, then runs the design
# through the normal template hardening.

EXPORT_VERSION = 1


def _embed_asset(storage: ObjectStorage, key: str) -> dict | None:
    """Fetch a stored image and encode it for the export doc, or None if it can't
    be read / isn't a recognised raster."""
    try:
        data = storage.get(key)
    except Exception:
        return None
    ctype = sniff_image_type(data)
    if ctype is None:
        return None
    return {"format": _EXT_BY_TYPE.get(ctype, "img"), "data": base64.b64encode(data).decode()}


async def _build_export_doc(
    db: AsyncSession, storage: ObjectStorage, t: CertificateTemplate
) -> dict:
    elements = t.elements or []
    assets: dict = {"background_image": None, "images": {}, "fonts": {}}

    if t.background_kind == "upload" and t.background_object_key:
        assets["background_image"] = _embed_asset(storage, t.background_object_key)
    for key, data in gather_image_bytes(storage, elements, t.competition_id).items():
        ctype = sniff_image_type(data) or ""
        assets["images"][key] = {
            "format": _EXT_BY_TYPE.get(ctype, "img"),
            "data": base64.b64encode(data).decode(),
        }

    font_bytes = await load_custom_font_bytes(db, storage, t.competition_id, elements)
    if font_bytes:
        ids = [ref.split("custom:", 1)[1] for ref in font_bytes]
        rows = {
            r.id: r
            for r in (
                await db.execute(
                    select(CertificateFont).where(
                        CertificateFont.competition_id == t.competition_id,
                        CertificateFont.id.in_(ids),
                    )
                )
            ).scalars().all()
        }
        for ref, data in font_bytes.items():
            row = rows.get(ref.split("custom:", 1)[1])
            assets["fonts"][ref] = {
                "name": row.name if row else "Custom font",
                "format": row.format if row else "ttf",
                "data": base64.b64encode(data).decode(),
            }

    return {
        "flagpost_certificate_template": EXPORT_VERSION,
        "exported_at": utcnow().isoformat(),
        "template": {
            "background_kind": t.background_kind,
            "background_preset": t.background_preset,
            "background_color": t.background_color,
            "preset_accent": t.preset_accent,
            "preset_base": t.preset_base,
            "recipient_rule": t.recipient_rule,
            "release_mode": t.release_mode,
            "release_delay_minutes": t.release_delay_minutes,
            "elements": elements,
        },
        "assets": assets,
    }


@router.get("/template/export")
async def export_template(
    competition_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Download the current design as a portable, self-contained JSON document."""
    await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No certificate has been configured for this competition",
        )
    doc = await _build_export_doc(db, storage, t)
    return Response(
        content=json.dumps(doc).encode(),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="certificate-template.json"',
            "Cache-Control": "no-store",
        },
    )


def _decode_asset(b64: str, cap: int) -> bytes:
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An embedded asset is not valid base64",
        )
    if len(raw) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="An embedded asset is empty"
        )
    if len(raw) > cap:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="An embedded asset exceeds its size limit",
        )
    return raw


async def _apply_import(
    db: AsyncSession, storage: ObjectStorage, competition_id: str, doc: CertificateTemplateImport
) -> CertificateTemplate:
    if doc.flagpost_certificate_template != EXPORT_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported template file version",
        )
    tmpl = doc.template
    assets = doc.assets
    raw_elements = tmpl.get("elements") if isinstance(tmpl, dict) else None
    raw_elements = raw_elements if isinstance(raw_elements, list) else []
    if len(raw_elements) > MAX_ELEMENTS or len(assets.images) > MAX_IMAGE_ELEMENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Imported template is too large"
        )
    if len(assets.fonts) > MAX_CUSTOM_FONTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Too many embedded fonts"
        )

    # --- Pass 1: decode + validate every asset BEFORE any storage/DB write, so a
    # malformed file fails cleanly without leaving orphaned objects behind. ---
    writes: list[tuple[str, bytes, str]] = []  # (key, bytes, content_type)

    bg_new_key: str | None = None
    if assets.background_image is not None:
        raw = _decode_asset(assets.background_image.data, MAX_CERT_BG_BYTES)
        ctype = _validate_raster(raw, landscape=True)
        bg_new_key = f"{competition_id}/certificates/backgrounds/{uuid4().hex}.{_EXT_BY_TYPE.get(ctype, 'img')}"
        writes.append((bg_new_key, raw, ctype))

    image_map: dict[str, str] = {}
    for old_key, asset in assets.images.items():
        raw = _decode_asset(asset.data, MAX_CERT_IMAGE_BYTES)
        ctype = _validate_raster(raw, landscape=False)
        new_key = f"{competition_id}/certificates/images/{uuid4().hex}.{_EXT_BY_TYPE.get(ctype, 'img')}"
        image_map[old_key] = new_key
        writes.append((new_key, raw, ctype))

    # Validate every embedded font (a malformed doc is rejected), but only
    # materialise the ones an element actually references — an unreferenced font
    # would otherwise create an orphan row/object that counts against the cap.
    referenced_fonts = custom_font_ids(raw_elements)
    font_map: dict[str, str] = {}
    font_rows: list[CertificateFont] = []
    for old_ref, asset in assets.fonts.items():
        raw = _decode_asset(asset.data, MAX_CERT_FONT_BYTES)
        fmt = _validate_font(raw)
        if old_ref not in referenced_fonts:
            continue
        fid = str(uuid4())
        new_key = f"{competition_id}/certificates/fonts/{fid}.{fmt}"
        font_map[old_ref] = f"custom:{fid}"
        font_rows.append(
            CertificateFont(
                id=fid,
                competition_id=competition_id,
                name=_font_label(asset.name, None),
                object_key=new_key,
                format=fmt,
            )
        )
        writes.append((new_key, raw, f"font/{fmt}"))

    # --- Rewrite element refs to the new in-scope keys. An image element whose
    # bytes weren't bundled can't be ported → drop it; a missing custom font
    # degrades to the bundled default. ---
    new_elements: list[dict] = []
    for el in raw_elements:
        if not isinstance(el, dict):
            continue
        el = dict(el)
        if el.get("type") == "image":
            mapped = image_map.get(el.get("image_key"))
            if mapped is None:
                continue
            el["image_key"] = mapped
        else:
            font = el.get("font")
            if isinstance(font, str) and font.startswith("custom:"):
                el["font"] = font_map.get(font, DEFAULT_FONT)
        new_elements.append(el)

    kind = tmpl.get("background_kind", "color")
    if kind == "upload" and bg_new_key is None:
        kind = "color"  # background wasn't bundled → fall back to a plain colour

    # --- Validate the rewritten design through the normal template hardening. ---
    try:
        parsed = CertificateTemplateUpdate(
            background_kind=kind,
            background_preset=tmpl.get("background_preset"),
            background_color=tmpl.get("background_color", "#ffffff"),
            preset_accent=tmpl.get("preset_accent"),
            preset_base=tmpl.get("preset_base"),
            elements=new_elements,
            recipient_rule=tmpl.get("recipient_rule", "all"),
            release_mode=tmpl.get("release_mode", "manual"),
            release_delay_minutes=tmpl.get("release_delay_minutes", 0),
        )
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The imported template is not valid",
        )
    persisted_elements = [e.model_dump() for e in parsed.elements]
    _validate_image_keys(competition_id, persisted_elements)

    # Import replaces the whole design, so the competition's existing custom fonts
    # (which belonged to the replaced design) are superseded — collect them to drop
    # after the commit, so they neither orphan nor count against the per-competition
    # cap on a re-import.
    existing_fonts = (
        await db.execute(
            select(CertificateFont).where(CertificateFont.competition_id == competition_id)
        )
    ).scalars().all()
    old_font_keys = [f.object_key for f in existing_fonts]

    # --- Persist: storage writes, then font rows + the (upserted) template in one
    # commit. Replaces the design only — release state is left untouched. ---
    for key, data, ctype in writes:
        storage.put(key, data, ctype)
    for f in existing_fonts:
        await db.delete(f)
    for row in font_rows:
        db.add(row)

    t = await _get_template(db, competition_id)
    old_bg_key = t.background_object_key if t else None
    if t is None:
        t = CertificateTemplate(competition_id=competition_id)
        db.add(t)
    t.background_kind = parsed.background_kind
    t.background_preset = parsed.background_preset
    t.background_color = parsed.background_color
    t.preset_accent = parsed.preset_accent
    t.preset_base = parsed.preset_base
    t.recipient_rule = parsed.recipient_rule
    t.release_mode = parsed.release_mode
    t.release_delay_minutes = parsed.release_delay_minutes
    t.elements = persisted_elements
    # Keep the uploaded-background reference only when the imported design is an
    # upload; otherwise clear it so a stale/replaced key can't linger on the row.
    t.background_object_key = bg_new_key if parsed.background_kind == "upload" else None
    try:
        await db.commit()
    except Exception:
        # The DB didn't durably record the import → don't leave the freshly written
        # objects orphaned in storage.
        for key, _data, _ctype in writes:
            try:
                storage.delete(key)
            except Exception:
                pass
        raise
    # Post-commit: drop superseded objects (the replaced design's fonts + a
    # replaced/removed background).
    for key in old_font_keys:
        try:
            storage.delete(key)
        except Exception:
            pass
    if old_bg_key and old_bg_key != bg_new_key:
        try:
            storage.delete(old_bg_key)
        except Exception:
            pass
    return t


@router.post("/template/import", response_model=CertificateTemplateOut)
async def import_template(
    competition_id: str,
    body: CertificateTemplateImport,
    current_user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CertificateTemplateOut:
    """Replace the current design with a previously-exported one (re-uploading its
    embedded assets). Release state is preserved; the design is fully re-validated."""
    await _guard(db, competition_id)
    t = await _apply_import(db, storage, competition_id, body)
    await event_bus.emit(
        "certificate.template_updated",
        {
            "competition_id": competition_id,
            "certificate_template_id": t.id,
            "user_id": current_user.id,
        },
    )
    return _template_out(t)


# --- organiser: release + bulk export --------------------------------------


@router.post("/release", response_model=CertificateTemplateOut)
async def release_now(
    competition_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
) -> CertificateTemplateOut:
    competition = await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No certificate has been configured for this competition",
        )
    if t.released_at is not None:
        return _template_out(t)  # already released — idempotent, no re-notify
    made = await release_template(db, competition, t)
    if made is None:
        # A concurrent caller won the atomic release; reflect their state.
        await db.refresh(t)
        return _template_out(t)
    await db.commit()
    await broadcast_notifications(made)
    await event_bus.emit(
        "certificate.released",
        {"competition_id": competition_id, "certificate_template_id": t.id},
    )
    return _template_out(t)


@router.post("/exports", response_model=CertificateExportJobOut, status_code=status.HTTP_201_CREATED)
async def create_export(
    competition_id: str,
    current_user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
) -> CertificateExportJobOut:
    await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No certificate has been configured for this competition",
        )
    job = CertificateExportJob(
        competition_id=competition_id, requested_by=current_user.id, status="pending"
    )
    db.add(job)
    await db.commit()
    return CertificateExportJobOut.model_validate(job)


@router.get("/exports/{job_id}", response_model=CertificateExportJobOut)
async def get_export(
    competition_id: str,
    job_id: str,
    _user: User = Depends(require_permission("manage_certificates")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CertificateExportJobOut:
    await _guard(db, competition_id)
    job = await db.get(CertificateExportJob, job_id)
    if job is None or job.competition_id != competition_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    out = CertificateExportJobOut.model_validate(job)
    if job.status == "done" and job.object_key:
        out.download_url = storage.presigned_get_url(
            job.object_key,
            settings.signed_url_ttl_seconds,
            response_headers={
                "response-content-type": "application/zip",
                "response-content-disposition": 'attachment; filename="certificates.zip"',
            },
        )
    return out


# --- participant: self-scoped availability + download ----------------------


@router.get("/me", response_model=CertificateAvailabilityOut)
async def my_availability(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CertificateAvailabilityOut:
    competition = await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    if t is None or t.released_at is None:
        return CertificateAvailabilityOut(available=False)
    rec = await resolve_one(db, competition, t, current_user)
    if rec is None:
        return CertificateAvailabilityOut(available=False)
    return CertificateAvailabilityOut(
        available=True, released_at=t.released_at, competition_name=competition.name
    )


@router.get("/me/download")
async def my_download(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    competition = await _guard(db, competition_id)
    t = await _get_template(db, competition_id)
    if t is None or t.released_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No certificate is available yet",
        )
    rec = await resolve_one(db, competition, t, current_user)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You don't have a certificate for this competition",
        )
    png = await _render(spec_from_template(t), rec.tokens, storage, db, competition_id)
    filename = _safe_filename(f"certificate-{competition.name}.png")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- cross-competition self list -------------------------------------------


@me_router.get("", response_model=list[MyCertificateOut])
async def my_certificates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MyCertificateOut]:
    """Every released certificate this user can download, across competitions —
    the durable Profile → Certificates home (survives archive)."""
    templates = (
        await db.execute(
            select(CertificateTemplate)
            .where(CertificateTemplate.released_at.is_not(None))
            .order_by(CertificateTemplate.released_at.desc())
        )
    ).scalars().all()
    # Pre-filter to competitions the user actually belongs to, so the heavy
    # per-template standings computation (resolve_one → compute_scoreboard) runs
    # only for the user's own competitions, not every released template on the
    # platform.
    member_comp_ids = set(
        (
            await db.execute(
                select(RoleAssignment.competition_id).where(
                    RoleAssignment.user_id == current_user.id,
                    RoleAssignment.competition_id.is_not(None),
                )
            )
        ).scalars().all()
    ) | set(
        (
            await db.execute(
                select(TeamMembership.competition_id).where(
                    TeamMembership.user_id == current_user.id
                )
            )
        ).scalars().all()
    )
    out: list[MyCertificateOut] = []
    for t in templates:
        if t.competition_id not in member_comp_ids:
            continue
        if not await is_module_enabled(db, "certificates", t.competition_id):
            continue
        competition = await db.get(Competition, t.competition_id)
        if competition is None:
            continue
        rec = await resolve_one(db, competition, t, current_user)
        if rec is None:
            continue
        out.append(
            MyCertificateOut(
                competition_id=competition.id,
                competition_name=competition.name,
                released_at=t.released_at,
            )
        )
    return out


# --- bundled assets (unauthenticated, non-sensitive) -----------------------

_FONT_VARIANTS = {
    "regular": (False, False),
    "bold": (True, False),
    "italic": (False, True),
    "bolditalic": (True, True),
}


@assets_router.get("/manifest")
async def manifest() -> dict:
    return build_manifest()


@assets_router.get("/fonts/{family}/{variant}")
async def font_file(family: str, variant: str) -> Response:
    if family not in FONT_IDS or variant not in _FONT_VARIANTS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown font")
    bold, italic = _FONT_VARIANTS[variant]
    data = font_path(family, bold=bold, italic=italic).read_bytes()
    return Response(
        content=data,
        media_type="font/ttf",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            # Public, non-sensitive font — allow the editor's @font-face to load
            # it cross-origin in dev (frontend :3000 → backend :8000) so the
            # canvas matches the render. Same-origin in production (Caddy).
            "Access-Control-Allow-Origin": "*",
        },
    )


_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex_or_none(v: str | None) -> str | None:
    return v if v and _HEX6.match(v) else None


@assets_router.get("/backgrounds/{preset_id}")
async def preset_background(
    preset_id: str, accent: str | None = None, base: str | None = None
) -> Response:
    if preset_id not in PRESET_IDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown preset")
    # Optional accent/base colour overrides (ignored unless a valid 6-digit hex),
    # so the editor can preview a preset in custom colours. Same code path as render.
    img = await asyncio.to_thread(
        draw_preset_background, preset_id, 1240, 877, _hex_or_none(accent), _hex_or_none(base)
    )
    buf = io.BytesIO()
    await asyncio.to_thread(img.save, buf, "PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _validate_raster(data: bytes, *, landscape: bool) -> str:
    """Shared upload hardening: non-empty, magic-byte PNG/JPEG/WebP, within the
    pixel budget, and (for backgrounds) a landscape A4-ish aspect."""
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    content_type = sniff_image_type(data)
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Image must be a PNG, JPEG, or WebP",
        )
    if exceeds_pixel_budget(data, content_type):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image dimensions are too large",
        )
    if landscape:
        dims = image_dimensions(data, content_type)
        if dims:
            w, h = dims
            if h <= 0 or w <= h or not (1.2 <= w / h <= 1.7):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Background must be a landscape, roughly A4-proportioned image",
                )
    return content_type
