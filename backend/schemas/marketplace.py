"""Marketplace settings schemas (#389, ADR-0040)."""

from __future__ import annotations

import base64

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.marketplace_verify import TRUST_POLICIES

# What ``max_trust_tier`` may be set to (pack < declarative < code). ``sandboxed``
# (Tier 3) is deliberately not selectable — it's reserved/unsupported.
MAX_TRUST_TIERS: tuple[str, ...] = ("pack", "declarative", "code")


class TrustedKeyIn(BaseModel):
    """An operator-added ed25519 public key that extends trust beyond the project
    root key. Public key only — nothing secret."""

    model_config = ConfigDict(extra="forbid")

    key_id: str = Field(min_length=1, max_length=128)
    public_key: str = Field(description="base64 raw ed25519 public key (32 bytes)")
    verified: bool = False
    label: str | None = Field(default=None, max_length=128)

    @field_validator("public_key")
    @classmethod
    def _valid_ed25519(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except Exception as exc:  # noqa: BLE001 - any decode failure is a bad key
            raise ValueError("public_key must be base64") from exc
        if len(raw) != 32:
            raise ValueError("public_key must decode to 32 bytes (raw ed25519)")
        return v


class MarketplaceSettingsOut(BaseModel):
    enabled: bool
    registry_url: str
    trust_policy: str
    max_trust_tier: str
    trusted_keys: list


class MarketplaceSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    registry_url: str | None = Field(default=None, max_length=500)
    trust_policy: str | None = None
    max_trust_tier: str | None = None
    trusted_keys: list[TrustedKeyIn] | None = None

    @field_validator("trust_policy")
    @classmethod
    def _policy(cls, v: str | None) -> str | None:
        if v is not None and v not in TRUST_POLICIES:
            raise ValueError(
                f"trust_policy must be one of {', '.join(TRUST_POLICIES)}"
            )
        return v

    @field_validator("max_trust_tier")
    @classmethod
    def _tier(cls, v: str | None) -> str | None:
        if v is not None and v not in MAX_TRUST_TIERS:
            raise ValueError(
                f"max_trust_tier must be one of {', '.join(MAX_TRUST_TIERS)}"
            )
        return v

    @field_validator("registry_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("registry_url must be an http(s) URL")
        return v
