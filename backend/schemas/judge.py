"""Code judge — admin config schemas (#447, ADR-0042).

Language commands are the sharp edge here: they are executed inside the judge
container. They are validated as **argv lists, never shell strings**, and may
reference only the placeholders in ``models.judge.COMMAND_PLACEHOLDERS``.
"""

from __future__ import annotations

import re

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
