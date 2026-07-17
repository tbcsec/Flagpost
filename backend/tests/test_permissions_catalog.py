"""Guard: every ``require_permission("x")`` references a real catalog key.

ADR-0004's accepted cost of roles-as-data is that a typo'd permission string
fails silently (a 403) rather than failing to compile. This test is the
lint/test step that ADR asks for: it scans the backend source for
``require_permission("...")`` call sites and asserts each string exists in the
catalog (auth/permissions.py). Also asserts the seeded role sets only
reference real keys.
"""

import re
from pathlib import Path

from auth.permissions import ALL_PERMISSION_KEYS
from auth.seed import SYSTEM_ROLE_SPECS

BACKEND_ROOT = Path(__file__).resolve().parent.parent
# Match the canonical route usage `Depends(require_permission("key"))` so prose
# examples of require_permission("x") in docstrings aren't treated as call sites.
CALL_RE = re.compile(
    r"""Depends\(\s*require_permission\(\s*["']([^"']+)["']"""
)


def test_all_require_permission_call_sites_reference_known_keys():
    offenders: list[str] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if ".venv" in path.parts or path.name.startswith("test_"):
            continue
        for match in CALL_RE.finditer(path.read_text()):
            key = match.group(1)
            if key not in ALL_PERMISSION_KEYS:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {key!r}")
    assert not offenders, "Unknown permission keys in require_permission():\n" + "\n".join(
        offenders
    )


def test_seeded_roles_only_reference_known_keys():
    for spec in SYSTEM_ROLE_SPECS:
        unknown = set(spec["permissions"]) - ALL_PERMISSION_KEYS
        assert not unknown, f"Role {spec['name']} references unknown keys: {unknown}"
