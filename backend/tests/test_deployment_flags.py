"""Multi-instance deployment flags (ADR-0031).

SCHEDULER_ENABLED, MULTI_INSTANCE and MINIO_IAM_AUTH exist so N app tasks
behind a load balancer (ECS/Fargate + ALB) can split the singleton scheduler
into its own service, keep the Redis relay on regardless of per-task worker
count, and authenticate to S3 with role credentials. These tests pin the gate
logic; the guard interplay lives in test_config_guards, the wire behaviour of
the relay itself in test_realtime_relay.
"""

import pytest

from config import Settings, settings
from realtime import start_realtime
from storage import minio_storage as ms
from utils.automation_scheduler import runs_in_process


def _settings(**overrides) -> Settings:
    # Direct construction, like test_config_guards: the point is the flag
    # logic, not the process-wide instance built from the test environment.
    return Settings(**overrides)


# --- SCHEDULER_ENABLED ------------------------------------------------------


def test_scheduler_runs_in_process_only_when_single_worker_and_enabled():
    assert runs_in_process(_settings(scheduler_enabled=True, web_concurrency=1))


def test_scheduler_skipped_in_process_under_multi_worker():
    # The entrypoint's sidecar owns it there.
    assert not runs_in_process(_settings(scheduler_enabled=True, web_concurrency=4))


def test_scheduler_disabled_means_no_in_process_scheduler():
    # The ADR-0031 web-task shape: a dedicated `python -m scheduler` service
    # is the one scheduler; this process must not start a second one.
    assert not runs_in_process(_settings(scheduler_enabled=False, web_concurrency=1))


def test_scheduler_enabled_parses_env_style_strings():
    assert _settings(scheduler_enabled="false").scheduler_enabled is False
    assert _settings(scheduler_enabled="true").scheduler_enabled is True


# --- MULTI_INSTANCE ---------------------------------------------------------


async def test_multi_instance_without_redis_refuses_to_start(monkeypatch):
    """N tasks that can't relay would silently drop broadcasts to each other's
    clients — the failure must be a loud startup error instead."""
    monkeypatch.setattr(settings, "web_concurrency", 1)
    monkeypatch.setattr(settings, "multi_instance", True)
    monkeypatch.setattr(settings, "redis_url", None)
    with pytest.raises(RuntimeError, match="MULTI_INSTANCE"):
        await start_realtime()


async def test_single_worker_single_instance_stays_a_no_op(monkeypatch):
    # Today's default topology: no Redis required, nothing to wire.
    monkeypatch.setattr(settings, "web_concurrency", 1)
    monkeypatch.setattr(settings, "multi_instance", False)
    monkeypatch.setattr(settings, "redis_url", None)
    await start_realtime()  # returns without raising, attaches nothing


# --- MINIO_IAM_AUTH ---------------------------------------------------------


class _RecordingMinio:
    calls: list[tuple[str, dict]] = []

    def __init__(self, endpoint, **kwargs):
        _RecordingMinio.calls.append((endpoint, kwargs))

    def bucket_exists(self, bucket):  # _ensure_bucket probe
        return True


@pytest.fixture
def recording_minio(monkeypatch):
    _RecordingMinio.calls = []
    monkeypatch.setattr(ms, "Minio", _RecordingMinio)
    return _RecordingMinio


def test_iam_auth_passes_one_shared_provider_and_no_static_keys(
    recording_minio, monkeypatch
):
    monkeypatch.setattr(ms.settings, "minio_iam_auth", True)
    ms.MinioStorage()
    assert len(recording_minio.calls) == 2  # internal + presign clients
    for _endpoint, kwargs in recording_minio.calls:
        assert isinstance(kwargs["credentials"], ms.IamAwsProvider)
        assert "access_key" not in kwargs and "secret_key" not in kwargs
    # One provider instance for both clients: role credentials are fetched and
    # cached once, not once per client.
    assert (
        recording_minio.calls[0][1]["credentials"]
        is recording_minio.calls[1][1]["credentials"]
    )


def test_static_keys_remain_the_default(recording_minio, monkeypatch):
    monkeypatch.setattr(ms.settings, "minio_iam_auth", False)
    ms.MinioStorage()
    for _endpoint, kwargs in recording_minio.calls:
        assert "credentials" not in kwargs
        assert kwargs["access_key"] == ms.settings.minio_access_key
