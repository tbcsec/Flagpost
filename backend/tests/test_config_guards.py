"""Startup guards in `config.Settings` that stop an insecure deployment booting.

These construct `Settings` directly rather than going through the app: the point
is the validator, and importing the app would use the process-wide instance that
was already built from the test environment.
"""

import pytest

from config import Settings, _endpoint_host, _is_loopback

_MINIO_DEFAULTS = {"minio_access_key": "minioadmin", "minio_secret_key": "minioadmin"}


def test_default_minio_credentials_are_fine_for_a_local_run():
    """`docker compose up` with no .env must keep working."""
    assert Settings(public_base_url="http://localhost:8080", **_MINIO_DEFAULTS)
    assert Settings(public_base_url="http://127.0.0.1:8080", **_MINIO_DEFAULTS)
    # A native `uvicorn` run leaves it unset entirely.
    assert Settings(public_base_url="", **_MINIO_DEFAULTS)


def test_default_minio_credentials_are_refused_on_a_real_deployment():
    """The vulnerable shape: reachable install, published-default object store.

    MinIO's S3 API is published on the host so browsers can fetch signed
    attachment URLs, so defaults here mean world read/write on every challenge
    attachment — including unreleased challenges — outside RBAC entirely.
    """
    with pytest.raises(ValueError, match="default credentials"):
        Settings(public_base_url="https://ctf.example.com", **_MINIO_DEFAULTS)


def test_either_half_of_the_default_pair_is_enough_to_refuse():
    with pytest.raises(ValueError, match="default credentials"):
        Settings(
            public_base_url="https://ctf.example.com",
            minio_access_key="minioadmin",
            minio_secret_key="a-real-secret",
        )
    with pytest.raises(ValueError, match="default credentials"):
        Settings(
            public_base_url="https://ctf.example.com",
            minio_access_key="a-real-user",
            minio_secret_key="",
        )


def test_exposed_minio_is_caught_even_when_public_base_url_is_unset():
    """The SITE_ADDRESS-only operator, who never sets PUBLIC_ORIGIN.

    Their deployment is reachable but `public_base_url` still says localhost.
    MINIO_PUBLIC_ENDPOINT gives them away: remote attachment downloads don't
    work without it, so setting it means browsers reach the object store.
    """
    with pytest.raises(ValueError, match="MINIO_PUBLIC_ENDPOINT"):
        Settings(
            public_base_url="http://localhost:8080",
            minio_public_endpoint="files.ctf.example.com",
            **_MINIO_DEFAULTS,
        )


def test_compose_internal_minio_with_no_published_port_is_unaffected():
    """How the demo stack runs: reachable site, object store on the private
    compose network only. `MINIO_PUBLIC_ENDPOINT` is deliberately unset there."""
    assert Settings(
        public_base_url="",
        minio_endpoint="minio:9000",
        minio_public_endpoint=None,
        **_MINIO_DEFAULTS,
    )


def test_real_credentials_deploy_normally():
    settings = Settings(
        public_base_url="https://ctf.example.com",
        minio_access_key="a-real-user",
        minio_secret_key="a-real-secret",
    )
    assert settings.minio_secret_key == "a-real-secret"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("localhost:9000", "localhost"),
        ("https://ctf.example.com", "ctf.example.com"),
        ("https://ctf.example.com/sub/path", "ctf.example.com"),
        ("http://127.0.0.1:8080", "127.0.0.1"),
        ("[::1]:9000", "::1"),
        ("minio", "minio"),
        ("", ""),
    ],
)
def test_endpoint_host_parsing(value, expected):
    assert _endpoint_host(value) == expected


@pytest.mark.parametrize(
    "host,expected",
    [
        ("localhost", True),
        ("LocalHost", True),
        ("app.localhost", True),
        ("127.0.0.1", True),
        ("127.1.2.3", True),  # all of 127/8 is loopback
        ("::1", True),
        ("", True),  # unset — a native dev run
        ("ctf.example.com", False),
        ("203.0.113.5", False),
        # Not loopback, but not routable either: a compose-internal name. It is
        # deliberately treated as a real deployment, since the guard cannot see
        # whether the port is published and refusing is the safe direction.
        ("minio", False),
    ],
)
def test_loopback_detection(host, expected):
    assert _is_loopback(host) is expected
