"""The code judge's executor contract (#448, ADR-0042 §1).

A sibling of ``utils/provisioners.py``, not a use of it: a provisioner manages
long-lived, network-exposed instances, whereas a judging is one run-to-
completion with a captured result. The *shape* is shared — an ABC whose
backends register by ``kind`` through a class decorator, constructed per use
with their configuration, and a staged ``validate()`` returning
``CheckResult`` legs — and lookup always goes through the registry.

``make_job`` turns a problem, a language and a submission into the frozen
``JudgeJob`` an executor runs: it applies the language's time multiplier and
substitutes the only two command placeholders (``models.judge.
COMMAND_PLACEHOLDERS``). Executors place the files; nothing else about a job
is executor-specific.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from utils.provisioners import CheckResult

VERDICTS = (
    "accepted",
    "wrong_answer",
    "time_limit",
    "memory_limit",
    "output_limit",
    "runtime_error",
    "compile_error",
    "internal_error",
)

# Where an executor puts the submission and its scratch space inside the judge
# environment. Commands refer to them only through the placeholders.
SOURCE_DIR = "/submission"
WORK_DIR = "/work"


@dataclass(frozen=True)
class JudgeTest:
    sample: bool
    input: bytes
    answer: bytes


@dataclass(frozen=True)
class JudgeJob:
    """Everything one judging needs. Limits are final — the language's time
    multiplier and the site defaults are already applied."""

    judging_id: str
    image_ref: str
    source_filename: str
    source: bytes
    compile_command: tuple[str, ...] | None
    run_command: tuple[str, ...]
    time_limit_ms: int
    memory_limit_mb: int
    output_limit_kb: int
    compare_mode: str
    float_tolerance: float
    # Judging order: samples first (the problem zip's order).
    tests: tuple[JudgeTest, ...]
    # Judge every test rather than stopping at the first failure — an author's
    # reference-solution check (#450), which reports each test.
    run_all: bool = False


@dataclass(frozen=True)
class JudgeTestResult:
    """One test that ran. ``output`` is the submission's (capped) output, and
    only ever for an example test that ran before any hidden one — a
    submission's output on a hidden test could echo the hidden input."""

    index: int
    sample: bool
    verdict: str
    time_ms: int
    wall_ms: int
    memory_kb: int
    exit_code: int | None = None
    signal: int | None = None
    output: str | None = None


@dataclass(frozen=True)
class JudgeResult:
    verdict: str
    # The compiler's own messages, safe to show the competitor: the compile
    # step can't read the test data.
    compile_output: str = ""
    compile_time_ms: int = 0
    tests: tuple[JudgeTestResult, ...] = field(default_factory=tuple)
    # Harness-side detail for an internal_error — for staff, not competitors.
    error: str | None = None

    @property
    def max_time_ms(self) -> int:
        return max((t.time_ms for t in self.tests), default=0)

    @property
    def max_memory_kb(self) -> int:
        return max((t.memory_kb for t in self.tests), default=0)


class JudgeExecutorError(Exception):
    """The judging couldn't be carried out (the container runtime failed, no
    result came back). Distinct from a verdict: the caller records it as an
    internal error and may retry, rather than blaming the submission."""


class UnknownJudgeExecutorKind(JudgeExecutorError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"Unknown judge executor kind: {kind!r}")
        self.kind = kind


class JudgeExecutor(ABC):
    #: Registry key; one of ``models.judge.EXECUTOR_KINDS``.
    kind: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_settings(cls, settings) -> JudgeExecutor:
        """Construct from the site's ``JudgeSettings`` (each kind reads its own
        configuration out of them)."""

    @abstractmethod
    async def run(self, job: JudgeJob) -> JudgeResult:
        """Compile and judge one submission. Returns the verdict — including
        ``internal_error`` when the harness itself reports one — and raises
        ``JudgeExecutorError`` when no verdict could be obtained at all."""

    @abstractmethod
    async def validate(self) -> list[CheckResult]:
        """The setup flow's staged "Check connection". Ordered; a failing leg
        may end the run early, and every leg carries actionable ``detail``."""

    @abstractmethod
    def time_budget_s(self, job: JudgeJob) -> float:
        """How long ``run(job)`` may legitimately take, end to end. The worker
        treats a judging still running past this (plus slack) as stuck."""

    async def cleanup(self, keep: set[str]) -> int:
        """Remove what crashed workers left behind — anything not belonging to a
        judging in ``keep`` (those still running inside their deadline) — and
        return how many. Must be safe when other processes, or other installs
        sharing the runtime, are judging: it must never cut a live judging
        short. Default: nothing to do."""
        return 0


_KINDS: dict[str, type[JudgeExecutor]] = {}


def register_judge_executor(cls: type[JudgeExecutor]) -> type[JudgeExecutor]:
    """Class decorator: register an executor by its ``kind``."""
    _KINDS[cls.kind] = cls
    return cls


def judge_executor_kind(kind: str) -> type[JudgeExecutor]:
    try:
        return _KINDS[kind]
    except KeyError:
        raise UnknownJudgeExecutorKind(kind) from None


def judge_executor_kinds() -> tuple[str, ...]:
    return tuple(sorted(_KINDS))


def executor_for(settings) -> JudgeExecutor:
    """The configured executor, looked up through the registry by kind."""
    import utils.judge_executor_docker  # noqa: F401  (registers the docker kind)

    return judge_executor_kind(settings.executor).from_settings(settings)


# --- building a job -------------------------------------------------------------


def substitute(command: list[str] | tuple[str, ...], source_filename: str) -> tuple[str, ...]:
    source = f"{SOURCE_DIR}/{source_filename}"
    return tuple(arg.replace("{source}", source).replace("{work}", WORK_DIR) for arg in command)


def make_job(
    *,
    judging_id: str,
    image_ref: str,
    source_filename: str,
    source: bytes,
    compile_command: list[str] | None,
    run_command: list[str],
    time_multiplier: float,
    time_limit_ms: int,
    memory_limit_mb: int,
    output_limit_kb: int,
    compare_mode: str,
    float_tolerance: float,
    tests: list[JudgeTest],
    run_all: bool = False,
) -> JudgeJob:
    if "/" in source_filename or source_filename in ("", ".", ".."):
        raise JudgeExecutorError(f"bad source filename {source_filename!r}")
    return JudgeJob(
        judging_id=judging_id,
        image_ref=image_ref,
        source_filename=source_filename,
        source=source,
        compile_command=(
            substitute(compile_command, source_filename) if compile_command else None
        ),
        run_command=substitute(run_command, source_filename),
        time_limit_ms=max(1, math.ceil(time_limit_ms * time_multiplier)),
        memory_limit_mb=memory_limit_mb,
        output_limit_kb=output_limit_kb,
        compare_mode=compare_mode,
        float_tolerance=float_tolerance,
        tests=tuple(tests),
        run_all=run_all,
    )
