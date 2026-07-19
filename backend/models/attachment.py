"""Challenge file attachments (ARCHITECTURE.md §13.3).

Tenant-scoped (§6.2). ``object_key`` is the storage-layer key
(``<competition_id>/<challenge_id>/<uuid>_<filename>``) — internal, never
serialized. Deleting a challenge cascades the rows; the objects themselves are
removed explicitly by the challenge-delete path (orphaned objects would
otherwise linger in the bucket).
"""

from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class Attachment(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    object_key: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
