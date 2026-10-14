"""Code judge — site configuration (#447, ADR-0042).

The ``judge`` module ships **inert**: nothing judges until an operator points
it at a container-runtime endpoint, registers at least one language, and
enables it — the instancing / AI posture (ADR-0036, ADR-0023).

Both tables are site-wide infrastructure, so neither carries
``CompetitionScopedMixin``, and both are excluded from the backup export
(``utils/backup.py``): ``JudgeSettings`` because a container endpoint is
specific to the host (the ``InstanceSettings`` reasoning), and ``JudgeLanguage``
because a language *is* an image plus commands the judge executes — the same
class of thing GHSA-x8v4 found must not be plantable through a backup import.
An operator restoring onto new infrastructure re-registers languages.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import JSON, Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin

JUDGE_SETTINGS_ID = "judge"
EXECUTOR_KINDS = ("docker",)

DEFAULT_MAX_CONCURRENT_JUDGINGS = 1
DEFAULT_TIME_LIMIT_MS = 2000
DEFAULT_MEMORY_LIMIT_MB = 256
DEFAULT_OUTPUT_LIMIT_KB = 8192

# The only substitutions a language command may use (ADR-0042 amendment): the
# executor replaces them with the uploaded source's path and the scratch
# directory. Anything else in braces is rejected at the API, so a command can't
# smuggle in a placeholder the executor would leave as a literal.
COMMAND_PLACEHOLDERS = ("{source}", "{work}")


class JudgeSettings(Base, TimestampMixin):
    """Site-level judge configuration, a singleton like ``instance_settings``."""

    __tablename__ = "judge_settings"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=JUDGE_SETTINGS_ID
    )
    # Master switch. Enabling is refused at the API until an endpoint and at
    # least one enabled language exist, so "enabled but unconfigured" is
    # unreachable.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Executor kind (EXECUTOR_KINDS). Only the embedded Docker executor exists;
    # an external judgehost kind is a later milestone (ADR-0042 §1).
    executor: Mapped[str] = mapped_column(
        String, nullable=False, default="docker", server_default="docker"
    )
    # Container-runtime API endpoint — always a least-privilege socket proxy,
    # never a raw Docker socket (ADR-0036 §1). A trusted operator setting that
    # is expected to be private, so not run through the ADR-0013 SSRF
    # blocklist (the instancing endpoint posture). May be the same proxy the
    # instances module uses.
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # How many judgings run at once. 1 by default: bounds peak cost to one core
    # and one memory limit and keeps time limits meaningful on shared hardware
    # (ADR-0042 §5).
    max_concurrent_judgings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MAX_CONCURRENT_JUDGINGS,
        server_default=str(DEFAULT_MAX_CONCURRENT_JUDGINGS),
    )
    # Defaults a problem inherits unless it sets its own (#447b).
    default_time_limit_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_TIME_LIMIT_MS,
        server_default=str(DEFAULT_TIME_LIMIT_MS),
    )
    default_memory_limit_mb: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MEMORY_LIMIT_MB,
        server_default=str(DEFAULT_MEMORY_LIMIT_MB),
    )
    default_output_limit_kb: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_OUTPUT_LIMIT_KB,
        server_default=str(DEFAULT_OUTPUT_LIMIT_KB),
    )


class JudgeLanguage(Base, TimestampMixin):
    """A language the judge can run: a stock image plus how to compile and run
    a submission in it. Commands are argv lists (never a shell string), using
    only ``COMMAND_PLACEHOLDERS``; they run as the unprivileged submission user
    inside the judge container (ADR-0042 amendment)."""

    __tablename__ = "judge_languages"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Stable, URL-safe identifier problems refer to (e.g. "python3", "cpp17").
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # A stock image, e.g. "python:3.13-slim" — the harness is uploaded into it
    # per judging, so no Flagpost-specific image is needed (ADR-0042 amendment).
    image_ref: Mapped[str] = mapped_column(String, nullable=False)
    # The filename the submission is saved as, e.g. "solution.py", "Main.java"
    # (some toolchains care).
    source_filename: Mapped[str] = mapped_column(String, nullable=False)
    # argv lists. compile_command is null for interpreted languages.
    compile_command: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    run_command: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # Scales a problem's time limit for this language, so an interpreted
    # language isn't punished by a limit tuned for a compiled one.
    time_multiplier: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
