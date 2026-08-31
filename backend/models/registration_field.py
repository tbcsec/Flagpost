"""Per-competition custom registration fields (#350, ARCHITECTURE.md §6.2).

An organiser defines extra fields on a competition — affiliation, t-shirt size,
dietary/accessibility needs, emergency contact, eligibility/consent — collected
when a subject *enters* the competition (individual join / team creation, not the
site-wide account registration, which is competition-agnostic) and stored **per
subject**: keyed by ``user_id`` in individual mode, ``team_id`` in team mode —
the same §13.2 subject semantics ``BracketMembership`` uses.

Two tenant-scoped tables (``CompetitionScopedMixin``):

- :class:`RegistrationField` — the definitions (label, type, options, required,
  order). Authored like the managed vocab (tags/difficulty/brackets).
- :class:`RegistrationFieldValues` — one row per subject, a JSON dict keyed by
  field ``key``. Keying values by the stable ``key`` (not a row id) means the
  definition set can be replaced wholesale without stranding values, and a
  renamed/removed field simply leaves its old values unreferenced — the same
  not-cascaded behaviour a removed tag has on a challenge.

These hold **personal data**: never surfaced publicly, only in the operator's
authenticated export/backup (``PRIVACY.md``).
"""

from uuid import uuid4

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from db import Base, CompetitionScopedMixin, TimestampMixin

# The field kinds an organiser can define. ``select`` carries ``options``;
# ``checkbox`` is a boolean consent/opt-in; ``text``/``textarea`` are free text.
FIELD_TYPES: tuple[str, ...] = ("text", "textarea", "select", "checkbox")


class RegistrationField(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "registration_fields"
    __table_args__ = (
        # A field's key is its stable handle within a competition — values
        # reference it, so it's unique per competition (§6.2).
        UniqueConstraint("competition_id", "key", name="uq_registration_field_key"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Stable machine handle values are keyed by (never shown to the subject).
    key: Mapped[str] = mapped_column(String, nullable=False)
    # What the subject sees.
    label: Mapped[str] = mapped_column(String, nullable=False)
    # One of FIELD_TYPES.
    field_type: Mapped[str] = mapped_column(String, nullable=False, default="text")
    # Choices for a ``select`` field; null/[] for the others. A JSON string list,
    # the same idiom as ``competition.brackets`` / ``challenge_tags``.
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Whether entry is blocked until this field is filled.
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Display order in the form (ascending); ties broken by key for stability.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class RegistrationFieldValues(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "registration_field_values"
    __table_args__ = (
        # One value row per subject per competition (§13.2). ``subject_id`` is a
        # plain string — user_id or team_id by mode — like BracketMembership,
        # deliberately not a polymorphic FK, so a deleted subject's row is merely
        # unreferenced rather than a constraint violation.
        UniqueConstraint(
            "competition_id", "subject_id", name="uq_registration_values_subject"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    subject_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # ``{field_key: value}`` — strings for text/select, bool for checkbox.
    values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
