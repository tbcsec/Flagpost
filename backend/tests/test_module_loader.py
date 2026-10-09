"""Module loader: discovery, dependency resolution, mounting (§11.1)."""

from dataclasses import replace

import pytest

from plugins.loader import (
    ModuleError,
    ModuleManifest,
    discover_manifests,
    parse_manifest,
    resolve_load_order,
)


def _m(id: str, deps: list[str] | None = None, required_core: bool = True) -> ModuleManifest:
    return ModuleManifest(
        id=id,
        name=id.title(),
        version="1.0.0",
        required_core=required_core,
        provides_routes=True,
        dependencies=deps or [],
    )


def test_parse_manifest_reads_provides_and_defaults():
    manifest = parse_manifest(
        {
            "id": "challenges",
            "name": "Challenges",
            "version": "1.0.0",
            "required_core": True,
            "provides": {"routes": True, "event_listeners": True},
            "dependencies": ["competitions"],
        }
    )
    assert manifest.id == "challenges"
    assert manifest.provides_routes is True
    assert manifest.provides_event_listeners is True
    assert manifest.dependencies == ["competitions"]


def test_parse_manifest_missing_field_is_an_error():
    with pytest.raises(ModuleError):
        parse_manifest({"name": "no id", "version": "1.0.0"})


# --- Manifest v2 validation (ADR-0040, plugins/manifest.py) -----------------


def test_parse_manifest_v2_code_module_exposes_new_fields():
    m = parse_manifest(
        {
            "manifest_version": 2,
            "id": "acme.slack-notifier",
            "name": "ACME Slack Notifier",
            "version": "1.2.0",
            "kind": "module",
            "trust_tier": "code",
            "publisher": {"id": "acme", "name": "ACME Security"},
            "requires_flagpost": {"min": "1.7.0"},
            "provides": {"routes": True, "event_listeners": True},
            "capabilities": ["network.egress", "events.subscribe"],
        }
    )
    assert m.kind == "module"
    assert m.trust_tier == "code"
    assert m.capabilities == ["network.egress", "events.subscribe"]
    assert m.provides_routes is True


def test_parse_manifest_v2_pack():
    m = parse_manifest(
        {
            "manifest_version": 2,
            "id": "acme.web-101",
            "name": "Web 101",
            "version": "1.0.0",
            "kind": "pack",
            "pack": {"pack_type": "challenges", "target": "competition"},
        }
    )
    assert m.kind == "pack"
    assert m.trust_tier is None


def test_v1_legacy_manifest_defaults_to_trusted_module():
    # No manifest_version / kind / trust_tier — the in-box shape. Validated
    # leniently as first-party code (kind defaults to module, trust_tier None).
    m = parse_manifest({"id": "legacy", "name": "Legacy", "version": "1.0.0"})
    assert m.kind == "module"
    assert m.trust_tier is None


def test_parse_manifest_rejects_module_without_trust_tier():
    with pytest.raises(ModuleError, match="trust_tier"):
        parse_manifest(
            {"manifest_version": 2, "id": "x", "name": "X", "version": "1.0.0", "kind": "module"}
        )


def test_parse_manifest_rejects_pack_without_body():
    with pytest.raises(ModuleError, match="pack"):
        parse_manifest(
            {"manifest_version": 2, "id": "x", "name": "X", "version": "1.0.0", "kind": "pack"}
        )


def test_parse_manifest_rejects_declarative_requesting_code_capability():
    with pytest.raises(ModuleError, match="code-only"):
        parse_manifest(
            {
                "id": "x",
                "name": "X",
                "version": "1.0.0",
                "kind": "module",
                "trust_tier": "declarative",
                "capabilities": ["network.egress"],
            }
        )


def test_parse_manifest_rejects_unknown_capability():
    with pytest.raises(ModuleError):
        parse_manifest(
            {
                "id": "x",
                "name": "X",
                "version": "1.0.0",
                "kind": "module",
                "trust_tier": "code",
                "capabilities": ["rm -rf"],
            }
        )


def test_parse_manifest_rejects_unknown_key():
    # extra="forbid": a typo'd field fails closed rather than being silently ignored.
    with pytest.raises(ModuleError, match="frobnicate"):
        parse_manifest({"id": "x", "name": "X", "version": "1.0.0", "frobnicate": True})


def test_parse_manifest_rejects_sandboxed_tier_as_reserved():
    with pytest.raises(ModuleError, match="sandboxed"):
        parse_manifest(
            {
                "manifest_version": 2,
                "id": "x",
                "name": "X",
                "version": "1.0.0",
                "kind": "module",
                "trust_tier": "sandboxed",
            }
        )


def test_parse_manifest_rejects_bad_id_pattern():
    with pytest.raises(ModuleError, match="id"):
        parse_manifest({"id": "BAD ID", "name": "X", "version": "1.0.0"})


def test_all_inbox_manifests_validate():
    # Every real on-disk manifest must pass manifest-v2 validation — a startup
    # guarantee, since discover_manifests parses each through parse_manifest.
    manifests = discover_manifests()
    assert len(manifests) >= 24
    assert all(m.id and m.kind == "module" for m in manifests)


def test_resolve_load_order_places_dependencies_first():
    # challenges depends on competitions -> competitions must load first,
    # regardless of input ordering.
    order = resolve_load_order([_m("challenges", ["competitions"]), _m("competitions")])
    assert [m.id for m in order].index("competitions") < [
        m.id for m in order
    ].index("challenges")


def test_resolve_load_order_rejects_missing_dependency():
    with pytest.raises(ModuleError, match="missing module"):
        resolve_load_order([_m("challenges", ["competitions"])])


def test_resolve_load_order_rejects_dependency_cycle():
    with pytest.raises(ModuleError, match="cycle"):
        resolve_load_order([_m("a", ["b"]), _m("b", ["a"])])


def test_resolve_load_order_rejects_disabled_dependency(monkeypatch):
    # Simulate a present-but-disabled dependency (what an optional, toggled-off
    # module would look like once disabling exists).
    disabled = _m("optional_dep", required_core=False)
    monkeypatch.setattr(type(disabled), "enabled", property(lambda self: False))
    with pytest.raises(ModuleError, match="disabled module"):
        resolve_load_order([_m("consumer", ["optional_dep"]), disabled])


def test_required_core_is_always_enabled():
    assert _m("competitions", required_core=True).enabled is True


def test_discovery_finds_the_competitions_module():
    # The real on-disk manifest is discovered and parsed.
    ids = {m.id for m in discover_manifests()}
    assert "competitions" in ids


async def test_competitions_routes_are_mounted_via_the_loader(client):
    # main.py loads modules at import; the competitions router is reachable,
    # proving it was mounted through the loader rather than a direct include.
    resp = await client.get("/api/competitions")
    assert resp.status_code == 401  # auth required, but the route exists
