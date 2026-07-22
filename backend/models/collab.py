"""Collaborative-document persistence (ARCHITECTURE.md §4.2, ADR-0014).

One row per collaboratively-edited note, keyed by a stable ``doc_key`` that
encodes the resource it belongs to (``team_challenge:<team_id>:<challenge_id>``
or ``ticket:<ticket_id>`` today). ``state`` is an **opaque** Y.js document blob
— the full merged CRDT state a client last persisted (``Y.encodeStateAsUpdate``).
The backend never decodes it (ADR-0014: dumb relay + client-snapshot); it only
stores the latest blob and hands it back as the join snapshot so a fresh client
can reconstruct the document, after which live updates flow over the WS relay.

Scoped by ``competition_id`` (§6.2) — every note belongs to exactly one
competition, so the row cascades away when the competition is deleted, and the
scope is auditable even though the primary lookup is by ``doc_key``.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime, utcnow


class CollabDocument(Base, TimestampMixin):
    __tablename__ = "collab_documents"

    # Natural key: the resource address (see module docstring). Globally unique.
    doc_key: Mapped[str] = mapped_column(String, primary_key=True)
    competition_id: Mapped[str] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Opaque Y.js merged state (Y.encodeStateAsUpdate). Null until first persist.
    state: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, onupdate=utcnow, nullable=True
    )
