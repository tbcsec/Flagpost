"""Post-event report API schemas (#134, ADR-0030)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportSectionOut(BaseModel):
    id: str
    label: str


class ReportCatalogOut(BaseModel):
    """Drives the "Reports" settings tab: the sections a report can contain, the
    audience presets that pre-select a bundle of them, and the output formats."""

    sections: list[ReportSectionOut]
    presets: dict[str, list[str]]
    formats: list[str]


class ReportCreate(BaseModel):
    # The sections to include (validated server-side against the catalog); a
    # preset is just how the UI pre-fills this list, recorded for the history.
    sections: list[str] = Field(min_length=1, max_length=20)
    formats: list[str] = Field(default_factory=lambda: ["pdf", "html"])
    preset: str | None = Field(default=None, max_length=40)
    # Top-N depth for standings / tickets tables.
    top_n: int = Field(default=10, ge=3, le=100)


class CompetitionReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    status: str
    config: dict
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    # Present only when status == "ready": short-lived signed download URLs.
    pdf_url: str | None = None
    html_url: str | None = None
