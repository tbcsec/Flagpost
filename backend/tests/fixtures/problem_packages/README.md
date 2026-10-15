# Vendored problem packages

Two real, third-party problem packages in the open ICPC/Kattis problem package
format, kept so the package importer (#451) is tested against what real tools
and contest archives produce, not just against what our own builders produce.
Every other case is built in memory by `backend/tests/package_fixtures.py`, so
nothing else should need vendoring. Both files are inert test data, never run.

Licences were checked at the source, both in each package's `problem.yaml` and
in the upstream repository's `LICENSE`, before vendoring.

## `hello.zip`

| | |
|---|---|
| Upstream | <https://github.com/Kattis/problemtools/tree/master/examples/hello> |
| Fetched | 2026-10-15, repository `HEAD` `1f5bf9253b0ae579fe241ae8da2e4208177ac0be`. The last commit touching `examples/hello` is `3161255b1178c09a3e1e27b945fa9845a7ddd50b` (2026-08-12). |
| Licence | `problem.yaml` says `license: public domain` (`source: Kattis`). The repository is MIT-licensed; the notice is reproduced below. |
| SHA-256 | `79c59ac962b088ea142e0ac8f0fd69f505f5305a1fbb2ed01ad46e6429655450` |

Upstream ships this example as a directory in git, not as a zip, so we packed
it ourselves. Every file under `examples/hello/` is included unmodified (each
member's git blob hash was checked against the upstream tree) under a top-level
`hello/` directory, with the modes git records (`100644`, and `100755` for
`input_validators/validate.py`), a fixed timestamp (2026-08-12 08:43:06) and no
directory entries. Upstream has no symlinks.

What it exercises:

- legacy format: no `problem_format_version`, name in `problem.yaml`,
  `limits.memory: 512` and no time limit at all;
- **no `data/sample/`** — only `data/secret/`, whose single `.in` is empty;
- two statement languages, `problem.en.tex` and `problem.sv.tex`, each with
  `\problemname`;
- `input_validators/`;
- submissions in `accepted/` (C, C++, Java, Kotlin, Python 3, Rust),
  `wrong_answer/` and `run_time_error/`.

## `outofsorts.zip`

| | |
|---|---|
| Upstream | <https://github.com/icpc/na-ecna-archive/blob/main/2019-2020/outofsorts.zip> |
| Fetched | 2026-10-15, from commit `9b6a727726187dba0701db15e67132860a693d4e` (2024-07-14, "added 2019-2020 regional contest files") |
| Licence | Repository `LICENSE`: CC0-1.0. `problem.yaml`: `license: cc0`, `rights_owner: ECNA`, `author: Bob Roos`, `source: 2019 ICPC East-Central NA Regional Contest`. |
| SHA-256 | `535793573bfaf42e27ffac2b443e855d54bf2b5374fa2c448bceb1ab9309dc9f` (git blob `785313a1a4ee321b4628856c9950b6a9c597c8d0`) |

Stored byte-for-byte as upstream publishes it. The 2019 ECNA problem "Binary
Botch".

What it exercises:

- a real contest export, zipped by someone else's tooling: directory entries,
  and members with **no Unix mode bits** (`create_system` 0, `external_attr`
  of 32 or 16), so mode-based symlink detection must not misfire;
- **CRLF line endings in every file** — `problem.yaml`, the statement, the
  solutions and all test data (`.in` and `.ans`), so YAML, `\problemname` and
  answer handling must not assume `\n`;
- **the name in `problem.yaml` ("Binary Botch") differs from the statement's
  `\problemname{Out of Sorts}`**;
- `limits.time_multiplier: 3` and no explicit time limit;
- a statement named `problem_statement/problem.tex`, with no language code
  (English by default);
- the older `input_format_validators/` directory name;
- 2 sample and 12 secret cases with descriptive names (`010-10-sorted.in` …);
- `submissions/README` and a `.ignore` file under `time_limit_exceeded/`
  beside accepted C++, Java and Python solutions.

## Licence notice for `hello.zip`

```
The MIT License (MIT)

Copyright (c) Kattis and all respective contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
