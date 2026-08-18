"""Post-event report routes (#134, ADR-0030, optional ``reports`` module).

Organiser-facing, competition-scoped, gated on ``generate_report`` and the
module being enabled (§11.3). Generation is only allowed once the competition has
**ended** (ADR-0028): a report is a snapshot of a finished event. Creating a
report enqueues a ``pending`` :class:`CompetitionReport`; the scheduler tick
renders it off the request path (``utils.automation_scheduler``) and fills the
object-storage keys, mirroring the certificates bulk export. Clients poll the
status route, which hands back short-lived signed download URLs once ready.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from config import settings
from db import get_db
from models.competition import Competition
from models.report import CompetitionReport
from models.user import User
from plugins.loader import is_module_enabled
from schemas.report import (
    CompetitionReportOut,
    ReportCatalogOut,
    ReportCreate,
    ReportSectionOut,
)
from storage import get_storage
from storage.base import ObjectStorage
from utils.report_data import PRESETS, SECTION_LABELS, SECTIONS

router = APIRouter(
    prefix="/api/competitions/{competition_id}/reports", tags=["reports"]
)

_FORMATS = ("pdf", "html")


async def _guard(db: AsyncSession, competition_id: str) -> Competition:
    """The competition exists and the reports module is on for it (§11.3)."""
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await is_module_enabled(db, "reports", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The reports module is disabled for this competition",
        )
    return competition


def _download_url(storage: ObjectStorage, key: str, version: int, fmt: str) -> str:
    mime = "application/pdf" if fmt == "pdf" else "text/html"
    return storage.presigned_get_url(
        key,
        settings.signed_url_ttl_seconds,
        response_headers={
            "response-content-type": mime,
            "response-content-disposition": f'attachment; filename="report-v{version}.{fmt}"',
        },
    )


def _to_out(report: CompetitionReport, storage: ObjectStorage) -> CompetitionReportOut:
    out = CompetitionReportOut.model_validate(report)
    if report.status == "ready":
        if report.pdf_object_key:
            out.pdf_url = _download_url(storage, report.pdf_object_key, report.version, "pdf")
        if report.html_object_key:
            out.html_url = _download_url(storage, report.html_object_key, report.version, "html")
    return out


@router.get("/catalog", response_model=ReportCatalogOut)
async def report_catalog(
    competition_id: str,
    _user: User = Depends(require_permission("generate_report")),
    db: AsyncSession = Depends(get_db),
) -> ReportCatalogOut:
    """The sections, presets, and formats the settings tab offers."""
    await _guard(db, competition_id)
    return ReportCatalogOut(
        sections=[ReportSectionOut(id=s, label=SECTION_LABELS[s]) for s in SECTIONS],
        presets=PRESETS,
        formats=list(_FORMATS),
    )


@router.post("", response_model=CompetitionReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(
    competition_id: str,
    body: ReportCreate,
    current_user: User = Depends(require_permission("generate_report")),
    db: AsyncSession = Depends(get_db),
) -> CompetitionReportOut:
    """Enqueue a report. Only once the competition has ended (ADR-0028)."""
    competition = await _guard(db, competition_id)
    if competition.status != "ended":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A report can only be generated once the competition has ended",
        )
    sections = [s for s in dict.fromkeys(body.sections) if s in SECTIONS]
    if not sections:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one valid report section",
        )
    formats = [f for f in dict.fromkeys(body.formats) if f in _FORMATS]
    if not formats:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one valid output format",
        )
    config = {
        "preset": body.preset,
        "sections": sections,
        "formats": formats,
        "options": {"top_n": body.top_n},
    }
    # version = max()+1, retried on the unique-constraint conflict a concurrent
    # create loses (the DB serialises them; the loser recomputes).
    for _ in range(5):
        next_version = (
            (
                await db.scalar(
                    select(func.max(CompetitionReport.version)).where(
                        CompetitionReport.competition_id == competition_id
                    )
                )
            )
            or 0
        ) + 1
        report = CompetitionReport(
            competition_id=competition_id,
            requested_by=current_user.id,
            version=next_version,
            status="pending",
            config=config,
        )
        db.add(report)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            continue
        # No signed URLs yet (pending); the scheduler renders it off the request path.
        return CompetitionReportOut.model_validate(report)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not allocate a report version — please retry",
    )


@router.get("", response_model=list[CompetitionReportOut])
async def list_reports(
    competition_id: str,
    _user: User = Depends(require_permission("generate_report")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> list[CompetitionReportOut]:
    """The generation history, newest version first."""
    await _guard(db, competition_id)
    rows = (
        (
            await db.execute(
                select(CompetitionReport)
                .where(CompetitionReport.competition_id == competition_id)
                .order_by(CompetitionReport.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(r, storage) for r in rows]


async def _load(db: AsyncSession, competition_id: str, report_id: str) -> CompetitionReport:
    report = await db.get(CompetitionReport, report_id)
    if report is None or report.competition_id != competition_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        )
    return report


@router.get("/{report_id}", response_model=CompetitionReportOut)
async def get_report(
    competition_id: str,
    report_id: str,
    _user: User = Depends(require_permission("generate_report")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> CompetitionReportOut:
    await _guard(db, competition_id)
    return _to_out(await _load(db, competition_id, report_id), storage)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    competition_id: str,
    report_id: str,
    _user: User = Depends(require_permission("generate_report")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    await _guard(db, competition_id)
    report = await _load(db, competition_id, report_id)
    keys = [k for k in (report.pdf_object_key, report.html_object_key) if k]
    # Reclaim the DB row first, then clean storage best-effort — an unreachable
    # object store must not block the delete (matches certificates' delete_font).
    await db.delete(report)
    await db.commit()
    for key in keys:
        try:
            storage.delete(key)
        except Exception:  # noqa: BLE001 — best-effort; a leaked object is namespaced garbage
            pass
