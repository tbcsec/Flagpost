"""Support-ticket image attachments (issue #80, §4.4, §13.3).

Screenshots a participant (or staff) attaches to a message on a ticket thread.
Stored in object storage like challenge :class:`~models.attachment.Attachment`
— not as a ``LargeBinary`` column — because this is a *growing per-ticket
collection* added to by several authors over time, which is the shape MinIO
already solves; the site logo and collab snapshots are singleton
overwrite-in-place blobs, hence their different treatment.

Tenant-scoped (§6.2). ``object_key`` is internal and never serialized. The row
hangs off the **message** (not just the ticket) so an attachment on a staff
**internal note** inherits that message's visibility — the thread's internal
filter hides it from the competitor along with the note body.
"""

from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class TicketAttachment(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "ticket_attachments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("ticket_messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Who uploaded it — the uploader may delete their own attachment (staff may
    # delete any, for moderation).
    uploader_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    object_key: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    # The **sniffed** type, not the client's claim (see utils.image_sniff) — so
    # what we serve back is always what the bytes actually are.
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
