"""Post-event report renderer (#134, ADR-0030).

Turns a report's aggregated data (``utils.report_data.build_report_data``) into the
two deliverables the feature ships: an HTML string and a PDF. One Jinja2 template
is *both* the HTML deliverable and the source WeasyPrint converts to PDF, so the
two can't diverge (ADR-0030). Charts are inline SVG (``plugins.reports.charts``),
so nothing here needs a browser or JavaScript.

Branding (platform name, accent, logo) is threaded from ``SiteSettings`` at render
time — unlike certificates, which hardcode the mark (ADR-0027). The un-removable
"Powered by Flagpost" footer is composited by the template into the running page
footer.

Security: Jinja2 autoescaping keeps user-supplied strings (team names, challenge
titles) from injecting into the document, and ``render_pdf`` passes WeasyPrint a
**restricted url_fetcher** that allows only ``data:`` URIs (the inlined logo) and
the bundled font files — every network fetch and every other local file is
refused, so report content can't trigger SSRF or a local-file read.

WeasyPrint is imported lazily inside ``render_pdf``, so importing this module (to
build the HTML deliverable, or under a test that never makes a PDF) doesn't
require WeasyPrint or its system libraries.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, unquote_to_bytes, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from plugins.reports import charts

_DIR = Path(__file__).resolve().parent
_TEMPLATES = _DIR / "templates"
_FONTS = _DIR / "assets" / "fonts"

# App-default accent, used when the operator hasn't set a brand colour.
_DEFAULT_ACCENT = "#2f4bd8"

# Only raster logos are inlined into a report. An SVG logo can carry active or
# external content, and the report — unlike the /logo HTTP endpoint — has no
# CSP/sandbox wrapper, so an SVG is deliberately dropped (the platform name still
# shows) rather than embedded.
_RASTER_LOGO_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

# Categorical palette for multi-segment charts (donut). The accent leads; the
# rest are fixed, print-legible hues distinct from it.
_SERIES = ["#0d9aa0", "#6b7fe8", "#c9a227", "#4a63e0", "#9aa1ad", "#e2725b", "#3aa76d"]

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _safe_color(value: Any) -> str:
    """The accent flows into CSS (``--accent``) and SVG attributes, so it must be a
    real hex colour and nothing else — otherwise an operator-set value could inject
    style/markup. Anything unexpected falls back to the app default."""
    return value if isinstance(value, str) and _HEX_COLOR.match(value) else _DEFAULT_ACCENT


# --- branding ---------------------------------------------------------------


async def fetch_branding(db: AsyncSession) -> dict[str, Any]:
    """Load the site branding a report inherits (§9, site-wide theming). The logo
    blob is ``deferred`` on the model, so undefer it; it's inlined as a data URI so
    the render stays self-contained (no external fetch)."""
    row = await db.scalar(
        select(SiteSettings)
        .where(SiteSettings.id == SITE_SETTINGS_ID)
        .options(undefer(SiteSettings.logo_data))
    )
    platform_name = (row.platform_name if row else None) or "Flagpost"
    accent = (row.accent if row else None) or _DEFAULT_ACCENT
    logo = None
    mime = (row.logo_content_type or "").lower() if row is not None else ""
    if row is not None and row.logo_data and mime in _RASTER_LOGO_MIMES:
        logo = f"data:{mime};base64,{base64.b64encode(row.logo_data).decode('ascii')}"
    return {"platform_name": platform_name, "accent": accent, "logo": logo}


# --- Jinja environment ------------------------------------------------------


def _fmt_duration(seconds: Any) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _fmt_datetime(value: Any) -> str:
    if not value:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    # Normalise to UTC before stamping the "UTC" label — a naive value is assumed
    # UTC; an aware non-UTC value is converted, so the shown time can't lie.
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.strftime("%b %d, %Y · %H:%M UTC")


def _fmt_date(value: Any) -> str:
    if not value:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return dt.strftime("%b %d, %Y")


def _pct(value: Any) -> str:
    return f"{round((value or 0) * 100)}%"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["duration"] = _fmt_duration
    env.filters["datetime"] = _fmt_datetime
    env.filters["date"] = _fmt_date
    env.filters["pct"] = _pct
    return env


def _build_svgs(data: dict[str, Any], accent: str) -> dict[str, str]:
    """Pre-render the section charts to SVG so the template just drops them in."""
    svgs: dict[str, str] = {}
    part = data.get("participation")
    if part:
        vel = part["solve_velocity"]
        svgs["velocity"] = charts.area(
            [d["date"][5:] for d in vel], [d["cumulative"] for d in vel], accent
        )
        svgs["heatmap"] = charts.heatmap(part["activity_by_hour"], accent)
    res = data.get("results")
    if res:
        svgs["score_hist"] = charts.histogram(
            [b["count"] for b in res["score_distribution"]], accent
        )
    ch = data.get("challenges")
    if ch and ch["category_rollup"]:
        roll = ch["category_rollup"]
        # Centre shows total solves — the same unit as the arcs and the heading.
        total = sum(r["solves"] for r in roll)
        svgs["category"] = charts.donut(
            [r["solves"] for r in roll], [accent, *_SERIES], str(total)
        )
    return svgs


# --- render -----------------------------------------------------------------


def render_html(
    data: dict[str, Any],
    branding: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> str:
    """Render the report to a self-contained HTML string (the HTML deliverable and
    the WeasyPrint source)."""
    accent = _safe_color(branding.get("accent"))
    template = _env().get_template("report.html")
    return template.render(
        data=data,
        meta=data.get("meta", {}),
        branding=branding,
        accent=accent,
        svg=_build_svgs(data, accent),
        # Colour the category legend to match the donut arcs.
        category_colors=[accent, *_SERIES],
        font_dir=_FONTS.as_uri(),
        generated_at=generated_at,
    )


def _url_fetcher(url: str):
    """Restricted fetcher (ADR-0030): only ``data:`` URIs (the inlined logo) and the
    bundled font files are served; every network fetch and every other local file
    is refused, so user-supplied report content can't trigger SSRF or a local-file
    read. Self-contained — decodes/reads the allowed resources itself and never
    reaches the network stack. Imports WeasyPrint's response type lazily (only PDF
    rendering ever calls this)."""
    from weasyprint.urls import URLFetcherResponse

    if url.startswith("data:"):
        header, _, payload = url[len("data:"):].partition(",")
        mime = header.split(";", 1)[0] or "application/octet-stream"
        data = base64.b64decode(payload) if ";base64" in header else unquote_to_bytes(payload)
        return URLFetcherResponse(url, body=data, headers={"Content-Type": mime})
    if url.startswith("file:"):
        path = Path(unquote(urlparse(url).path)).resolve()
        if (path == _FONTS or _FONTS in path.parents) and path.is_file():
            return URLFetcherResponse(
                url, body=path.read_bytes(), headers={"Content-Type": "font/ttf"}
            )
    raise ValueError(f"blocked report resource fetch: {url!r}")


def render_pdf(html: str) -> bytes:
    """Convert the report HTML to PDF bytes. Imports WeasyPrint lazily; CPU-bound,
    so callers run it off the request path (``asyncio.to_thread``)."""
    import weasyprint

    return weasyprint.HTML(
        string=html, base_url=str(_DIR), url_fetcher=_url_fetcher
    ).write_pdf()


def render_report(
    data: dict[str, Any],
    branding: dict[str, Any],
    *,
    generated_at: datetime | None = None,
    formats: tuple[str, ...] = ("html", "pdf"),
) -> dict[str, Any]:
    """Render the requested ``formats`` from one HTML pass — ``{"html": str,
    "pdf": bytes}`` (only the requested keys)."""
    html = render_html(data, branding, generated_at=generated_at)
    out: dict[str, Any] = {}
    if "html" in formats:
        out["html"] = html
    if "pdf" in formats:
        out["pdf"] = render_pdf(html)
    return out
