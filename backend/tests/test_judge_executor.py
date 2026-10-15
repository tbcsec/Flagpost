"""The judge executor contract and the docker kind, without a daemon (#448).

A fake Docker API (``httpx.MockTransport``) plays the daemon: it unpacks the
uploaded archive, and its "container" answers with a result line carrying the
nonce from the uploaded job file — so the whole create → upload → start → wait
→ logs → delete path is exercised, including the security-relevant parts of
what's sent: the container's privileges, and who can read which file. The real
daemon run is ``test_judge_executor_e2e.py``.
"""

import io
import json
import tarfile
from types import SimpleNamespace

import httpx
import pytest

from utils.judge_executor import (
    JudgeExecutorError,
    JudgeTest,
    UnknownJudgeExecutorKind,
    executor_for,
    judge_executor_kind,
    make_job,
)
from utils.judge_executor_docker import (
    LABEL_JUDGE,
    DockerJudgeExecutor,
    JudgeDockerConfig,
    build_archive,
    demux_logs,
    parse_result,
)
from utils.provisioner_docker import LABEL_MANAGED

HARNESS = b"\x7fELF fake harness"


def _job(**over):
    base = dict(
        judging_id="j1",
        image_ref="python:3.14-slim",
        source_filename="solution.py",
        source=b"print(int(input()) * 2)\n",
        compile_command=["python3", "-m", "py_compile", "{source}"],
        run_command=["python3", "{source}"],
        time_multiplier=1.5,
        time_limit_ms=1000,
        memory_limit_mb=256,
        output_limit_kb=1024,
        compare_mode="token",
        float_tolerance=1e-6,
        tests=[
            JudgeTest(sample=True, input=b"1\n", answer=b"2\n"),
            JudgeTest(sample=False, input=b"21\n", answer=b"42\n"),
            JudgeTest(sample=False, input=b"5\n", answer=b"10\n"),
        ],
    )
    base.update(over)
    return make_job(**base)


