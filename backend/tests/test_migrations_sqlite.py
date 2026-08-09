"""SQLite migration-cycle regression (#7).

The schema tests build from ``Base.metadata`` (ADR-0006), so they never exercise
the migration chain — yet a SQLite ``batch_alter_table`` rebuild silently drops
expression/partial indexes. This drives the real alembic CLI against a throwaway
SQLite DB to prove the two affected indexes survive an upgrade → (rebuild-crossing)
downgrade → upgrade cycle, and that a full ``downgrade base`` no longer wedges.
Runs the CLI in a subprocess so it can't collide with the suite's event loop / DB.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
# A revision below the mc_penalty migration whose downgrade rebuilds `submissions`.
_BELOW_SUBMISSIONS_REBUILD = "d5b3e2c9a710"


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


def _indexes(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
    finally:
        conn.close()


def test_sqlite_expression_indexes_survive_batch_rebuild_cycle(tmp_path):
    db = tmp_path / "mig.db"
    url = f"sqlite+aiosqlite:///{db}"

    up = _alembic(url, "upgrade", "head")
    if up.returncode != 0 and "No module named alembic" in up.stderr:
        pytest.skip("alembic CLI unavailable")
    assert up.returncode == 0, up.stderr
    idx = _indexes(db)
    assert "uq_submissions_awarded_subject" in idx
    assert "uq_users_display_name_lower" in idx

    # Downgrading past the mc_penalty migration rebuilds `submissions`, which on
    # SQLite drops the partial/expression index (reflection can't recreate it).
    down = _alembic(url, "downgrade", _BELOW_SUBMISSIONS_REBUILD)
    assert down.returncode == 0, down.stderr
    assert "uq_submissions_awarded_subject" not in _indexes(db)

    # Upgrading to head heals it via the corrective migration.
    up2 = _alembic(url, "upgrade", "head")
    assert up2.returncode == 0, up2.stderr
    assert "uq_submissions_awarded_subject" in _indexes(db)

    # A full downgrade must not wedge on the now-absent index (tolerant drops).
    base = _alembic(url, "downgrade", "base")
    assert base.returncode == 0, base.stderr
