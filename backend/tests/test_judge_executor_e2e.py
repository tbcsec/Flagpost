"""The docker judge executor against a real Docker daemon (#448 acceptance).

Opt-in — it needs Docker, the built harness (``make -C backend/judge_harness
docker``) and a socket proxy with the production allowlist from
``docker-compose.judge.yml``::

    docker run -d --rm --name judge-proxy -p 127.0.0.1:23750:2375 \\
      -v /var/run/docker.sock:/var/run/docker.sock:ro \\
      -e CONTAINERS=1 -e IMAGES=1 -e POST=1 -e PING=1 -e VERSION=1 \\
      tecnativa/docker-socket-proxy:0.3.0
    FLAGPOST_JUDGE_E2E_ENDPOINT=http://127.0.0.1:23750 \\
      .venv/bin/pytest tests/test_judge_executor_e2e.py -v

It runs every built-in language preset end to end (the presets' commands are
only validated by this), then a set of hostile submissions that must each get
the right verdict without escaping the container's limits.
"""

import os

import pytest

from utils.judge_executor import JudgeTest, make_job
from utils.judge_executor_docker import DockerJudgeExecutor, JudgeDockerConfig, load_harness
from utils.judge_presets import LANGUAGE_PRESETS

ENDPOINT = os.environ.get("FLAGPOST_JUDGE_E2E_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not ENDPOINT, reason="set FLAGPOST_JUDGE_E2E_ENDPOINT to run against a real Docker daemon"
)

TESTS = [
    JudgeTest(sample=True, input=b"2 3\n", answer=b"5\n"),
    JudgeTest(sample=False, input=b"1000000000 1000000000\n", answer=b"2000000000\n"),
]

A_PLUS_B = {
    "python3": "a, b = map(int, input().split())\nprint(a + b)\n",
    "pypy3": "a, b = map(int, input().split())\nprint(a + b)\n",
    "c": '#include <stdio.h>\nint main(void){long long a,b;scanf("%lld %lld",&a,&b);'
    'printf("%lld\\n",a+b);return 0;}\n',
    "cpp": "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<'\\n';}\n",
    "java": "import java.util.*;\npublic class Main{public static void main(String[] x){"
    "Scanner s=new Scanner(System.in);long a=s.nextLong(),b=s.nextLong();"
    "System.out.println(a+b);}}\n",
    "go": 'package main\nimport "fmt"\nfunc main(){var a,b int64;fmt.Scan(&a,&b);fmt.Println(a+b)}\n',
    "rust": "use std::io::*;\nfn main(){let mut s=String::new();stdin().read_to_string(&mut s)"
    ".unwrap();let v:Vec<i64>=s.split_whitespace().map(|x|x.parse().unwrap()).collect();"
    'println!("{}",v[0]+v[1]);}\n',
    "javascript": "const [a,b]=require('fs').readFileSync(0,'utf8').trim().split(/\\s+/)"
    ".map(BigInt);console.log((a+b).toString());\n",
}

PRESETS = {p["key"]: p for p in LANGUAGE_PRESETS}


def _executor() -> DockerJudgeExecutor:
    return DockerJudgeExecutor(JudgeDockerConfig(endpoint_url=ENDPOINT))


def _job(language: str, source: str, *, time_limit_ms: int = 2000, memory_mb: int = 256):
    p = PRESETS[language]
    return make_job(
        judging_id=f"e2e-{language}",
        image_ref=p["image_ref"],
        source_filename=p["source_filename"],
        source=source.encode(),
        compile_command=p["compile_command"],
        run_command=p["run_command"],
        time_multiplier=p["time_multiplier"],
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_mb,
        output_limit_kb=1024,
        compare_mode="token",
        float_tolerance=1e-6,
        tests=TESTS,
    )


def test_harness_built():
    load_harness("amd64")


