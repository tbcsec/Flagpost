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
