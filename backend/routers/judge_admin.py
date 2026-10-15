"""Code judge — site configuration (#447, ADR-0042).

Admin → Site settings → Code judge. Gated on ``manage_judge_infra`` (its own
grant, not ``manage_site_settings``): this surface points the platform at a
container-runtime endpoint and decides which images and commands the judge
executes, so it sits with the other infrastructure grants
(``manage_instance_infra``, ``manage_ai``).

The module ships **inert**: ``enabled`` is off until an operator sets an
endpoint and registers at least one enabled language, and enabling is refused
until both hold — so "enabled but unconfigured" is unreachable, including via a
language being disabled or deleted out from under an enabled judge.

"Test connection" arrives with the executor (#448).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.challenge_instancing import INSTANCE_SETTINGS_ID, InstanceSettings
from models.judge import JUDGE_SETTINGS_ID, JudgeLanguage, JudgeSettings
from models.user import User
from schemas.judge import (
    JudgeCheckLeg,
    JudgeCheckResult,
    JudgeLanguageCreate,
    JudgeLanguageOut,
    JudgeLanguagePreset,
    JudgeLanguageUpdate,
    JudgeSettingsOut,
    JudgeSettingsUpdate,
    JudgeSetupRequest,
    JudgeSetupResult,
)
from utils.event_bus import event_bus
from utils.judge_connection import effective_endpoint
from utils.judge_executor import executor_for
from utils.judge_presets import LANGUAGE_PRESETS

router = APIRouter(prefix="/api/admin/judge", tags=["judge-admin"])

_PERM = "manage_judge_infra"
_COMPOSE_DEFAULT_ENDPOINT = "http://socket-proxy:2375"


async def _get_or_create(db: AsyncSession) -> JudgeSettings:
    settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
    if settings is None:
        settings = JudgeSettings(id=JUDGE_SETTINGS_ID)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def _lock_settings(db: AsyncSession) -> JudgeSettings:
    """Load the singleton and take a row lock on it, so concurrent admin writes
    that touch the enable invariant serialise (the ``_lock_admission``
    pattern). Real on Postgres; SQLite drops ``FOR UPDATE`` but serialises
    writers anyway."""
    settings = await _get_or_create(db)
    await db.execute(
        select(JudgeSettings.id)
        .where(JudgeSettings.id == JUDGE_SETTINGS_ID)
        .with_for_update()
    )
    return settings


async def _enabled_language_count(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count(JudgeLanguage.id)).where(JudgeLanguage.enabled.is_(True))
        )
        or 0
    )


async def _check_enable_invariant(db: AsyncSession, settings: JudgeSettings) -> None:
    if not settings.enabled:
        return
    endpoint, _managed = effective_endpoint(settings)
    if not endpoint:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Set an endpoint URL before enabling the judge.",
        )
    if await _enabled_language_count(db) == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Add and enable at least one language before enabling the judge.",
        )


# --- settings ----------------------------------------------------------------


async def _to_out(db: AsyncSession, settings: JudgeSettings) -> JudgeSettingsOut:
    """The settings plus a suggested endpoint for the form to prefill. Reusing
    the challenge-instancing proxy is the common case — one least-privilege
    proxy can serve both — so offer that before the compose default."""
    out = JudgeSettingsOut.model_validate(settings)
    endpoint, managed = effective_endpoint(settings)
    out.endpoint_url = endpoint
    out.endpoint_managed = managed
    if managed:
        out.suggested_endpoint_url = endpoint
        return out
    instance = await db.get(InstanceSettings, INSTANCE_SETTINGS_ID)
    out.suggested_endpoint_url = (
        instance.endpoint_url
        if instance is not None and instance.endpoint_url
        else _COMPOSE_DEFAULT_ENDPOINT
    )
    return out


@router.get("/settings", response_model=JudgeSettingsOut)
async def get_settings(
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> JudgeSettingsOut:
    return await _to_out(db, await _get_or_create(db))


@router.put("/settings", response_model=JudgeSettingsOut)
async def update_settings(
    body: JudgeSettingsUpdate,
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> JudgeSettingsOut:
    settings = await _lock_settings(db)
    if body.executor is not None:
        settings.executor = body.executor
    if body.endpoint_url is not None:
        _endpoint, managed = effective_endpoint(settings)
        if managed:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "The endpoint is set by your deployment (JUDGE_ENDPOINT_URL), "
                "so it can't be changed here.",
            )
        settings.endpoint_url = body.endpoint_url.strip() or None
    if body.max_concurrent_judgings is not None:
        settings.max_concurrent_judgings = body.max_concurrent_judgings
    if body.default_time_limit_ms is not None:
        settings.default_time_limit_ms = body.default_time_limit_ms
    if body.default_memory_limit_mb is not None:
        settings.default_memory_limit_mb = body.default_memory_limit_mb
    if body.default_output_limit_kb is not None:
        settings.default_output_limit_kb = body.default_output_limit_kb
    if body.enabled is not None:
        settings.enabled = body.enabled
    await _check_enable_invariant(db, settings)
    await db.commit()
    # Commit before emit — the audit consumer opens its own session. Carries no
    # endpoint, only who and the new enabled flag (instance.settings_updated).
    await event_bus.emit(
        "judge.settings_updated",
        {"actor_user_id": current_user.id, "enabled": settings.enabled},
    )
    return await _to_out(db, settings)


@router.post("/check", response_model=JudgeCheckResult)
async def check_connection(
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> JudgeCheckResult:
    """Probe the **saved/effective** endpoint — never one supplied in the
    request — so this can't be turned into a way to make the server reach
    arbitrary addresses (the instancing test-the-saved-config posture)."""
    settings = await _get_or_create(db)
    endpoint, _managed = effective_endpoint(settings)
    if not endpoint:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Save an endpoint before checking it."
        )
    legs = await _run_check(settings)
    return JudgeCheckResult(
        ok=bool(legs) and all(leg.ok for leg in legs),
        legs=[JudgeCheckLeg(name=leg.name, ok=leg.ok, detail=leg.detail) for leg in legs],
    )


async def _run_check(settings: JudgeSettings) -> list:
    """The configured executor's staged check: the proxy is reachable and
    restricted, the harness is installed, and a real test judging runs end to
    end (#448). Built from the saved settings only. Seam tests monkeypatch; the
    legs themselves are exercised against a fake daemon in test_judge_executor."""
    return await executor_for(settings).validate()


@router.post("/setup", response_model=JudgeSetupResult)
async def apply_setup(
    body: JudgeSetupRequest,
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> JudgeSetupResult:
    """The setup flow's single atomic write. Doing it as one transaction means
    a failure part-way can't leave the judge half-configured — e.g. enabled
    with some languages added and others not — which a client making several
    calls could."""
    presets = {p["key"]: p for p in LANGUAGE_PRESETS}
    unknown = sorted(set(body.preset_keys) - set(presets))
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown built-in language(s): {', '.join(unknown)}.",
        )
    wanted = set(body.preset_keys)

    settings = await _lock_settings(db)
    existing = {
        lang.key: lang
        for lang in (
            await db.execute(select(JudgeLanguage).where(JudgeLanguage.key.in_(presets)))
        ).scalars()
    }
    created: list[JudgeLanguage] = []
    changed: list[JudgeLanguage] = []
    for key in presets:
        row = existing.get(key)
        if key in wanted and row is None:
            row = JudgeLanguage(**presets[key], enabled=True)
            db.add(row)
            created.append(row)
        elif row is not None and row.enabled != (key in wanted):
            # Ticked → on; unticked built-in → off. The row (and the version the
            # operator pinned) is kept either way.
            row.enabled = key in wanted
            changed.append(row)
    settings.enabled = True
    await db.flush()
    await _check_enable_invariant(db, settings)
    await db.commit()

    for row in created:
        await event_bus.emit("judge.language_created", _language_payload(current_user, row))
    for row in changed:
        await event_bus.emit("judge.language_updated", _language_payload(current_user, row))
    await event_bus.emit(
        "judge.settings_updated", {"actor_user_id": current_user.id, "enabled": True}
    )
    languages = (
        await db.execute(select(JudgeLanguage).order_by(JudgeLanguage.name))
    ).scalars().all()
    return JudgeSetupResult(
        settings=await _to_out(db, settings),
        languages=[JudgeLanguageOut.model_validate(lang) for lang in languages],
    )


# --- languages ---------------------------------------------------------------


def _language_payload(user: User, language: JudgeLanguage) -> dict:
    return {
        "actor_user_id": user.id,
        "language_id": language.id,
        "key": language.key,
    }


async def _get_language(db: AsyncSession, language_id: str) -> JudgeLanguage:
    language = await db.get(JudgeLanguage, language_id)
    if language is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Language not found.")
    return language


@router.get("/presets", response_model=list[JudgeLanguagePreset])
async def list_presets(
    current_user: User = Depends(require_permission(_PERM)),
) -> list[dict]:
    """Built-in languages the admin can add with one click
    (``utils/judge_presets``). Which are already added is the client's join
    against ``/languages`` by key."""
    return LANGUAGE_PRESETS


@router.get("/languages", response_model=list[JudgeLanguageOut])
async def list_languages(
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> list[JudgeLanguage]:
    rows = await db.execute(select(JudgeLanguage).order_by(JudgeLanguage.name))
    return list(rows.scalars().all())


@router.post(
    "/languages", response_model=JudgeLanguageOut, status_code=status.HTTP_201_CREATED
)
async def create_language(
    body: JudgeLanguageCreate,
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> JudgeLanguage:
    clash = await db.scalar(select(JudgeLanguage.id).where(JudgeLanguage.key == body.key))
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A language with key '{body.key}' already exists."
        )
    language = JudgeLanguage(
        key=body.key,
        name=body.name,
        image_ref=body.image_ref,
        source_filename=body.source_filename,
        compile_command=body.compile_command,
        run_command=body.run_command,
        time_multiplier=body.time_multiplier,
        enabled=body.enabled,
    )
    db.add(language)
    await db.commit()
    await db.refresh(language)
    await event_bus.emit("judge.language_created", _language_payload(current_user, language))
    return language


@router.patch("/languages/{language_id}", response_model=JudgeLanguageOut)
async def update_language(
    language_id: str,
    body: JudgeLanguageUpdate,
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> JudgeLanguage:
    settings = await _lock_settings(db)
    language = await _get_language(db, language_id)
    if body.name is not None:
        language.name = body.name
    if body.image_ref is not None:
        language.image_ref = body.image_ref
    if body.source_filename is not None:
        language.source_filename = body.source_filename
    # An explicit null clears the compile step (an interpreted language);
    # omitting the field leaves it untouched.
    if "compile_command" in body.model_fields_set:
        language.compile_command = body.compile_command
    if body.run_command is not None:
        language.run_command = body.run_command
    if body.time_multiplier is not None:
        language.time_multiplier = body.time_multiplier
    if body.enabled is not None:
        language.enabled = body.enabled
    await db.flush()
    # Disabling the last enabled language under an enabled judge would reach
    # the forbidden "enabled but unconfigured" state.
    await _check_enable_invariant(db, settings)
    await db.commit()
    await db.refresh(language)
    await event_bus.emit("judge.language_updated", _language_payload(current_user, language))
    return language


@router.delete("/languages/{language_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_language(
    language_id: str,
    current_user: User = Depends(require_permission(_PERM)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    settings = await _lock_settings(db)
    language = await _get_language(db, language_id)
    payload = _language_payload(current_user, language)
    await db.delete(language)
    await db.flush()
    await _check_enable_invariant(db, settings)
    await db.commit()
    await event_bus.emit("judge.language_deleted", payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
