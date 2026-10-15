"""The ``docker`` judge executor (#448, ADR-0042 §7 and its amendment).

One throwaway container per judging, driven through the same least-privilege
socket proxy posture as Docker instancing (never a raw socket):

    create → PUT archive (harness + job + source + test data) → start →
    wait → read logs → delete

The container has **no network**, and runs the static Go harness
(``backend/judge_harness``) as PID 1 — uid 0 holding only ``SETUID``,
``SETGID`` and ``KILL`` — which compiles once and runs each test as the
unprivileged submission user. It deviates from instancing's hardening recipe
in four deliberate ways, each justified in the ADR amendment: no network, an
exec-able scratch tmpfs, a writable layer (an archive upload into a read-only
rootfs is refused) and those three capabilities. Everything the submission
must not see — the job file and the test data — is uploaded root-only.

Judge containers carry their **own** label, never instancing's
``io.flagpost.managed``: the instance reaper deletes any managed container it
has no row for, which would kill an in-flight judging.

Testability mirrors the instancing kind: every request goes through an
injectable ``httpx.AsyncBaseTransport``, and the harness binary through an
injectable loader, so tests need neither a daemon nor a Go build.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import secrets
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import httpx

from utils.judge_executor import (
    SOURCE_DIR,
    VERDICTS,
    WORK_DIR,
    JudgeExecutor,
    JudgeExecutorError,
    JudgeJob,
    JudgeResult,
    JudgeTest,
    JudgeTestResult,
    make_job,
    register_judge_executor,
)
from utils.provisioner_docker import _daemon_detail, _truncate, pull_image
from utils.provisioners import CheckResult

logger = logging.getLogger(__name__)

LABEL_JUDGE = "io.flagpost.judge"
LABEL_JUDGING = "io.flagpost.judging_id"

JOB_DIR = "/judge"
HARNESS_PATH = f"{JOB_DIR}/harness"
# Each judging's submission runs as its own uid, drawn from a reserved range
# above any real account. The kernel counts a uid's processes host-wide, so with
# one shared uid a fork-heavy submission would eat into a *concurrent* judging's
# process cap and fail its compiler. (Collisions are possible but harmless
# beyond sharing that cap: each container sees only its own processes.)
SUBMISSION_UID_BASE = 100_000
SUBMISSION_UID_SPAN = 1_000_000

# --- resource envelope (ADR-0042 §5) ----------------------------------------------
# The compile step gets a fixed, generous budget: compilers are trusted
# programs, but some (rustc, javac, a cold Go build cache) are slow and hungry.
COMPILE_CPU_MS = 30_000
COMPILE_WALL_MS = 60_000
COMPILE_OUTPUT_BYTES = 64 * 1024
COMPILE_FILE_BYTES = 256 * 1024 * 1024
# The container's memory cap is the hard backstop behind the harness's
# per-test watcher, so it must fit the compile step as well as a run, plus the
# harness and the scratch tmpfs (which counts as memory).
COMPILE_MEMORY_FLOOR_MB = 1024
MEMORY_HEADROOM_MB = 128
WORK_TMPFS_MB = 256
TMP_TMPFS_MB = 64
# Docker's own /dev/shm (another world-writable tmpfs), pinned rather than left
# to the daemon's default.
SHM_MB = 64
# Every writable tmpfs: what a test writes into these lives in memory, so the
# harness counts its growth against the memory limit — /dev/shm included, or it
# would be a place to park data the limit can't see.
SCRATCH_DIRS = [WORK_DIR, "/tmp", "/var/tmp", "/dev/shm"]
# A test may write files, but not fill the scratch space with one.
RUN_FILE_BYTES = 16 * 1024 * 1024
# The wall-clock backstop for a test: CPU time is the real limit; this only
# catches a submission that sleeps or blocks.
RUN_WALL_FACTOR = 3
RUN_WALL_SLACK_MS = 1000
# Twice the harness's per-submission process cap (RLIMIT_NPROC 128), so a fork
# bomb exhausts its own allowance long before the container's, and the
# harness can still start the threads it needs to report.
PIDS_LIMIT = 256
CPUS = 1.0

_TIMEOUT_QUICK = 10.0
_TIMEOUT_LIFECYCLE = 60.0
_TIMEOUT_UPLOAD = 120.0
_TIMEOUT_PULL = 300.0
# Slack on top of the summed per-step limits before the executor gives up on
# a container: covers start-up, image layers and log flushing.
_BUDGET_SLACK_S = 30.0

_DEFAULT_PROBE_IMAGE = "alpine:3.20"

# When cleanup may remove a judge container no live judging claims: a stopped
# one after this long (its executor reads the logs as soon as it exits), and a
# running one only once far past any judging's budget — the harness enforces
# every limit itself, so a container still running this late is wedged.
_ORPHAN_STOPPED_AGE_S = 10 * 60
_ORPHAN_RUNNING_AGE_S = 6 * 60 * 60


def default_harness_dir() -> Path:
    from config import settings

    if settings.judge_harness_dir:
        return Path(settings.judge_harness_dir)
    return Path(__file__).resolve().parent.parent / "judge_harness" / "bin"


def load_harness(arch: str) -> bytes:
    path = default_harness_dir() / f"harness-linux-{arch}"
    try:
        return path.read_bytes()
    except OSError:
        raise JudgeExecutorError(
            f"the judge harness for linux/{arch} isn't installed ({path}) — "
            "the backend image builds it; from a source checkout, run "
            "`make -C backend/judge_harness`"
        ) from None


@dataclass(frozen=True)
class JudgeDockerConfig:
    endpoint_url: str
    probe_image: str = _DEFAULT_PROBE_IMAGE
    extra_headers: dict[str, str] = field(default_factory=dict)


# --- the pieces, as pure functions -------------------------------------------------


def run_wall_ms(time_limit_ms: int) -> int:
    return time_limit_ms * RUN_WALL_FACTOR + RUN_WALL_SLACK_MS


def container_memory_mb(job: JudgeJob) -> int:
    return (
        max(job.memory_limit_mb, COMPILE_MEMORY_FLOOR_MB)
        + MEMORY_HEADROOM_MB
        + WORK_TMPFS_MB
        + 2 * TMP_TMPFS_MB
        + SHM_MB
    )


def time_budget_s(job: JudgeJob) -> float:
    compile_s = COMPILE_WALL_MS / 1000 if job.compile_command else 0
    return compile_s + len(job.tests) * run_wall_ms(job.time_limit_ms) / 1000 + _BUDGET_SLACK_S


def _test_name(job: JudgeJob, index: int) -> str:
    # Position within its group, as in the problem zip: sample/001, secret/001…
    test = job.tests[index]
    n = sum(1 for t in job.tests[: index + 1] if t.sample == test.sample)
    return f"{'sample' if test.sample else 'secret'}/{n:03d}"


def submission_uid() -> int:
    return SUBMISSION_UID_BASE + secrets.randbelow(SUBMISSION_UID_SPAN)


def job_document(job: JudgeJob, nonce: str, uid: int) -> dict[str, Any]:
    tests = []
    # Output comes back only for the leading run of example tests: once a
    # hidden test has run, a later test's output could carry what the
    # submission saw (tests share the scratch directory).
    leading_examples = True
    for i, test in enumerate(job.tests):
        leading_examples = leading_examples and test.sample
        stem = f"{JOB_DIR}/data/{i:03d}"
        tests.append({
            "name": _test_name(job, i),
            "input": f"{stem}.in",
            "answer": f"{stem}.ans",
            "show_output": leading_examples,
        })
    return {
        "nonce": nonce,
        "uid": uid,
        "work": WORK_DIR,
        "scratch": SCRATCH_DIRS,
        "compile": list(job.compile_command) if job.compile_command else None,
        "run": list(job.run_command),
        "compile_limits": {
            "cpu_ms": COMPILE_CPU_MS,
            "wall_ms": COMPILE_WALL_MS,
            # The compiler is trusted, its input isn't: a source crafted to make
            # it balloon gets a compile error, not the container's OOM killer.
            "memory_kb": COMPILE_MEMORY_FLOOR_MB * 1024,
            "output_bytes": COMPILE_OUTPUT_BYTES,
            "file_bytes": COMPILE_FILE_BYTES,
        },
        "run_limits": {
            "cpu_ms": job.time_limit_ms,
            "wall_ms": run_wall_ms(job.time_limit_ms),
            "memory_kb": job.memory_limit_mb * 1024,
            "output_bytes": job.output_limit_kb * 1024,
            "file_bytes": RUN_FILE_BYTES,
        },
        "compare": job.compare_mode,
        "tolerance": job.float_tolerance,
        "tests": tests,
        # A harness older than #450 ignores this and stops at the first
        # failure; the worker notices the missing tests (see _finish).
        "run_all": job.run_all,
    }


def build_archive(job: JudgeJob, harness: bytes, nonce: str, uid: int) -> bytes:
    """The tar uploaded into the container root. Ownership and modes are the
    security boundary: everything under ``/judge`` is root-only (the submission
    user can't read the job, the test data or the harness), while the source is
    world-readable so the compiler — running as the submission user — can."""
    buf = io.BytesIO()
    now = time.time()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:

        def add_dir(name: str, mode: int) -> None:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode, info.uid, info.gid, info.mtime = mode, 0, 0, now
            tar.addfile(info)

        def add_file(name: str, data: bytes, mode: int) -> None:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.uid, info.gid, info.mtime = len(data), mode, 0, 0, now
            tar.addfile(info, io.BytesIO(data))

        add_dir("judge", 0o700)
        add_file("judge/harness", harness, 0o700)
        add_file("judge/job.json", json.dumps(job_document(job, nonce, uid)).encode(), 0o600)
        add_dir("judge/data", 0o700)
        for i, test in enumerate(job.tests):
            add_file(f"judge/data/{i:03d}.in", test.input, 0o600)
            add_file(f"judge/data/{i:03d}.ans", test.answer, 0o600)
        add_dir(SOURCE_DIR.lstrip("/"), 0o755)
        add_file(f"{SOURCE_DIR.lstrip('/')}/{job.source_filename}", job.source, 0o444)
    return buf.getvalue()


def container_body(job: JudgeJob, uid: int) -> dict[str, Any]:
    """The ``POST /containers/create`` payload. Fixed by Flagpost; only the
    image comes from configuration (an admin-registered language)."""
    memory = container_memory_mb(job) * 1024 * 1024
    stack = job.memory_limit_mb * 1024 * 1024
    return {
        "Image": job.image_ref,
        # The image's own entrypoint is bypassed: the harness is PID 1.
        "Entrypoint": [HARNESS_PATH],
        "Cmd": [f"{JOB_DIR}/job.json"],
        "User": "0:0",
        "WorkingDir": WORK_DIR,
        "NetworkDisabled": True,
        "Labels": {LABEL_JUDGE: "true", LABEL_JUDGING: job.judging_id},
        "HostConfig": {
            "NetworkMode": "none",
            "CapDrop": ["ALL"],
            # The harness switches each run to the submission user and reaps
            # its processes; the submission itself ends up with none.
            "CapAdd": ["SETUID", "SETGID", "KILL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Privileged": False,
            # Writable layer: an archive upload into a read-only rootfs is
            # refused. Everything in it is root-owned, so the submission user
            # can't write it regardless.
            "ReadonlyRootfs": False,
            "PidsLimit": PIDS_LIMIT,
            "Memory": memory,
            "MemorySwap": memory,  # no swap
            "NanoCpus": int(CPUS * 1_000_000_000),
            "RestartPolicy": {"Name": "no"},
            # Off: the result is read from the logs after exit; the executor
            # removes the container itself.
            "AutoRemove": False,
            "ShmSize": SHM_MB * 1024 * 1024,
            "Binds": [],
            "Mounts": [],
            "Tmpfs": {
                # Scratch for the compiler's output and the run: exec allowed
                # (a compiled submission must run), owned by the submission user.
                WORK_DIR: (
                    f"rw,exec,nosuid,nodev,size={WORK_TMPFS_MB}m,"
                    f"uid={uid},gid={uid},mode=0755"
                ),
                # Shadow the image's world-writable temp dirs, so writes land
                # in bounded memory rather than the container's disk layer.
                "/tmp": f"rw,nosuid,nodev,size={TMP_TMPFS_MB}m,mode=1777",
                "/var/tmp": f"rw,nosuid,nodev,size={TMP_TMPFS_MB}m,mode=1777",
            },
            "Ulimits": [
                {"Name": "nofile", "Soft": 1024, "Hard": 1024},
                # Deep recursion is normal in contest code: allow a stack as
                # large as the memory limit.
                {"Name": "stack", "Soft": stack, "Hard": stack},
            ],
            # Explicit, so the result is readable whatever the daemon's
            # default logging driver is.
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m"}},
        },
    }


def demux_logs(raw: bytes) -> tuple[bytes, bytes]:
    """Split Docker's multiplexed log stream (8-byte frame headers: stream id,
    three zero bytes, big-endian length) into stdout and stderr."""
    out, err = bytearray(), bytearray()
    i = 0
    while i + 8 <= len(raw):
        stream, size = raw[i], int.from_bytes(raw[i + 4 : i + 8], "big")
        if stream not in (0, 1, 2) or raw[i + 1 : i + 4] != b"\0\0\0":
            # Not multiplexed (a TTY container): it's all stdout.
            return raw, b""
        chunk = raw[i + 8 : i + 8 + size]
        (err if stream == 2 else out).extend(chunk)
        i += 8 + size
    return bytes(out), bytes(err)


def parse_result(stdout: bytes, nonce: str, job: JudgeJob, stderr: bytes = b"") -> JudgeResult:
    """The harness's result line — the last stdout line carrying this
    judging's nonce. A line without it didn't come from this harness."""
    for line in reversed(stdout.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("nonce") == nonce:
            return _result_from(doc, job)
    detail = _truncate(stderr.decode("utf-8", "replace")) if stderr else ""
    raise JudgeExecutorError(
        "the judge harness produced no result" + (f": {detail}" if detail else "")
    )


def _result_from(doc: dict[str, Any], job: JudgeJob) -> JudgeResult:
    verdict = doc.get("verdict")
    if verdict not in VERDICTS:
        raise JudgeExecutorError(f"the judge harness reported an unknown verdict {verdict!r}")
    tests = []
    for i, t in enumerate(doc.get("tests") or []):
        if i >= len(job.tests):
            break
        tests.append(
            JudgeTestResult(
                index=i,
                sample=job.tests[i].sample,
                verdict=str(t.get("verdict")),
                time_ms=int(t.get("time_ms") or 0),
                wall_ms=int(t.get("wall_ms") or 0),
                memory_kb=int(t.get("memory_kb") or 0),
                exit_code=t.get("exit_code"),
                signal=t.get("signal"),
                output=(
                    str(t["output"])
                    if job.tests[i].sample and t.get("output") is not None
                    else None
                ),
            )
        )
    return JudgeResult(
        verdict=verdict,
        compile_output=str(doc.get("compile_output") or ""),
        compile_time_ms=int(doc.get("compile_time_ms") or 0),
        tests=tuple(tests),
        error=doc.get("error") or None,
    )


# --- the executor -----------------------------------------------------------------


@register_judge_executor
class DockerJudgeExecutor(JudgeExecutor):
    kind: ClassVar[str] = "docker"

    def __init__(
        self,
        config: JudgeDockerConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        harness_loader: Callable[[str], bytes] | None = None,
    ) -> None:
        self._cfg = config
        self._transport = transport
        self._load_harness = harness_loader or load_harness
        self._arch: str | None = None

    @classmethod
    def from_settings(cls, settings) -> DockerJudgeExecutor:
        from utils.judge_connection import effective_endpoint

        endpoint, _managed = effective_endpoint(settings)
        if not endpoint:
            raise JudgeExecutorError("the code judge has no endpoint configured")
        return cls(JudgeDockerConfig(endpoint_url=endpoint.rstrip("/")))

    # --- HTTP plumbing ---------------------------------------------------------

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._cfg.endpoint_url,
            timeout=timeout,
            transport=self._transport,
            headers=self._cfg.extra_headers or None,
        )

    async def _request(self, method: str, path: str, *, timeout: float, **kwargs: Any) -> httpx.Response:
        async with self._client(timeout) as http:
            try:
                return await http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise JudgeExecutorError(f"request to the container runtime failed: {exc}") from exc

    async def _host_arch(self) -> str:
        if self._arch is None:
            resp = await self._request("GET", "/version", timeout=_TIMEOUT_QUICK)
            if resp.status_code != 200:
                raise JudgeExecutorError(f"reading the Docker version failed: {_daemon_detail(resp)}")
            self._arch = str(resp.json().get("Arch") or "amd64")
        return self._arch

    async def _ensure_image(self, image: str) -> None:
        # Inspect first: a cached image needs no registry round trip, so
        # judging keeps working when the registry is slow or the host is
        # air-gapped with pre-pulled images.
        resp = await self._request("GET", f"/images/{image}/json", timeout=_TIMEOUT_QUICK)
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise JudgeExecutorError(f"checking the image {image} failed: {_daemon_detail(resp)}")
        async with self._client(_TIMEOUT_PULL) as http:
            ok, detail = await pull_image(http, image)
        if not ok:
            raise JudgeExecutorError(detail)

    async def _remove(self, cid: str) -> None:
        try:
            resp = await self._request(
                "DELETE", f"/containers/{cid}", params={"force": "1", "v": "1"}, timeout=_TIMEOUT_QUICK
            )
            if resp.status_code not in (204, 404):
                logger.warning("judge container %s not removed: %s", cid, _daemon_detail(resp))
        except JudgeExecutorError as exc:
            logger.warning("judge container %s not removed: %s", cid, exc)

    # --- run ------------------------------------------------------------------------

    async def run(self, job: JudgeJob) -> JudgeResult:
        harness = self._load_harness(await self._host_arch())
        await self._ensure_image(job.image_ref)
        nonce = secrets.token_hex(16)
        uid = submission_uid()
        archive = build_archive(job, harness, nonce, uid)

        created = await self._request(
            "POST",
            "/containers/create",
            params={"name": f"flagpost-judge-{job.judging_id}-{nonce[:8]}"},
            json=container_body(job, uid),
            timeout=_TIMEOUT_LIFECYCLE,
        )
        if created.status_code != 201:
            raise JudgeExecutorError(f"judge container create failed: {_daemon_detail(created)}")
        cid = created.json()["Id"]
        try:
            return await self._run_container(cid, job, archive, nonce)
        finally:
            # Shielded: a cancelled judging must still not leak its container.
            await asyncio.shield(self._remove(cid))

    async def _run_container(self, cid: str, job: JudgeJob, archive: bytes, nonce: str) -> JudgeResult:
        uploaded = await self._request(
            "PUT",
            f"/containers/{cid}/archive",
            params={"path": "/"},
            content=archive,
            headers={"Content-Type": "application/x-tar"},
            timeout=_TIMEOUT_UPLOAD,
        )
        if uploaded.status_code != 200:
            raise JudgeExecutorError(f"uploading the judging failed: {_daemon_detail(uploaded)}")

        started = await self._request("POST", f"/containers/{cid}/start", timeout=_TIMEOUT_LIFECYCLE)
        if started.status_code not in (204, 304):
            raise JudgeExecutorError(f"judge container start failed: {_daemon_detail(started)}")

        budget = time_budget_s(job)
        try:
            async with asyncio.timeout(budget):
                waited = await self._request(
                    "POST", f"/containers/{cid}/wait", timeout=budget + _TIMEOUT_QUICK
                )
        except TimeoutError:
            raise JudgeExecutorError(
                f"the judging didn't finish within {budget:.0f}s"
            ) from None
        if waited.status_code != 200:
            raise JudgeExecutorError(f"waiting for the judging failed: {_daemon_detail(waited)}")

        logs = await self._request(
            "GET",
            f"/containers/{cid}/logs",
            params={"stdout": "1", "stderr": "1"},
            timeout=_TIMEOUT_QUICK,
        )
        if logs.status_code != 200:
            raise JudgeExecutorError(f"reading the judging's result failed: {_daemon_detail(logs)}")
        stdout, stderr = demux_logs(logs.content)
        try:
            return parse_result(stdout, nonce, job, stderr)
        except JudgeExecutorError:
            status_code = (waited.json() or {}).get("StatusCode")
            if status_code == 137:
                raise JudgeExecutorError(
                    "the judge container was killed (out of memory?) before reporting"
                ) from None
            raise

    def time_budget_s(self, job: JudgeJob) -> float:
        return time_budget_s(job)

    async def cleanup(self, keep: set[str]) -> int:
        """Remove judge containers left by a crashed worker. Conservative,
        because the endpoint may be shared — by another worker mid rolling
        deploy, or another install entirely, whose judgings this database
        knows nothing about: a *running* container is only removed once far
        older than any judging could last, and a stopped one after a grace
        period (its own executor reads the result the moment it exits)."""
        resp = await self._request(
            "GET",
            "/containers/json",
            params={"all": "1", "filters": json.dumps({"label": [f"{LABEL_JUDGE}=true"]})},
            timeout=_TIMEOUT_QUICK,
        )
        if resp.status_code != 200:
            raise JudgeExecutorError(f"listing judge containers failed: {_daemon_detail(resp)}")
        now = time.time()
        removed = 0
        for c in resp.json():
            if (c.get("Labels") or {}).get(LABEL_JUDGING) in keep:
                continue
            age = now - float(c.get("Created") or now)
            limit = _ORPHAN_RUNNING_AGE_S if c.get("State") == "running" else _ORPHAN_STOPPED_AGE_S
            if age < limit:
                continue
            await self._remove(c["Id"])
            removed += 1
        return removed

    # --- validate -------------------------------------------------------------------

    async def validate(self) -> list[CheckResult]:
        from utils.judge_connection import check_endpoint

        legs = await check_endpoint(self._cfg.endpoint_url, transport=self._transport)
        if not all(leg.ok for leg in legs):
            return legs

        try:
            arch = await self._host_arch()
            self._load_harness(arch)
        except JudgeExecutorError as exc:
            legs.append(CheckResult("harness_available", False, str(exc)))
            return legs
        legs.append(CheckResult("harness_available", True, f"judge harness for linux/{arch} is installed"))

        # A real judging of a one-line program, end to end through the proxy:
        # pull, create with the judge's capabilities, upload, run, read back.
        probe = make_job(
            judging_id="probe",
            image_ref=self._cfg.probe_image,
            source_filename="probe.sh",
            source=b"read a b\necho $((a + b))\n",
            compile_command=None,
            run_command=["sh", "{source}"],
            time_multiplier=1.0,
            time_limit_ms=2000,
            memory_limit_mb=64,
            output_limit_kb=64,
            compare_mode="token",
            float_tolerance=0.0,
            tests=[JudgeTest(sample=True, input=b"2 3\n", answer=b"5\n")],
        )
        started = time.monotonic()
        try:
            result = await self.run(probe)
        except JudgeExecutorError as exc:
            legs.append(CheckResult("test_judging", False, f"a test judging failed: {exc}"))
            return legs
        took = time.monotonic() - started
        if result.verdict != "accepted":
            detail = result.error or result.compile_output or result.verdict
            legs.append(
                CheckResult("test_judging", False, f"a test judging returned {result.verdict}: {detail}")
            )
        else:
            legs.append(CheckResult("test_judging", True, f"ran a test judging in {took:.1f}s"))
        return legs
