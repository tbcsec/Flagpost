"""Built-in language presets for the code judge (#447, ADR-0042).

Each preset is a ready-made ``JudgeLanguage`` definition over an **official
image** — a Docker Hub Official Image, or the language vendor's own registry
where that's the official source (C#: Microsoft's) — no Flagpost-specific image
is needed, because the harness is a static binary uploaded per judging
(ADR-0042 amendment). A language without an official image (Kotlin, say) isn't
a preset; an operator can still add it as a custom language over an image they
choose or build. The admin UI
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
#448's acceptance — that is what validates these commands.

Time multipliers are tiered by how much slower a language runs than C/C++
(#451; measured on these images): compiled systems languages 1.0, Go 1.5, the
JIT and bytecode languages (Java, C#, JavaScript, PyPy) 2.0, CPython 3.0 — so a
reasonable solution isn't punished by a limit tuned for C++, without letting
much slower algorithms through (no multiplier closes CPython's gap on
loop-heavy code, and each one costs judge time on a TLE). ICPC-style events
that want one limit for every language set them back to 1.0.
"""

from __future__ import annotations

from typing import Any

# Go's toolchain needs a writable cache and module path; the submission user
# has no home directory, so point both into the scratch directory.
_GO_ENV = ["env", "GOCACHE={work}/.gocache", "GOPATH={work}/.gopath"]

LANGUAGE_PRESETS: list[dict[str, Any]] = [
    {
        "key": "python3",
        "time_multiplier": 3.0,
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
        "time_multiplier": 2.0,
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
        "time_multiplier": 1.0,
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
        "time_multiplier": 1.0,
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
        "time_multiplier": 2.0,
        "name": "Java",
        "image_ref": "eclipse-temurin:25-jdk",
        "source_filename": "Main.java",
        "compile_command": ["javac", "-d", "{work}", "{source}"],
        "run_command": ["java", "-Xss64m", "-cp", "{work}", "Main"],
    },
    {
        "key": "go",
        "time_multiplier": 1.5,
        "name": "Go",
        "image_ref": "golang:1.27",
        "source_filename": "main.go",
        "compile_command": [*_GO_ENV, "go", "build", "-o", "{work}/main", "{source}"],
        "run_command": ["{work}/main"],
    },
    {
        "key": "rust",
        "time_multiplier": 1.0,
        "name": "Rust",
        "image_ref": "rust:1.98-slim",
        "source_filename": "main.rs",
        "compile_command": [
            "rustc", "-O", "--edition", "2021", "-o", "{work}/main", "{source}",
        ],
        "run_command": ["{work}/main"],
    },
    {
        # Microsoft's official .NET SDK image (MCR — there's no Docker Hub
        # Official one). ``dotnet build`` needs a project file: it's passed as
        # a positional argument (keeping each argv entry short) and written
        # into the scratch directory. Offline, no build server, telemetry off.
        "key": "csharp",
        "time_multiplier": 2.0,
        "name": "C#",
        "image_ref": "mcr.microsoft.com/dotnet/sdk:10.0",
        "source_filename": "Main.cs",
        "compile_command": [
            "env", "DOTNET_CLI_TELEMETRY_OPTOUT=1", "DOTNET_NOLOGO=1",
            "sh", "-c",
            'cd {work} && printf %s "$1" > s.csproj && dotnet build s.csproj -c Release'
            " -o out -v q -p:UseSharedCompilation=false --disable-build-servers",
            "sh",
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            "<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>"
            "<EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup>"
            '<ItemGroup><Compile Include="{source}"/></ItemGroup></Project>',
        ],
        "run_command": ["env", "DOTNET_CLI_TELEMETRY_OPTOUT=1", "dotnet", "{work}/out/s.dll"],
    },
    {
        "key": "javascript",
        "time_multiplier": 2.0,
        "name": "JavaScript (Node.js)",
        "image_ref": "node:24-slim",
        "source_filename": "solution.js",
        "compile_command": None,
        "run_command": ["node", "{source}"],
    },
]

for _preset in LANGUAGE_PRESETS:
    _preset.setdefault("time_multiplier", 1.0)
