"""Password hashing: argon2 params, bounded executors, backward compat (#207).

The multi-worker validation (docs/load-testing/2026-08-12-multiworker-validation.md)
found the login storm oversubscribed cores: N workers each ran argon2 (p=4) on
asyncio.to_thread's ~min(32,cpu+4)-thread default pool. The fix is p=1 + two
bounded executors (login-slice vs bulk).
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from auth import security
from config import settings


def test_argon2_uses_parallelism_one():
    # p=1 is the OWASP server config. m/t are compared against `settings` rather
    # than literals because the suite runs argon2 at a reduced cost (conftest);
    # what this asserts is that the hasher actually uses the configured params.
    # The *shipped* values are pinned by the test below.
    h = security.hash_password("correct horse")
    assert "$argon2id$" in h
    import re

    m = re.search(r"m=(\d+),t=(\d+),p=(\d+)", h)
    memory, time_cost, parallelism = (int(x) for x in m.groups())
    assert parallelism == settings.argon2_parallelism == 1
    assert memory == settings.argon2_memory_cost
    assert time_cost == settings.argon2_time_cost


def test_production_argon2_defaults_are_strong():
    """The cost reduction in conftest must never leak into what ships.

    Reads the *declared* field defaults, which no environment variable can
    change, so this keeps asserting the production posture (pwdlib's recommended
    64 MiB / t=3, well above OWASP's minimum) even though the suite itself runs
    the KDF cheaply. Without this, weakening the test environment would silently
    delete the only coverage of the real parameters.
    """
    from config import Settings

    fields = Settings.model_fields
    assert fields["argon2_memory_cost"].default == 65536  # KiB = 64 MiB
    assert fields["argon2_time_cost"].default == 3
    assert fields["argon2_parallelism"].default == 1


def test_verifies_a_legacy_p4_hash():
    # Existing hashes were written with pwdlib's default p=4; they must still
    # verify (argon2 reads params from the encoded hash), or the p=1 switch would
    # lock every existing user out.
    from pwdlib import PasswordHash
    from pwdlib.hashers.argon2 import Argon2Hasher

    legacy = PasswordHash((Argon2Hasher(memory_cost=65536, time_cost=3, parallelism=4),))
    old_hash = legacy.hash("hunter2")
    assert security.verify_password("hunter2", old_hash) is True
    assert security.verify_password("wrong", old_hash) is False


def test_executors_are_bounded_not_the_default_pool():
    # Both must be bounded ThreadPoolExecutors — the whole point is NOT to use
    # asyncio.to_thread's default ~min(32,cpu+4) pool that oversubscribes.
    assert isinstance(security._hash_executor, ThreadPoolExecutor)
    assert isinstance(security._bulk_hash_executor, ThreadPoolExecutor)
    # Login pool is the per-worker slice (floor 2 to avoid per-worker
    # head-of-line); total across workers ~= cores.
    assert security._hash_executor._max_workers == max(
        2, security._cores // security._workers
    )
    # Bulk pool gets the whole box (rare admin import).
    assert security._bulk_hash_executor._max_workers == security._cores


async def test_async_helpers_roundtrip():
    h = await security.ahash_password("s3cret")
    assert await security.averify_password("s3cret", h) is True
    assert await security.averify_password("nope", h) is False


async def test_ahash_many_preserves_order():
    raws = [f"pw-{i}" for i in range(6)]
    hashes = await security.ahash_many(raws)
    assert len(hashes) == len(raws)
    # Order must match inputs (the import zips hashes back onto its rows).
    for raw, h in zip(raws, hashes):
        assert security.verify_password(raw, h) is True


async def test_ahash_many_empty_is_noop():
    assert await security.ahash_many([]) == []
