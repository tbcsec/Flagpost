"""Built-in language presets for the code judge (#447, ADR-0042).

Each preset is a ready-made ``JudgeLanguage`` definition over a Docker Hub
**Official Image** — no Flagpost-specific image is needed, because the harness
is a static binary uploaded per judging (ADR-0042 amendment). The admin UI
offers these as "tick the languages you want"; adding one creates an ordinary
``judge_languages`` row the operator can then edit (e.g. to re-pin a version).

Presets are a catalog, deliberately **not** seeded rows: a later release
updating a preset's image tag must not silently change a language an operator
already runs (a mid-event compiler change can flip a verdict), and a deleted
language must not reappear on restart.

Image choice: Debian-based (``-slim`` where it exists) rather than Alpine — musl
can change behaviour and performance versus the glibc toolchains contests
assume. Tags are pinned to a release line, the newest stable except where an
LTS line exists (Java, Node) or the newest is brand-new (Python 3.15). Every
preset compiles and runs a hello-world through the real executor as part of
#448's acceptance — that is what validates these commands. Time multipliers
default to 1.0, as in ICPC-style judges; operators may raise them.
"""

from __future__ import annotations

from typing import Any

# Go's toolchain needs a writable cache and module path; the submission user
# has no home directory, so point both into the scratch directory.
_GO_ENV = ["env", "GOCACHE={work}/.gocache", "GOPATH={work}/.gopath"]

LANGUAGE_PRESETS: list[dict[str, Any]] = [
    {
        "key": "python3",
        "name": "Python 3",
        "image_ref": "python:3.14-slim",
        "source_filename": "solution.py",
        # A syntax check as the "compile" step, so a syntax error is reported
        # as a compile error rather than a runtime error on the first test.
        "compile_command": [
            "python3", "-c",
            "import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])",
            "{source}",
        ],
        "run_command": ["python3", "{source}"],
    },
    {
        "key": "pypy3",
        "name": "PyPy 3",
        "image_ref": "pypy:3.11-slim",
        "source_filename": "solution.py",
        "compile_command": [
            "pypy3", "-c",
            "import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])",
            "{source}",
        ],
        "run_command": ["pypy3", "{source}"],
    },
    {
        "key": "c",
        "name": "C",
        "image_ref": "gcc:16",
        "source_filename": "main.c",
        "compile_command": [
            "gcc", "-O2", "-std=gnu17", "-o", "{work}/main", "{source}", "-lm",
        ],
        "run_command": ["{work}/main"],
    },
    {
        "key": "cpp",
        "name": "C++",
        "image_ref": "gcc:16",
        "source_filename": "main.cpp",
        "compile_command": [
            "g++", "-O2", "-std=gnu++20", "-o", "{work}/main", "{source}",
        ],
        "run_command": ["{work}/main"],
    },
    {
        "key": "java",
        "name": "Java",
        "image_ref": "eclipse-temurin:25-jdk",
        "source_filename": "Main.java",
        "compile_command": ["javac", "-d", "{work}", "{source}"],
        "run_command": ["java", "-Xss64m", "-cp", "{work}", "Main"],
    },
    {
        "key": "go",
        "name": "Go",
        "image_ref": "golang:1.27",
        "source_filename": "main.go",
        "compile_command": [*_GO_ENV, "go", "build", "-o", "{work}/main", "{source}"],
        "run_command": ["{work}/main"],
    },
    {
        "key": "rust",
        "name": "Rust",
        "image_ref": "rust:1.98-slim",
        "source_filename": "main.rs",
        "compile_command": [
            "rustc", "-O", "--edition", "2021", "-o", "{work}/main", "{source}",
        ],
        "run_command": ["{work}/main"],
    },
    {
        "key": "javascript",
        "name": "JavaScript (Node.js)",
        "image_ref": "node:24-slim",
        "source_filename": "solution.js",
        "compile_command": None,
        "run_command": ["node", "{source}"],
    },
]

for _preset in LANGUAGE_PRESETS:
    _preset.setdefault("time_multiplier", 1.0)
