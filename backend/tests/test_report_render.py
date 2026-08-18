"""Post-event report renderer (#134, ADR-0030, Stage 3).

Exercises the full render path — build_report_data → fetch_branding → HTML → PDF —
plus the two security properties: user-supplied strings are autoescaped, and the
inherited branding (platform name, accent, "Powered by Flagpost" footer) is
present. The PDF assertion needs WeasyPrint + its system libs, so it skips where
those aren't installed (the report image stage adds them).
"""

import pytest

# WeasyPrint raises OSError (not ImportError) when its system libraries are
# absent, so importorskip() isn't enough — detect availability robustly. The
# report ops stage adds the libs to the image; until then the PDF path skips.
try:
    import weasyprint  # noqa: F401

    _WEASYPRINT = True
except Exception:  # pragma: no cover
    _WEASYPRINT = False

from db import SessionLocal
from models.challenge import Challenge
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from plugins.reports import render
from utils.report_data import SECTIONS, build_report_data
from tests.test_report_data import (
    _challenge,
    _competition,
    _load,
    _participant,
    _submit,
)


async def _brand(platform_name: str, accent: str) -> None:
    async with SessionLocal() as db:
        settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if settings is None:
            settings = SiteSettings(id=SITE_SETTINGS_ID)
            db.add(settings)
        settings.platform_name = platform_name
        settings.accent = accent
        await db.commit()


async def test_render_pipeline_html_and_pdf(client):
    comp = await _competition(client)
    easy = await _challenge(client, comp, "Easy Web", 100, "flag{a}")
    ada = await _participant(client, comp, "ada@example.com")
    await _participant(client, comp, "bob@example.com")
    assert await _submit(client, comp, easy, ada, "flag{a}") is True
    await _brand("Acme CTF Platform", "#0d9aa0")

    competition = await _load(comp)
    async with SessionLocal() as db:
        data = await build_report_data(db, competition, sections=list(SECTIONS))
        branding = await render.fetch_branding(db)

    assert branding["platform_name"] == "Acme CTF Platform"
    assert branding["accent"] == "#0d9aa0"

    html = render.render_html(data, branding)
    assert "Acme CTF Platform" in html          # inherited platform name
    assert "--accent: #0d9aa0" in html          # inherited accent threaded to CSS
    assert "Easy Web" in html                    # real challenge data rendered
    assert "Powered by Flagpost" in html         # the un-removable footer mark
    assert "Executive summary" in html           # a section rendered

    # PDF conversion needs WeasyPrint + system libs (added in the report ops stage).
    if _WEASYPRINT:
        pdf = render.render_pdf(html)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000


async def test_render_escapes_user_content(client):
    """A challenge title carrying markup must be escaped, not injected into the
    document (Jinja autoescape) — the reason the renderer uses a template engine."""
    comp = await _competition(client)
    chal = await _challenge(client, comp, "placeholder", 100, "flag{a}")
    async with SessionLocal() as db:
        challenge = await db.get(Challenge, chal)
        challenge.title = "<script>alert(1)</script>"
        await db.commit()

    competition = await _load(comp)
    async with SessionLocal() as db:
        data = await build_report_data(db, competition, sections=["challenges"])
        branding = await render.fetch_branding(db)
    html = render.render_html(data, branding)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_donut_covers_all_categories():
    """More categories than palette colours still draws an arc per category —
    colours cycle (regression: zip() dropped every category past the 8th)."""
    from plugins.reports import charts

    values = [30, 25, 20, 18, 15, 12, 10, 8, 5]  # 9 categories
    colors = [f"#{i}{i}{i}" for i in range(1, 9)]  # 8 colours
    svg = charts.donut(values, colors, str(sum(values)))
    assert svg.count("<circle") == 9


async def test_svg_logo_is_dropped_raster_kept(client):
    """An SVG logo is not embedded in the report (no CSP wrapper there); a raster
    logo is inlined as a data URI."""
    async with SessionLocal() as db:
        settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if settings is None:
            settings = SiteSettings(id=SITE_SETTINGS_ID)
            db.add(settings)
        settings.logo_data = b"<svg xmlns='http://www.w3.org/2000/svg'><image href='file:///etc/passwd'/></svg>"
        settings.logo_content_type = "image/svg+xml"
        await db.commit()
    async with SessionLocal() as db:
        assert (await render.fetch_branding(db))["logo"] is None

    async with SessionLocal() as db:
        settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
        settings.logo_data = b"\x89PNG\r\n\x1a\n" + b"0" * 40
        settings.logo_content_type = "image/png"
        await db.commit()
    async with SessionLocal() as db:
        logo = (await render.fetch_branding(db))["logo"]
    assert logo and logo.startswith("data:image/png;base64,")


@pytest.mark.skipif(not _WEASYPRINT, reason="weasyprint/system libs unavailable")
def test_url_fetcher_blocks_network_and_foreign_files():
    """The restricted fetcher refuses everything but data: URIs and the bundled
    fonts, so report content can't trigger SSRF or a local-file read (ADR-0030)."""
    for blocked in ("http://169.254.169.254/", "https://example.com/x.png", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            render._url_fetcher(blocked)
    # A bundled font is allowed (returns a fetch response, doesn't raise).
    font_url = (render._FONTS / "Lato-Regular.ttf").as_uri()
    assert render._url_fetcher(font_url) is not None
