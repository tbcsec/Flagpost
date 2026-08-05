"""Output-side flag-format redaction for the competitor assistant (#98,
ADR-0023 Phase 3, spec §5 layer 3).

**Belt-and-braces, not the guarantee.** The real protection against a competitor
extracting a flag is structural: flags are stored hashed and the competitor tools
reuse ``ChallengeOut``, which has no field that could carry a flag, hash, salt,
regex, or the correct multiple-choice option (spec §3.1). A jailbroken model
therefore has nothing to leak from its tools. This scan is a cheap secondary net
for the residual cases — a model that *hallucinates* a flag-shaped string, or
echoes one a competitor pasted into the chat — so such a string never renders
back to the competitor.

It is a heuristic on the common CTF flag shape ``prefix{...}`` and may
occasionally redact a non-flag that happens to look like one (a code snippet on a
single line). That over-redaction is the acceptable side of the trade-off for a
competitor hint channel, and it is applied to competitor output only — the admin
assistant, which executes as the organiser, is never scanned.
"""

from __future__ import annotations

import re

REDACTION = "[redacted]"

# An identifier immediately followed by a single-line brace group with non-empty,
# non-whitespace-led content: `flag{...}`, `CTF{...}`, `picoCTF{...}`. Requiring
# the identifier to abut `{` (no space) and the body to be single-line and start
# non-space keeps ordinary prose/code like `if (x) {` or `object { ... }` from
# matching, while catching the flag shape regardless of the prefix word.
_FLAG_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]{1,31}\{[^\s}][^\n}]{0,255}\}")


def redact_flags(text: str) -> str:
    """Replace flag-shaped substrings with a redaction marker. Idempotent and
    safe on empty input."""
    if not text:
        return text
    return _FLAG_RE.sub(REDACTION, text)


def contains_flag_shape(text: str) -> bool:
    """Whether ``text`` contains a flag-shaped substring (for tests / metrics)."""
    return bool(text) and _FLAG_RE.search(text) is not None
