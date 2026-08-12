"""Core-aware worker-count computation (#189 Phase 3).

The count must come from the *container's* cgroup CPU quota, not the host CPU
count, or a CPU-capped container on a big host spawns far too many workers.
"""

from workers import compute_worker_count, detect_cpu_quota


def _reader(files: dict[str, str]):
    return lambda path: files.get(path)


def test_cgroup_v2_quota_is_read_as_cores():
    # "400000 100000" = 4 cores.
    read = _reader({"/sys/fs/cgroup/cpu.max": "400000 100000"})
    assert detect_cpu_quota(read) == 4.0


def test_cgroup_v2_max_is_unconstrained():
    read = _reader({"/sys/fs/cgroup/cpu.max": "max 100000"})
    assert detect_cpu_quota(read) is None


def test_cgroup_v1_quota_is_read_as_cores():
    read = _reader(
        {
            "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "600000",
            "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
        }
    )
    assert detect_cpu_quota(read) == 6.0


def test_cgroup_v1_unlimited_quota_is_none():
    read = _reader(
        {
            "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "-1",
            "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
        }
    )
    assert detect_cpu_quota(read) is None


def test_worker_count_reserves_cores_and_uses_the_quota():
    # 8-core quota → reserve 2 → 6 workers.
    read = _reader({"/sys/fs/cgroup/cpu.max": "800000 100000"})
    assert compute_worker_count(read=read) == 6


def test_worker_count_is_capped():
    # 64-core quota → clamped to the max, not 62.
    read = _reader({"/sys/fs/cgroup/cpu.max": "6400000 100000"})
    assert compute_worker_count(read=read) == 8


def test_worker_count_floor_is_one_on_a_tiny_box():
    # 2 cores → 2 - 2 reserved → clamps up to 1, never 0.
    read = _reader({"/sys/fs/cgroup/cpu.max": "200000 100000"})
    assert compute_worker_count(read=read) == 1


def test_no_quota_falls_back_to_host_cpu_count():
    read = _reader({})  # no cgroup files
    assert compute_worker_count(read=read, cpu_count=lambda: 4) == 2
    assert compute_worker_count(read=read, cpu_count=lambda: None) == 1
