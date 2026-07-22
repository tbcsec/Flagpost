"""Per-competition optional-module state (ARCHITECTURE.md §11.3).

An optional system module (automations now; feedback in a later phase) "can be
disabled per competition" — this is that state. **Absence of a row means the
default: enabled** (in-box optional modules are on by default, §11.3), so a
fresh competition needs no provisioning and a new optional module lights up
everywhere without a backfill. Required-core modules never get a row — the
loader's ``is_module_enabled`` short-circuits them to always-on.
"""

from uuid import uuid4

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class CompetitionModule(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "competition_modules"
    __table_args__ = (
        UniqueConstraint(
            "competition_id", "module_id", name="uq_competition_module"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # The manifest id from plugins/<id>/plugin.yaml (§11.1).
    module_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
