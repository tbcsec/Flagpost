"""Manifest v2 validation (ADR-0040, docs/MODULES.md §3).

The loader's runtime currency is the lightweight :class:`ModuleManifest`
dataclass in ``loader.py``; this module is the *validation* layer in front of it.
``parse_manifest`` runs a raw ``plugin.yaml`` dict through :class:`ManifestModel`
so a malformed manifest fails closed with a clear error instead of loading a
half-formed module.

This Pydantic model is the backend enforcement of the language-neutral contract
in ``docs/spec/module-manifest.schema.json`` — keep the two in sync. JSON Schema
is the cross-language source of truth (SDK + registry consume it); Pydantic is how
the platform enforces it at load without shipping a JSON-Schema validator
dependency.

**Backwards compatibility.** The in-box required-core manifests are ``manifest_version``
1 (they omit the field, and ``kind``/``trust_tier``/``publisher``): they are treated
as first-party, kernel-trusted code and validated leniently. Anything declaring
``manifest_version: 2`` — every registry-distributed artifact — is validated strictly.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Kind(str, Enum):
    pack = "pack"
    module = "module"


class TrustTier(str, Enum):
    declarative = "declarative"
    code = "code"
    # Tier 3 — reserved for the deferred untrusted-code sandbox (ARCHITECTURE §15).
    # Accepted by the enum so a manifest can *name* it, but rejected in validation
    # because nothing can run it yet.
    sandboxed = "sandboxed"


class Capability(str, Enum):
    network_egress = "network.egress"
    storage_objects = "storage.objects"
    events_emit = "events.emit"
    events_subscribe = "events.subscribe"
    background_tasks = "background.tasks"
    permissions_define = "permissions.define"
    migrations_run = "migrations.run"
    settings_store = "settings.store"
    competition_read = "competition.read"
    competition_write = "competition.write"
    site_settings_read = "site_settings.read"


class PackType(str, Enum):
    challenges = "challenges"
    theme = "theme"
    translations = "translations"
    automation_recipes = "automation-recipes"


class PermissionScope(str, Enum):
    global_ = "global"
    competition = "competition"


class SettingType(str, Enum):
    string = "string"
    text = "text"
    number = "number"
    boolean = "boolean"
    secret = "secret"
    select = "select"
    url = "url"


# Capabilities that imply real backend code — a `declarative` (Tier 1) module may
# not request them (docs/MODULES.md §3.3). Enforced here; the JSON Schema leaves
# this cross-field rule to the loader.
_CODE_ONLY_CAPABILITIES = {
    Capability.network_egress,
    Capability.migrations_run,
    Capability.permissions_define,
}

_ID_PATTERN = r"^[a-z0-9]([a-z0-9_.-]*[a-z0-9])?$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
_PERM_KEY_PATTERN = r"^[A-Z][A-Z0-9_]*$"
_SETTING_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class _Strict(BaseModel):
    """Base: reject unknown keys so a typo fails closed rather than being ignored
    (mirrors ``additionalProperties: false`` in the JSON Schema)."""

    model_config = ConfigDict(extra="forbid")


class Publisher(_Strict):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    url: str | None = None


class RequiresFlagpost(_Strict):
    min: str = Field(pattern=_SEMVER_PATTERN)
    max: str | None = Field(default=None, pattern=_SEMVER_PATTERN)


class Provides(_Strict):
    routes: bool = False
    event_listeners: bool = False
    models: bool = False
    migrations: bool = False


class PermissionDef(_Strict):
    key: str = Field(pattern=_PERM_KEY_PATTERN)
    name: str = Field(min_length=1)
    description: str | None = None
    category: str = Field(min_length=1)
    scope: PermissionScope


class SettingOption(_Strict):
    value: str
    label: str | None = None


class SettingDef(_Strict):
    key: str = Field(pattern=_SETTING_KEY_PATTERN)
    type: SettingType
    label: str | None = None
    description: str | None = None
    default: Any = None
    required: bool = False
    options: list[SettingOption] | None = None


class NavItem(_Strict):
    label: str = Field(min_length=1)
    path: str = Field(pattern=r"^/")
    icon: str | None = None
    scope: Literal["site", "competition"] = "competition"
    required_permissions: list[str] = Field(default_factory=list)


class WidgetDef(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")
    label: str = Field(min_length=1)
    slot: str = "dashboard.widgets"
    data_source: str | None = None
    audiences: list[Literal["organiser", "competitor"]] = Field(default_factory=list)


class ExtensionContribution(_Strict):
    component: str = Field(min_length=1)
    label: str | None = None
    required_permissions: list[str] = Field(default_factory=list)


class PackBody(_Strict):
    pack_type: PackType
    target: Literal["competition", "site"] | None = None


class ManifestModel(_Strict):
    """A validated ``plugin.yaml``. See ``docs/spec/module-manifest.schema.json``."""

    manifest_version: Literal[1, 2] = 1
    id: str = Field(pattern=_ID_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(pattern=_SEMVER_PATTERN)
    description: str = ""
    kind: Kind | None = None
    publisher: Publisher | None = None
    requires_flagpost: RequiresFlagpost | None = None
    dependencies: list[str] = Field(default_factory=list)
    required_core: bool = False
    trust_tier: TrustTier | None = None
    provides: Provides = Field(default_factory=Provides)
    capabilities: list[Capability] = Field(default_factory=list)
    permissions: list[PermissionDef] = Field(default_factory=list)
    settings: list[SettingDef] = Field(default_factory=list)
    nav_items: list[NavItem] = Field(default_factory=list)
    widgets: list[WidgetDef] = Field(default_factory=list)
    extensions: dict[str, list[ExtensionContribution]] = Field(default_factory=dict)
    pack: PackBody | None = None

    @property
    def effective_kind(self) -> Kind:
        """``kind`` with the v1 default applied (a legacy manifest is a module)."""
        return self.kind or Kind.module

    @model_validator(mode="after")
    def _check_tier_rules(self) -> ManifestModel:
        strict = self.manifest_version == 2

        if strict:
            if self.kind is None:
                raise ValueError("manifest_version 2 requires 'kind' (pack|module)")
            if self.kind == Kind.module and self.trust_tier is None:
                raise ValueError("a module requires 'trust_tier' (declarative|code)")
            if self.kind == Kind.pack and self.pack is None:
                raise ValueError("a pack requires a 'pack' body")

        if self.trust_tier == TrustTier.sandboxed:
            raise ValueError(
                "trust_tier 'sandboxed' (Tier 3) is reserved and not yet supported"
            )

        # A declarative module ships no arbitrary backend code, so it may not
        # request the code-only capabilities (docs/MODULES.md §3.3).
        if self.trust_tier == TrustTier.declarative:
            forbidden = _CODE_ONLY_CAPABILITIES.intersection(self.capabilities)
            if forbidden:
                names = ", ".join(sorted(c.value for c in forbidden))
                raise ValueError(
                    f"a declarative module may not request code-only capabilities: {names}"
                )

        # A pack is data, not code — it carries no wiring.
        if self.effective_kind == Kind.pack:
            if self.dependencies:
                raise ValueError("a pack takes no dependencies")
            if (
                self.capabilities
                or self.permissions
                or self.provides.routes
                or self.provides.event_listeners
                or self.provides.migrations
                or self.provides.models
            ):
                raise ValueError(
                    "a pack declares no code (no provides/capabilities/permissions)"
                )
            if self.pack is None:
                raise ValueError("a pack requires a 'pack' body")

        return self
