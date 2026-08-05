"""Admin config for the AI module (#98, ADR-0023) — Admin → Site settings → AI.

Gated on ``manage_ai`` (its own grant, not ``manage_site_settings``): this
surface holds an API key and enables outbound calls to an operator-chosen
endpoint, so it's a higher-stakes control than a palette or SMTP host — the same
reasoning the identity-provider admin follows.

The ``api_key`` is write-only and stored encrypted (ADR-0020). Enabling the
module is refused unless a ``base_url`` and ``model`` are set, so "enabled but
unconfigured" isn't reachable through the API. The provider ``base_url`` is a
trusted operator setting and is deliberately exempt from the webhook SSRF
blocklist (ADR-0023 §3), so a local inference endpoint works.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import String, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from auth.deps import require_permission
from db import get_db
from models.ai import AI_SETTINGS_ID, AiSettings
from models.user import User
from schemas.ai import AiSettingsOut, AiSettingsUpdate, TestConnectionCheck, TestConnectionResult
from utils.ai.client import AiProviderError, chat_completion, config_from_settings
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/admin/ai", tags=["ai-admin"])

# A trivial tool the test-connection forces the model to call, so an operator
# discovers *before* an event whether their model can tool-call at all — the
# admin assistant is entirely tool calls (spec §3.2).
_TEST_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "report_status",
            "description": "Report a one-word status back to the caller.",
            "parameters": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
        },
    }
]


async def _get_or_create(db: AsyncSession) -> AiSettings:
    settings = await db.get(AiSettings, AI_SETTINGS_ID)
    if settings is None:
        settings = AiSettings(id=AI_SETTINGS_ID)
        db.add(settings)
        await db.commit()
        settings = await db.get(AiSettings, AI_SETTINGS_ID)
    return settings


async def _api_key_present(db: AsyncSession) -> bool:
    """Whether an API key is stored, read past the ``EncryptedString`` decrypt.

    Mirrors ``site_settings._smtp_password_present``: the deferred key column
    decrypts on attribute access and *raises* on a key mismatch, so presence is
    read straight from the raw ciphertext — knowable even when the key is wrong,
    which is exactly when an admin is on this page to re-enter it.
    """
    raw = await db.scalar(
        select(type_coerce(AiSettings.__table__.c.api_key, String)).where(
            AiSettings.id == AI_SETTINGS_ID
        )
    )
    return bool(raw)


def _to_out(settings: AiSettings, *, api_key_set: bool) -> AiSettingsOut:
    out = AiSettingsOut.model_validate(settings)
    out.api_key_set = api_key_set
    return out


def _check_enable_invariant(settings: AiSettings) -> None:
    if settings.enabled and not (settings.base_url and settings.model):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a base URL and model before enabling the AI module",
        )


@router.get("/settings", response_model=AiSettingsOut)
async def get_settings(
    current_user: User = Depends(require_permission("manage_ai")),
    db: AsyncSession = Depends(get_db),
) -> AiSettingsOut:
    settings = await _get_or_create(db)
    return _to_out(settings, api_key_set=await _api_key_present(db))


@router.put("/settings", response_model=AiSettingsOut)
async def update_settings(
    body: AiSettingsUpdate,
    current_user: User = Depends(require_permission("manage_ai")),
    db: AsyncSession = Depends(get_db),
) -> AiSettingsOut:
    settings = await _get_or_create(db)

    if body.base_url is not None:
        settings.base_url = body.base_url.strip() or None
    if body.model is not None:
        settings.model = body.model.strip() or None
    if body.api_key is not None:
        # "" clears it (keyless local endpoint); omitting leaves it untouched.
        settings.api_key = body.api_key or None
    if body.max_output_tokens is not None:
        settings.max_output_tokens = body.max_output_tokens
    if body.competitor_max_output_tokens is not None:
        settings.competitor_max_output_tokens = body.competitor_max_output_tokens
    if body.request_timeout_s is not None:
        settings.request_timeout_s = body.request_timeout_s
    if body.admin_prompt_override is not None:
        settings.admin_prompt_override = body.admin_prompt_override or None
    if body.competitor_prompt_override is not None:
        settings.competitor_prompt_override = body.competitor_prompt_override or None
    if body.default_guidance_level is not None:
        settings.default_guidance_level = body.default_guidance_level
    if body.enabled is not None:
        settings.enabled = body.enabled

    _check_enable_invariant(settings)
    await db.commit()
    # Commit before emitting — the audit consumer opens its own session (§ "Things
    # that will bite you").
    await event_bus.emit(
        "ai.settings_updated",
        {"user_id": current_user.id, "enabled": settings.enabled},
    )
    return _to_out(settings, api_key_set=await _api_key_present(db))


async def _run_test_connection(config) -> TestConnectionResult:
    """(a) a trivial completion and (b) a forced tool call, each reported
    separately (spec §3.2). A provider error on either leg is captured as a
    failed check, not raised — the operator sees which leg failed and why."""
    try:
        result = await chat_completion(
            config,
            [{"role": "user", "content": "Reply with the single word: OK"}],
            max_tokens=16,
        )
        text = result.content.strip() or "(empty response)"
        completion = TestConnectionCheck(ok=True, detail=f"Model replied: {text[:200]}")
    except AiProviderError as exc:
        completion = TestConnectionCheck(ok=False, detail=str(exc)[:300])

    try:
        result = await chat_completion(
            config,
            [{"role": "user", "content": 'Call the report_status tool with status "ok".'}],
            tools=_TEST_TOOL,
            tool_choice={"type": "function", "function": {"name": "report_status"}},
            max_tokens=64,
        )
        if result.tool_calls:
            tool_call = TestConnectionCheck(
                ok=True, detail=f"Tool call received: {result.tool_calls[0].name}"
            )
        else:
            tool_call = TestConnectionCheck(
                ok=False,
                detail=(
                    "The model returned a reply but made no tool call — this model "
                    "likely can't tool-call, which the assistants require."
                ),
            )
    except AiProviderError as exc:
        tool_call = TestConnectionCheck(ok=False, detail=str(exc)[:300])

    return TestConnectionResult(
        completion=completion, tool_call=tool_call, model=config.model
    )


@router.post("/test-connection", response_model=TestConnectionResult)
async def test_connection(
    current_user: User = Depends(require_permission("manage_ai")),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResult:
    """Probe the *saved* provider config: a trivial completion and a forced tool
    call, so an operator can validate the endpoint (and that the model can
    tool-call) before an event rather than during one."""
    settings = await db.scalar(
        select(AiSettings)
        .options(undefer(AiSettings.api_key))
        .where(AiSettings.id == AI_SETTINGS_ID)
    )
    if settings is None or not settings.base_url or not settings.model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a base URL and model before testing the connection",
        )
    return await _run_test_connection(config_from_settings(settings))
