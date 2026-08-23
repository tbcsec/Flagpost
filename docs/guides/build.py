#!/usr/bin/env python3
"""Build the branded Flagpost user-guide PDFs from Markdown sources.

Each guide is a directory beside this script holding a ``guide.yaml`` (title,
audience, ordered chapter list) and a ``chapters/`` folder of Markdown files.
Chapters carry no H1 — the build renders the chapter title itself (with its
"Chapter N" kicker) from guide.yaml, so the table of contents and the page
headers can never drift from the body. Start chapter files at ``##``.

The visual theme lives in ``theme/`` (stylesheet, page template, the mark, and
the vendored Space Grotesk faces — the same @fontsource files the frontend
ships). Colours mirror the app's Harbor palette; see theme/style.css.

The version stamped on each cover is read from ``SOURCE_BUILD_VERSION`` in
backend/config.py, so a guide built at a release describes that release.

Usage:
    python build.py                 # build every guide into dist/
    python build.py competitor      # build one guide
    python build.py --deploy        # also copy PDFs to frontend/public/guides/

Requires the tooling in requirements.txt (WeasyPrint needs system
Pango/cairo — the same libraries the reports module documents).
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
DIST = ROOT / "dist"
DEPLOY_DIR = REPO / "frontend" / "public" / "guides"

MARKDOWN_EXTENSIONS = [
    "tables",
    "fenced_code",
    "sane_lists",
    "admonition",
    "attr_list",
    "smarty",
]


def source_version() -> str:
    """The version this build documents — SOURCE_BUILD_VERSION from config.py."""
    config = (REPO / "backend" / "config.py").read_text()
    match = re.search(r'SOURCE_BUILD_VERSION\s*=\s*"([^"]+)"', config)
    return match.group(1) if match else "unknown"


def discover_guides() -> list[Path]:
    return sorted(
        p.parent for p in ROOT.glob("*/guide.yaml") if p.parent.name != "theme"
    )


def build_guide(guide_dir: Path, version: str, date: str) -> Path:
    meta = yaml.safe_load((guide_dir / "guide.yaml").read_text())

    chapters = []
    for n, chapter in enumerate(meta["chapters"], start=1):
        raw = (guide_dir / "chapters" / chapter["file"]).read_text()
        chapters.append(
            {
                "n": n,
                "id": f"ch-{n}",
                "title": chapter["title"],
                "html": markdown.markdown(raw, extensions=MARKDOWN_EXTENSIONS),
            }
        )

    env = Environment(loader=FileSystemLoader(ROOT / "theme"), autoescape=True)
    document = env.get_template("template.html.j2").render(
        meta=meta, chapters=chapters, version=version, date=date
    )

    # Imported lazily so `--help` and guide-source errors don't need the
    # system Pango/cairo libraries WeasyPrint loads at import time.
    from weasyprint import HTML

    DIST.mkdir(exist_ok=True)
    out = DIST / f"{meta['slug']}.pdf"
    HTML(string=document, base_url=str(ROOT / "theme")).write_pdf(out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("guides", nargs="*", help="guide directory names (default: all)")
    parser.add_argument(
        "--deploy",
        action="store_true",
        help=f"also copy built PDFs to {DEPLOY_DIR.relative_to(REPO)}",
    )
    args = parser.parse_args()

    targets = (
        [ROOT / name for name in args.guides] if args.guides else discover_guides()
    )
    for target in targets:
        if not (target / "guide.yaml").is_file():
            parser.error(f"{target.name}: no guide.yaml")

    version = source_version()
    date = datetime.date.today().strftime("%-d %B %Y")

    for target in targets:
        out = build_guide(target, version, date)
        size_kb = out.stat().st_size // 1024
        print(f"built {out.relative_to(REPO)}  ({size_kb} KB, Flagpost {version})")
        if args.deploy:
            DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
            deployed = DEPLOY_DIR / out.name
            deployed.write_bytes(out.read_bytes())
            print(f"  → {deployed.relative_to(REPO)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
