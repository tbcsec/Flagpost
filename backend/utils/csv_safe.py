"""Spreadsheet formula-injection defence for CSV exports (CWE-1236).

A CSV cell whose text a spreadsheet (Excel, LibreOffice, Google Sheets) would
evaluate as a formula — it begins with ``=``, ``+``, ``-``, ``@``, or a leading
TAB/CR — becomes code execution (DDE, ``=HYPERLINK`` exfiltration of adjacent
cells) the moment an operator opens the export. Every export that writes a
user-influenced string into a cell must route it through :func:`csv_safe`, which
prefixes a single quote so the spreadsheet treats the value as literal text.

The start of the value is not the only place a cell can start. Our writers emit
comma-separated files and quote only what a *comma* parser needs quoted, but
Excel splits a ``.csv`` on the locale's list separator — ``;`` wherever the
decimal mark is a comma (fr/es/pl/de/it, three of our shipped UI languages) —
and tab-delimited import splits on TAB. A ``;`` or TAB inside a value is
therefore a cell boundary on those machines, and no quoting style prevents it:
to that parser a comma-CSV quote usually opens mid-cell, where it is plain text,
so a CR/LF inside the value ends the row as well. Importers that end a row at
every line break, quoted or not, do that even with a comma separator, and from
there on their quoting is out of step with the writer's — so a comma inside a
value is a boundary too. So :func:`csv_safe` also neutralises a formula lead at
the start of every segment that follows a ``;``, comma, TAB, CR or LF
(GHSA-352q-g5xh-3299). The cost is a stray apostrophe mid-value, only where a
separator is followed by a lead — legible, and inert.

Numbers/booleans are passed through as their plain rendering: a value that
arrived as ``int``/``float``/``bool`` is server-computed, never an attacker
formula, so a negative number like ``-5`` is not mangled into text. Only genuine
strings (names, free-text answers, emails — the attacker-controlled columns) are
guarded. Use it at *every* export site, including for header labels and for
columns that are IDs today, so a later free-text column can't silently reopen
the hole.
"""

from __future__ import annotations

import re

# Leading characters a spreadsheet treats as the start of a formula. TAB/CR are
# included because some importers strip surrounding whitespace before parsing,
# exposing a following '=' as the first meaningful character.
_FORMULA_LEADS = frozenset("=+-@\t\r")

# A ';', comma, TAB, CR or LF — a cell or row boundary to some parser of the
# file (see above) — followed by a formula lead. Quote characters between the
# two are looked through: once the writer has doubled them, a parser can consume
# them as an empty quoted prefix and still leave the lead first in the cell. The
# apostrophe goes straight after the separator, ahead of any quotes. A TAB or
# CR after a separator needs nothing: it is a separator itself, so a lead after
# *it* is caught there — prefixing it would only mangle CRLF paragraphs. This
# runs over untrusted text, so it must stay linear: a single-character
# separator and a possessive quote run (runs after different separators can't
# overlap — a separator is never a quote).
_SEGMENT_FORMULA = re.compile(r'([;,\t\r\n])(?="*+[=+\-@])')


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
    text = _SEGMENT_FORMULA.sub(r"\1'", text)
    if text and text[0] in _FORMULA_LEADS:
        return "'" + text
    return text
