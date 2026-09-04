"""Spreadsheet formula-injection defence for CSV exports (CWE-1236).

A CSV cell whose text a spreadsheet (Excel, LibreOffice, Google Sheets) would
evaluate as a formula — it begins with ``=``, ``+``, ``-``, ``@``, or a leading
TAB/CR — becomes code execution (DDE, ``=HYPERLINK`` exfiltration of adjacent
cells) the moment an operator opens the export. Every export that writes a
user-influenced string into a cell must route it through :func:`csv_safe`, which
prefixes a single quote so the spreadsheet treats the value as literal text.

Numbers/booleans are passed through as their plain rendering: a value that
arrived as ``int``/``float``/``bool`` is server-computed, never an attacker
formula, so a negative number like ``-5`` is not mangled into text. Only genuine
strings (names, free-text answers, emails — the attacker-controlled columns) are
guarded. Use it at *every* export site, including for header labels and for
columns that are IDs today, so a later free-text column can't silently reopen
the hole.
"""

from __future__ import annotations

# Leading characters a spreadsheet treats as the start of a formula. TAB/CR are
# included because some importers strip surrounding whitespace before parsing,
# exposing a following '=' as the first meaningful character.
_FORMULA_LEADS = frozenset("=+-@\t\r")


def csv_safe(value: object) -> str:
    """Return ``value`` as a CSV cell string with formula leads neutralised."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        # Server-computed numeric — never an attacker-supplied formula.
        return str(value)
    text = value if isinstance(value, str) else str(value)
    if text and text[0] in _FORMULA_LEADS:
        return "'" + text
    return text
