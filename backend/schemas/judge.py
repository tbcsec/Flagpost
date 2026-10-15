"""Code judge — admin config schemas (#447, ADR-0042).

Language commands are the sharp edge here: they are executed inside the judge
container. They are validated as **argv lists, never shell strings**, and may
reference only the placeholders in ``models.judge.COMMAND_PLACEHOLDERS``.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.judge import COMMAND_PLACEHOLDERS, EXECUTOR_KINDS

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
# A bare filename: no path separators, no leading dot, nothing exotic.
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
# Any {…} group — every one must be an allowed placeholder.
_BRACES_RE = re.compile(r"\{[^}]*\}")
_MAX_ARGS = 32
_MAX_ARG_LEN = 512


def _validate_command(value: list[str] | None, *, required: bool) -> list[str] | None:
    if value is None:
        if required:
            raise ValueError("a command is required")
        return None
    if not value:
        if required:
            raise ValueError("a command needs at least one argument")
        return None
    if len(value) > _MAX_ARGS:
        raise ValueError(f"at most {_MAX_ARGS} arguments")
    cleaned = []
    for arg in value:
        if not isinstance(arg, str) or not arg.strip():
            raise ValueError("arguments must be non-empty strings")
        if len(arg) > _MAX_ARG_LEN:
            raise ValueError(f"an argument is longer than {_MAX_ARG_LEN} characters")
        if "\x00" in arg or "\n" in arg:
            raise ValueError("arguments can't contain NUL or newline characters")
        for token in _BRACES_RE.findall(arg):
            if token not in COMMAND_PLACEHOLDERS:
                raise ValueError(
                    f"unknown placeholder {token}; allowed: "
                    + ", ".join(COMMAND_PLACEHOLDERS)
                )
        cleaned.append(arg)
    return cleaned


class JudgeSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    executor: str
    endpoint_url: str | None
    max_concurrent_judgings: int
    default_time_limit_ms: int
    default_memory_limit_mb: int
    default_output_limit_kb: int
    # What the form prefills when no endpoint is stored yet: the challenge-
    # instancing proxy if one is configured, else the compose stack's default.
    # Only a suggestion — nothing is stored until the admin saves.
    suggested_endpoint_url: str = "http://socket-proxy:2375"
    # True when the deployment sets the endpoint (JUDGE_ENDPOINT_URL, from the
    # docker-compose.judge.yml overlay): ``endpoint_url`` is then that value and
    # can't be changed here.
    endpoint_managed: bool = False


class JudgeSettingsUpdate(BaseModel):
    enabled: bool | None = None
    executor: str | None = None
    # "" clears it.
    endpoint_url: str | None = Field(default=None, max_length=512)
    max_concurrent_judgings: int | None = Field(default=None, ge=1, le=64)
    default_time_limit_ms: int | None = Field(default=None, ge=100, le=60_000)
    default_memory_limit_mb: int | None = Field(default=None, ge=16, le=8192)
    default_output_limit_kb: int | None = Field(default=None, ge=1, le=262_144)

    @field_validator("executor")
    @classmethod
    def _known_executor(cls, v: str | None) -> str | None:
        if v is not None and v not in EXECUTOR_KINDS:
            raise ValueError(f"executor must be one of: {', '.join(EXECUTOR_KINDS)}")
        return v


class JudgeLanguageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    image_ref: str
    source_filename: str
    compile_command: list[str] | None
    run_command: list[str]
    time_multiplier: float
    enabled: bool


class _LanguageFields(BaseModel):
    """Shared validators. Fields are optional here so Update can reuse them;
    Create re-declares the required ones."""

    key: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=64)
    image_ref: str | None = Field(default=None, min_length=1, max_length=256)
    source_filename: str | None = None
    time_multiplier: float | None = Field(default=None, ge=0.1, le=20)
    enabled: bool | None = None

    @field_validator("key")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        if v is not None and not _KEY_RE.fullmatch(v):
            raise ValueError(
                "use 1–32 lowercase letters, digits, '-' or '_', starting with a letter or digit"
            )
        return v

    @field_validator("source_filename")
    @classmethod
    def _bare_filename(cls, v: str | None) -> str | None:
        if v is not None and not _FILENAME_RE.fullmatch(v):
            raise ValueError("a plain filename like solution.py — no paths")
        return v

    @field_validator("image_ref")
    @classmethod
    def _image_ref(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v or any(c.isspace() for c in v):
                raise ValueError("an image reference can't contain whitespace")
        return v


class JudgeLanguageCreate(_LanguageFields):
    key: str
    name: str = Field(min_length=1, max_length=64)
    image_ref: str = Field(min_length=1, max_length=256)
    source_filename: str
    compile_command: list[str] | None = None
    run_command: list[str]
    time_multiplier: float = Field(default=1.0, ge=0.1, le=20)
    enabled: bool = True

    @field_validator("compile_command")
    @classmethod
    def _compile(cls, v: list[str] | None) -> list[str] | None:
        return _validate_command(v, required=False)

    @field_validator("run_command")
    @classmethod
    def _run(cls, v: list[str]) -> list[str]:
        return _validate_command(v, required=True)  # type: ignore[return-value]


class JudgeLanguageUpdate(_LanguageFields):
    # The key is immutable once created: problems refer to languages by key.
    key: None = None
    compile_command: list[str] | None = None
    # Explicitly clearing the compile step (null) needs to be distinguishable
    # from "leave unchanged" — see the router's use of model_fields_set.
    run_command: list[str] | None = None

    @field_validator("compile_command")
    @classmethod
    def _compile(cls, v: list[str] | None) -> list[str] | None:
        return _validate_command(v, required=False)

    @field_validator("run_command")
    @classmethod
    def _run(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _validate_command(v, required=True)


class JudgeLanguagePreset(BaseModel):
    """A built-in language definition (``utils/judge_presets``). Adding one
    creates an ordinary language from it, enabled."""

    key: str
    name: str
    image_ref: str
    source_filename: str
    compile_command: list[str] | None
    run_command: list[str]
    time_multiplier: float


class JudgeCheckLeg(BaseModel):
    name: str
    ok: bool
    detail: str


class JudgeCheckResult(BaseModel):
    ok: bool
    legs: list[JudgeCheckLeg]


class JudgeSetupRequest(BaseModel):
    """The setup flow's one atomic write: which built-in languages competitors
    may use. Ticked presets are added (or re-enabled); unticked built-ins are
    disabled; custom languages are left alone; the judge is switched on."""

    preset_keys: list[str] = Field(min_length=1, max_length=64)


class JudgeSetupResult(BaseModel):
    settings: JudgeSettingsOut
    languages: list[JudgeLanguageOut]


# --- problem authoring (#447) -------------------------------------------------

class JudgeTestcaseOut(BaseModel):
    """A test case as listed in the editor: sizes plus a short preview, never
    the whole (possibly multi-MB) content."""

    id: str
    sample: bool
    input_bytes: int
    answer_bytes: int
    input_preview: str
    answer_preview: str


class JudgeTestcaseContent(BaseModel):
    """One test case in full, for editing."""

    id: str
    sample: bool
    # False when the data is too big or isn't text: the editor then offers to
    # replace it by uploading files rather than editing in place.
    editable: bool = True
    input: str | None = None
    answer: str | None = None


class JudgeProblemOut(BaseModel):
    # Null = the site default, which is reported alongside so the editor can
    # show what an empty field means.
    time_limit_ms: int | None
    memory_limit_mb: int | None
    output_limit_kb: int | None
    compare_mode: str
    float_tolerance: float | None
    allowed_languages: list[str] | None
    testcases: list[JudgeTestcaseOut]
    default_time_limit_ms: int
    default_memory_limit_mb: int
    default_output_limit_kb: int


class JudgeProblemUpdate(BaseModel):
    """Partial update. An explicit null resets a limit (or the language list)
    to its default; omitting a field leaves it unchanged."""

    time_limit_ms: int | None = Field(default=None, ge=100, le=60_000)
    memory_limit_mb: int | None = Field(default=None, ge=16, le=8192)
    output_limit_kb: int | None = Field(default=None, ge=1, le=262_144)
    compare_mode: str | None = None
    float_tolerance: float | None = Field(default=None, gt=0, le=1)
    allowed_languages: list[str] | None = Field(default=None, max_length=64)

    @field_validator("compare_mode")
    @classmethod
    def _mode(cls, v: str | None) -> str | None:
        from models.judge_problem import COMPARE_MODES

        if v is not None and v not in COMPARE_MODES:
            raise ValueError(f"compare_mode must be one of: {', '.join(COMPARE_MODES)}")
        return v


class JudgeTestcaseCreate(BaseModel):
    """A test case typed or pasted in the editor. Bigger data goes through the
    multipart upload route instead (the JSON body is capped)."""

    input: str = Field(max_length=1_000_000)
    answer: str = Field(max_length=1_000_000)
    sample: bool = False


class JudgeTestcaseUpdate(BaseModel):
    input: str | None = Field(default=None, max_length=1_000_000)
    answer: str | None = Field(default=None, max_length=1_000_000)
    sample: bool | None = None


class JudgeStatusOut(BaseModel):
    """Whether this competition can have programming challenges right now, and
    in which languages. Readable by competitors too (#449), so languages carry
    only a key and a display name — never images or commands."""

    module_enabled: bool
    judge_enabled: bool
    ready: bool
    languages: list[dict]


# --- code submissions and judgings (#448) ------------------------------------------


class CodeSubmitRequest(BaseModel):
    language: str = Field(min_length=1, max_length=64)
    # Characters here; the byte cap (MAX_SOURCE_BYTES) is checked on the UTF-8.
    source: str = Field(min_length=1, max_length=200_000)
    # "submit" is judged against every test and scored; "run" against the
    # examples only, never scored (#449's Run button).
    kind: str = "submit"

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        from models.judging import CODE_SUBMISSION_KINDS

        if v not in CODE_SUBMISSION_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(CODE_SUBMISSION_KINDS)}")
        return v


class JudgingRunOut(BaseModel):
    """One test's result. For a hidden test a competitor sees only its position
    and verdict; time, memory and output are examples-only (output always is —
    the harness never returns it for a hidden test)."""

    index: int
    sample: bool
    verdict: str
    time_ms: int | None = None
    memory_kb: int | None = None
    output: str | None = None


class JudgingOut(BaseModel):
    id: str
    challenge_id: str
    user_id: str
    team_id: str | None
    kind: str
    language_key: str
    language_name: str
    status: str
    verdict: str | None
    # Judgings ahead of this one plus one, while queued; otherwise null.
    queue_position: int | None = None
    created_at: datetime
    finished_at: datetime | None
    compile_output: str | None
    max_time_ms: int | None
    max_memory_kb: int | None
    tests_passed: int | None
    tests_total: int | None
    tests: list[JudgingRunOut] = []
    # Why no verdict was reached — staff (judging_view) only.
    error: str | None = None


class CodeSourceOut(BaseModel):
    language_key: str
    source: str


class ProblemLanguageOut(BaseModel):
    key: str
    name: str
    # The file extension its source is saved with (".py", ".cpp"), so the
    # problem page can pick the language for an uploaded file.
    extension: str
    # This language's time limit: the problem's, scaled by the language's
    # multiplier.
    time_limit_ms: int


class ProblemExampleOut(BaseModel):
    index: int
    input: str
    answer: str
    # True when the text was cut for display (very large, or not UTF-8).
    truncated: bool = False


class ProblemOut(BaseModel):
    """What a competitor needs beside the statement: the limits, the languages
    they may submit in, and the example tests. Never the hidden tests."""

    time_limit_ms: int
    memory_limit_mb: int
    output_limit_kb: int
    compare_mode: str
    float_tolerance: float | None
    languages: list[ProblemLanguageOut]
    examples: list[ProblemExampleOut]
    # False while the judge is switched off: submitting would be refused.
    judge_ready: bool
