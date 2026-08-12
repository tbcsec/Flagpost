"""Core-aware worker-count computation (#189 Phase 3, ADR-0025).

Picks a uvicorn ``--workers`` value from the *container's* CPU allowance, not the
host's. The naive ``os.cpu_count()`` reads the host — a backend capped at 2 CPUs
on a 64-core box would otherwise spawn dozens of workers. So read the cgroup CPU
quota first (v2 then v1), fall back to ``os.cpu_count()`` only when there's no
quota, then reserve headroom for the co-located Postgres/Caddy/frontend on an
all-in-one box and clamp — past a point Postgres's write path is the wall, not
more event loops (see docs/load-testing/2026-08-12-500user-multicomp.md).

The reader is injectable so the clamp logic is unit-testable without a cgroup.
"""

from __future__ import annotations

import os

# Reserve cores for everything else on the box (an all-in-one docker-compose
# runs Postgres, Caddy, the frontend and Redis alongside the backend).
_RESERVED_CORES = 2
# Beyond this, Postgres becomes the binding constraint before more workers help;
# a hard cap also stops a huge host spawning a pool-exhausting worker count.
_MAX_WORKERS = 8


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def detect_cpu_quota(read=_read) -> float | None:
    """The container's CPU allowance in cores, or None if unconstrained.

    cgroup v2: ``/sys/fs/cgroup/cpu.max`` = ``"<quota_us> <period_us>"`` or
    ``"max <period_us>"``. cgroup v1: ``cpu.cfs_quota_us`` (-1 = unlimited) over
    ``cpu.cfs_period_us``.
    """
    v2 = read("/sys/fs/cgroup/cpu.max")
    if v2:
        parts = v2.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                quota, period = int(parts[0]), int(parts[1])
                if quota > 0 and period > 0:
                    return quota / period
            except ValueError:
                pass
        return None  # "max <period>" ⇒ unconstrained

    quota_s = read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period_s = read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if quota_s and period_s:
        try:
            quota, period = int(quota_s), int(period_s)
            if quota > 0 and period > 0:
                return quota / period
        except ValueError:
            pass
    return None


def compute_worker_count(read=_read, cpu_count=os.cpu_count) -> int:
    """The core-aware default worker count: ``clamp(cores - reserved, 1, max)``.

    ``cores`` is the cgroup quota when set, else the (host) CPU count. Always at
    least 1, so a tiny box or a missing quota degrades to single-worker.
    """
    quota = detect_cpu_quota(read)
    cores = quota if quota is not None else (cpu_count() or 1)
    workers = int(cores) - _RESERVED_CORES
    return max(1, min(_MAX_WORKERS, workers))