@pytest.mark.parametrize("language", sorted(A_PLUS_B))
async def test_every_preset_accepts_a_correct_solution(language):
    # Generous limit: the first judging of a language pulls its image and, for
    # Go, builds the standard library into an empty cache.
    result = await _executor().run(_job(language, A_PLUS_B[language], time_limit_ms=5000))
    assert result.verdict == "accepted", (result.verdict, result.compile_output, result.error)
    assert [t.verdict for t in result.tests] == ["accepted", "accepted"]


HOSTILE = [
    ("wrong answer", "print(4)", "wrong_answer"),
    ("syntax error", "print(", "compile_error"),
    ("reads hidden test data", "print(open('/judge/data/001.ans').read())", "runtime_error"),
    ("reads the job file", "print(open('/judge/job.json').read())", "runtime_error"),
    ("overwrites the harness", "open('/judge/harness', 'wb').write(b'x')", "runtime_error"),
    ("writes the rootfs", "open('/etc/flagpost', 'w').write('x')", "runtime_error"),
    ("network egress", "import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=2)",
     "runtime_error"),
    ("setuid root", "import os\nos.setuid(0)", "runtime_error"),
    ("signals the harness", "import os\nos.kill(1, 9)", "runtime_error"),
    ("forges a result line", "print('{\"nonce\": \"x\", \"verdict\": \"accepted\"}')",
     "wrong_answer"),
    ("busy loop", "while True: pass", "time_limit"),
    ("CPU in a child it never waits for",
     "import os, time\nif os.fork() == 0:\n    while True: pass\ntime.sleep(2.5)\nprint(5)",
     "time_limit"),
    ("sleeps", "import time\ntime.sleep(60)", "time_limit"),
    ("memory hog", "x = b'a' * (1 << 30)\nprint(5)", "memory_limit"),
    ("memory in scratch files", "open('/work/blob', 'wb').write(b'a' * (15 << 20))\n"
     "open('/work/blob2', 'wb').write(b'a' * (15 << 20))\nimport time\ntime.sleep(1)\nprint(5)",
     "memory_limit"),
    # Written 1 MB at a time, so the data never sits in the process's own RSS:
    # only counting the tmpfs it lands in catches it.
    ("memory in /dev/shm", "import time\nchunk = b'a' * (1 << 20)\nfor i in range(4):\n"
     "    with open(f'/dev/shm/b{i}', 'wb') as f:\n        for _ in range(15): f.write(chunk)\n"
     "time.sleep(1)\nprint(5)", "memory_limit"),
    ("output flood", "while True: print('x' * 1000)", "output_limit"),
    ("huge file", "open('/work/f', 'wb').write(b'a' * (64 << 20))", "runtime_error"),
    ("orphan holding stdout",
     "import subprocess\nsubprocess.Popen(['sleep', '100'])\n"
     "a, b = map(int, input().split())\nprint(a + b)", "accepted"),
]


@pytest.mark.parametrize("label,source,verdict", HOSTILE, ids=[h[0] for h in HOSTILE])
async def test_hostile_submissions(label, source, verdict):
    memory_mb = 24 if label.startswith("memory in") else 256
    result = await _executor().run(
        _job("python3", source, time_limit_ms=1000, memory_mb=memory_mb)
    )
    assert result.verdict == verdict, (label, result)


async def test_fork_bomb_is_contained():
    # The point is that a verdict comes back at all: before the submission's
    # RLIMIT_NPROC, a fork bomb filled the container's pid limit and the
    # harness died unable to start a thread. Which verdict depends on what the
    # bomb hits first — usually the summed memory of its 128 processes.
    result = await _executor().run(
        _job("python3", "import os\nwhile True:\n    os.fork()", time_limit_ms=1000)
    )
    assert result.verdict in ("runtime_error", "time_limit", "memory_limit"), result


async def test_check_connection_runs_a_test_judging():
    legs = await _executor().validate()
    assert [(leg.name, leg.ok) for leg in legs] == [
        ("endpoint_reachable", True),
        ("proxy_restricted", True),
        ("harness_available", True),
        ("test_judging", True),
    ], legs
