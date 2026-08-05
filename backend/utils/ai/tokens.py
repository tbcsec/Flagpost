"""Token accounting for the AI module (#98, spec §9).

The usage counter and the context-window budget need token counts, but a
bring-your-own endpoint can't be assumed to report them: hosted APIs populate a
``usage`` object, while local endpoints (Ollama and friends) frequently omit it.
So the accounting *prefers* the endpoint's own numbers and falls back to a cheap
local estimate, which keeps the cost guard and history truncation working
against any endpoint rather than silently reading zero.

The estimate is deliberately approximate — ~4 characters per token, OpenAI's own
rule of thumb — not a real tokenizer. It only backstops endpoints that don't
report usage; where the endpoint does report, that exact number wins.
"""

from __future__ import annotations

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """A rough token count for ``text`` when the endpoint reports none."""
    if not text:
        return 0
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)