def _frame(stream: int, data: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data


def _untar(content: bytes) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(fileobj=io.BytesIO(content)) as tar:
        return {m.name: (m, tar.extractfile(m).read() if m.isfile() else None) for m in tar}


class FakeDaemon:
    """Answers the judge's Docker API calls. ``result`` builds the harness's
    result document from the uploaded job; override the knobs to inject
    failures."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.image_present = True
        self.fail: dict[str, int] = {}
        self.archive: dict | None = None
        self.result = lambda job: {
            "nonce": job["nonce"],
            "verdict": "accepted",
            "compile_output": "",
            "compile_time_ms": 12,
            "tests": [
                {"name": t["name"], "verdict": "accepted", "time_ms": 5, "wall_ms": 9,
                 "memory_kb": 1024 * (i + 1), "exit_code": 0, "signal": None}
                for i, t in enumerate(job["tests"])
            ],
        }
        self.log_prefix = b""

    def job(self) -> dict:
        return json.loads(self.archive["judge/job.json"][1])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        for key, code in self.fail.items():
            m, _, frag = key.partition(" ")
            if m == method and frag in path:
                return httpx.Response(code, json={"message": f"injected {code}"})
        if path == "/version":
            return httpx.Response(200, json={"Arch": "amd64"})
        if method == "GET" and path.startswith("/images/"):
            return httpx.Response(200 if self.image_present else 404, json={})
        if path == "/images/create":
            return httpx.Response(200, content=b'{"status":"Status: Downloaded newer image"}\n')
        if path == "/containers/create":
            return httpx.Response(201, json={"Id": "c123"})
        if method == "PUT" and path.endswith("/archive"):
            self.archive = _untar(request.content)
            return httpx.Response(200)
        if path.endswith("/start"):
            return httpx.Response(204)
        if path.endswith("/wait"):
            return httpx.Response(200, json={"StatusCode": 0})
        if path.endswith("/logs"):
            line = json.dumps(self.result(self.job())).encode() + b"\n"
            return httpx.Response(200, content=_frame(2, b"harness log\n") + _frame(1, self.log_prefix + line))
        if method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(500, json={"message": f"unrouted {method} {path}"})

    def executor(self) -> DockerJudgeExecutor:
        return DockerJudgeExecutor(
            JudgeDockerConfig(endpoint_url="http://judge-proxy:2375"),
            transport=httpx.MockTransport(self.handler),
            harness_loader=lambda arch: HARNESS,
        )

    def calls(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]

    def create_body(self) -> dict:
        for r in self.requests:
            if r.url.path == "/containers/create":
                return json.loads(r.content)
        raise AssertionError("no create")


# --- building a job -------------------------------------------------------------


def test_make_job_substitutes_placeholders_and_scales_time():
    job = _job(compile_command=["gcc", "-o", "{work}/main", "{source}"], run_command=["{work}/main"])
    assert job.compile_command == ("gcc", "-o", "/work/main", "/submission/solution.py")
    assert job.run_command == ("/work/main",)
    assert job.time_limit_ms == 1500  # 1000ms × the language's 1.5 multiplier
    assert _job(compile_command=None).compile_command is None


@pytest.mark.parametrize("name", ["../x.py", "a/b.py", "", ".."])
def test_make_job_rejects_a_path_as_filename(name):
    with pytest.raises(JudgeExecutorError):
        _job(source_filename=name)


def test_registry_lookup():
    assert judge_executor_kind("docker") is DockerJudgeExecutor
    with pytest.raises(UnknownJudgeExecutorKind):
        judge_executor_kind("kubernetes")
    settings = SimpleNamespace(executor="docker", endpoint_url="http://proxy:2375/")
    executor = executor_for(settings)
    assert isinstance(executor, DockerJudgeExecutor)
    assert executor._cfg.endpoint_url == "http://proxy:2375"
    with pytest.raises(JudgeExecutorError):
        executor_for(SimpleNamespace(executor="docker", endpoint_url=None))


# --- what goes into the container ------------------------------------------------


def test_archive_keeps_job_and_test_data_root_only():
    files = _untar(build_archive(_job(), HARNESS, "nonce123", 123456))
    modes = {name: (info.mode, info.uid, info.gid) for name, (info, _) in files.items()}
    assert modes["judge"] == (0o700, 0, 0)
    assert modes["judge/harness"] == (0o700, 0, 0)
    assert modes["judge/job.json"] == (0o600, 0, 0)
    assert modes["judge/data"] == (0o700, 0, 0)
    for i in range(3):
        assert modes[f"judge/data/{i:03d}.in"] == (0o600, 0, 0)
        assert modes[f"judge/data/{i:03d}.ans"] == (0o600, 0, 0)
    # The source is the one thing the submission user may read.
    assert modes["submission/solution.py"] == (0o444, 0, 0)
    assert files["judge/data/001.ans"][1] == b"42\n"
    assert files["judge/harness"][1] == HARNESS

    job = json.loads(files["judge/job.json"][1])
    assert job["nonce"] == "nonce123" and job["uid"] == 123456
    assert [t["name"] for t in job["tests"]] == ["sample/001", "secret/001", "secret/002"]
    assert job["run"] == ["python3", "/submission/solution.py"]
    assert job["run_limits"]["cpu_ms"] == 1500
    assert job["run_limits"]["wall_ms"] == 1500 * 3 + 1000
    assert job["run_limits"]["memory_kb"] == 256 * 1024
    assert job["run_limits"]["output_bytes"] == 1024 * 1024
    assert job["scratch"] == ["/work", "/tmp", "/var/tmp", "/dev/shm"]
    assert [t["show_output"] for t in job["tests"]] == [True, False, False]
    assert job["compile_limits"]["memory_kb"] > 0


async def test_container_is_hardened():
    daemon = FakeDaemon()
    await daemon.executor().run(_job())
    body = daemon.create_body()
    host = body["HostConfig"]
    assert body["Entrypoint"] == ["/judge/harness"] and body["User"] == "0:0"
    assert body["NetworkDisabled"] is True and host["NetworkMode"] == "none"
    assert host["CapDrop"] == ["ALL"]
    assert sorted(host["CapAdd"]) == ["KILL", "SETGID", "SETUID"]
    assert host["SecurityOpt"] == ["no-new-privileges:true"]
    assert host["Privileged"] is False
    assert host["Binds"] == [] and host["Mounts"] == []
    assert host["AutoRemove"] is False
    assert host["PidsLimit"] == 256
    assert host["Memory"] == host["MemorySwap"]
    # The scratch dir belongs to this judging's own submission uid — the one
    # named in the job file, from the reserved range above real accounts.
    uid = daemon.job()["uid"]
    assert 100_000 <= uid < 1_100_000
    assert "exec" in host["Tmpfs"]["/work"] and f"uid={uid},gid={uid}" in host["Tmpfs"]["/work"]
    assert set(host["Tmpfs"]) == {"/work", "/tmp", "/var/tmp"}
    assert host["ShmSize"] == 64 * 1024 * 1024  # counted as scratch, see job_document
    assert host["LogConfig"]["Type"] == "json-file"
    # Never instancing's label: its reaper deletes managed containers it has
    # no row for, which would kill a judging mid-run.
    assert LABEL_MANAGED not in body["Labels"]
    assert body["Labels"][LABEL_JUDGE] == "true"


# --- running ----------------------------------------------------------------------


async def test_run_round_trip():
    daemon = FakeDaemon()
    result = await daemon.executor().run(_job())
    assert result.verdict == "accepted"
    assert [t.sample for t in result.tests] == [True, False, False]
    assert result.max_memory_kb == 3072 and result.compile_time_ms == 12
    assert daemon.calls() == [
        "GET /version",
        "GET /images/python:3.14-slim/json",
        "POST /containers/create",
        "PUT /containers/c123/archive",
        "POST /containers/c123/start",
        "POST /containers/c123/wait",
        "GET /containers/c123/logs",
        "DELETE /containers/c123",
    ]


async def test_absent_image_is_pulled_present_image_is_not():
    daemon = FakeDaemon()
    await daemon.executor().run(_job())
    assert "POST /images/create" not in daemon.calls()
    daemon = FakeDaemon()
    daemon.image_present = False
    await daemon.executor().run(_job())
    assert "POST /images/create" in daemon.calls()


async def test_harness_verdicts_pass_through():
    daemon = FakeDaemon()
    daemon.result = lambda job: {
        "nonce": job["nonce"], "verdict": "compile_error",
        "compile_output": "SyntaxError: bad", "tests": [],
    }
    result = await daemon.executor().run(_job())
    assert result.verdict == "compile_error" and result.compile_output == "SyntaxError: bad"
    assert result.tests == ()


async def test_a_line_without_the_nonce_is_not_a_result():
    daemon = FakeDaemon()
    daemon.result = lambda job: {"nonce": "forged", "verdict": "accepted", "tests": []}
    with pytest.raises(JudgeExecutorError, match="no result"):
        await daemon.executor().run(_job())
    assert "DELETE /containers/c123" in daemon.calls()


async def test_the_last_nonced_line_wins_over_earlier_noise():
    daemon = FakeDaemon()
    daemon.log_prefix = b'not json\n{"nonce": "forged", "verdict": "accepted"}\n'
    result = await daemon.executor().run(_job())
    assert result.verdict == "accepted" and len(result.tests) == 3


@pytest.mark.parametrize(
    "failure", ["PUT /archive", "POST /start", "POST /wait", "GET /logs"]
)
async def test_container_removed_whatever_fails(failure):
    daemon = FakeDaemon()
    daemon.fail[failure] = 500
    with pytest.raises(JudgeExecutorError):
        await daemon.executor().run(_job())
    assert daemon.calls()[-1] == "DELETE /containers/c123"


async def test_create_failure_is_an_executor_error():
    daemon = FakeDaemon()
    daemon.fail["POST /containers/create"] = 409
    with pytest.raises(JudgeExecutorError, match="create failed"):
        await daemon.executor().run(_job())


async def test_missing_harness_is_reported():
    def missing(arch):
        raise JudgeExecutorError(f"no harness for {arch}")

    executor = DockerJudgeExecutor(
        JudgeDockerConfig(endpoint_url="http://judge-proxy:2375"),
        transport=httpx.MockTransport(FakeDaemon().handler),
        harness_loader=missing,
    )
    with pytest.raises(JudgeExecutorError, match="no harness for amd64"):
        await executor.run(_job())


def test_demux_and_parse():
    out, err = demux_logs(_frame(1, b"a\n") + _frame(2, b"oops\n") + _frame(1, b"b\n"))
    assert out == b"a\nb\n" and err == b"oops\n"
    # A TTY container's log isn't multiplexed: all of it is stdout.
    assert demux_logs(b'{"x": 1}\n') == (b'{"x": 1}\n', b"")
    with pytest.raises(JudgeExecutorError, match="unknown verdict"):
        parse_result(b'{"nonce": "n", "verdict": "pwned"}\n', "n", _job())


# --- check connection ---------------------------------------------------------------


def _proxy_routes(daemon: FakeDaemon, *, restricted: bool = True):
    inner = daemon.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_ping":
            return httpx.Response(200, headers={"Api-Version": "1.47"})
        if request.url.path in ("/exec/flagpost-judge-probe/start", "/volumes", "/build"):
            return httpx.Response(403 if restricted else 200)
        return inner(request)

    return handler


async def test_validate_runs_a_test_judging():
    daemon = FakeDaemon()
    executor = DockerJudgeExecutor(
        JudgeDockerConfig(endpoint_url="http://judge-proxy:2375"),
        transport=httpx.MockTransport(_proxy_routes(daemon)),
        harness_loader=lambda arch: HARNESS,
    )
    legs = await executor.validate()
    assert [(leg.name, leg.ok) for leg in legs] == [
        ("endpoint_reachable", True),
        ("proxy_restricted", True),
        ("harness_available", True),
        ("test_judging", True),
    ]
    assert daemon.create_body()["Image"] == "alpine:3.20"


async def test_validate_stops_at_an_unrestricted_proxy():
    daemon = FakeDaemon()
    executor = DockerJudgeExecutor(
        JudgeDockerConfig(endpoint_url="http://judge-proxy:2375"),
        transport=httpx.MockTransport(_proxy_routes(daemon, restricted=False)),
        harness_loader=lambda arch: HARNESS,
    )
    legs = await executor.validate()
    assert [leg.name for leg in legs] == ["endpoint_reachable", "proxy_restricted"]
    assert not legs[-1].ok
    # Nothing was run against a socket that isn't restricted.
    assert "POST /containers/create" not in daemon.calls()


async def test_validate_reports_a_failed_test_judging():
    daemon = FakeDaemon()
    daemon.result = lambda job: {"nonce": job["nonce"], "verdict": "runtime_error", "tests": []}
    executor = DockerJudgeExecutor(
        JudgeDockerConfig(endpoint_url="http://judge-proxy:2375"),
        transport=httpx.MockTransport(_proxy_routes(daemon)),
        harness_loader=lambda arch: HARNESS,
    )
    legs = await executor.validate()
    assert legs[-1].name == "test_judging" and not legs[-1].ok
    assert "runtime_error" in legs[-1].detail


def test_output_only_for_examples_before_any_hidden_test():
    tests = [
        JudgeTest(sample=True, input=b"1\n", answer=b"2\n"),
        JudgeTest(sample=False, input=b"2\n", answer=b"4\n"),
        JudgeTest(sample=True, input=b"3\n", answer=b"6\n"),
    ]
    job = _job(tests=tests)
    files = _untar(build_archive(job, HARNESS, "n", 123456))
    doc = json.loads(files["judge/job.json"][1])
    # The example after a hidden test gets no output: tests share /work, so it
    # could carry what the submission saw in the hidden one.
    assert [t["show_output"] for t in doc["tests"]] == [True, False, False]
    # And output reported against a hidden test is dropped on parsing anyway.
    line = json.dumps({
        "nonce": "n", "verdict": "accepted",
        "tests": [{"verdict": "accepted", "output": "2"}, {"verdict": "accepted", "output": "leak"}],
    }).encode()
    result = parse_result(line, "n", job)
    assert result.tests[0].output == "2" and result.tests[1].output is None


async def test_cleanup_never_cuts_a_live_judging_short():
    """The sweep may share its endpoint with another worker or another
    install, so it removes only what can't be anyone's live judging."""
    import time as _time

    now = _time.time()
    listed = [
        # Live here: kept whatever its age.
        {"Id": "live", "State": "running", "Created": now - 999_999, "Labels": {"io.flagpost.judging_id": "j-live"}},
        # Running, not ours, young: maybe another install's judging — kept.
        {"Id": "foreign", "State": "running", "Created": now - 600, "Labels": {"io.flagpost.judging_id": "x"}},
        # Running for hours: wedged — removed.
        {"Id": "wedged", "State": "running", "Created": now - 7 * 3600, "Labels": {"io.flagpost.judging_id": "y"}},
        # Exited just now: its executor may be reading the logs — kept.
        {"Id": "fresh", "State": "exited", "Created": now - 60, "Labels": {"io.flagpost.judging_id": "z"}},
        # Exited long ago: a crashed worker's leftover — removed.
        {"Id": "stale", "State": "exited", "Created": now - 3600, "Labels": {"io.flagpost.judging_id": "w"}},
    ]
    daemon = FakeDaemon()
    inner = daemon.handler

    def handler(request):
        if request.method == "GET" and request.url.path == "/containers/json":
            daemon.requests.append(request)
            assert "io.flagpost.judge=true" in request.url.params["filters"]
            return httpx.Response(200, json=listed)
        return inner(request)

    executor = DockerJudgeExecutor(
        JudgeDockerConfig(endpoint_url="http://judge-proxy:2375"),
        transport=httpx.MockTransport(handler),
        harness_loader=lambda arch: HARNESS,
    )
    assert await executor.cleanup(keep={"j-live"}) == 2
    removed = sorted(r.url.path for r in daemon.requests if r.method == "DELETE")
    assert removed == ["/containers/stale", "/containers/wedged"]
