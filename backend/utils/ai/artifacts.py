"""Strip stray tool-call artifacts from competitor output (#98, ADR-0023 Phase 3).

Some tool-capable local models (notably llama3.1 via Ollama) leak a vestige of
their tool-call format into the *content* stream when tools are offered but the
model ultimately answers in prose: a bare empty JSON object ``{}`` (or ``[]``) at
the very start of the message, ahead of the real answer. The client can't map it
to a tool call (there's no function name), so it rides through as content. It's a
cosmetic model/template quirk, not a Flagpost signal — nothing downstream
consumes it — so the competitor turn scrubs a leading empty-structure token
before delivery, in the same buffered post-processing pass that runs the flag
scan (``utils.ai.flag_scan``).

Deliberately narrow: only the *leading* position and only *empty* object/array
tokens, so it can never eat a legitimate ``{}`` a competitor is discussing
mid-answer. If stripping would empty the message entirely (the model produced
nothing but the artifact) the original is kept, so a degenerate turn still shows
*something* rather than a blank bubble.

A sharper sibling of the same failure (:func:`scrub_leaked_tool_calls`): the same
weak models sometimes emit a *whole* tool call as content text — the JSON plus a
natural-language lead-in ("Here is the JSON for the function call:") — instead of
into the structured ``tool_calls`` field, so the loop never executes it and the
raw call leaks into the answer. That scrub is anchored to an allowlist of the
known competitor tool names, so it recognises a real leak without touching
ordinary prose and, crucially, leaves a *hallucinated* (genuinely broken) call
visible rather than masking it.
"""

from __future__ import annotations

import re

from utils.ai.competitor_tools import competitor_tool_names

# One or more leading empty object/array tokens (`{}`, `{ }`, `[]`), together with
# any surrounding whitespace, anchored to the very start of the message. The `+`
# folds a run like `{}{}` into a single match so one substitution clears them all.
_LEADING_EMPTY_STRUCT = re.compile(r"^(?:\s*(?:\{\s*\}|\[\s*\]))+\s*")


def strip_tool_call_artifacts(text: str) -> str:
    """Remove a leading empty-JSON tool-call artifact, if any. Idempotent, safe on
    empty input, and a no-op when the whole message *is* the artifact (keeps the
    original rather than returning blank)."""
    if not text:
        return text
    stripped = _LEADING_EMPTY_STRUCT.sub("", text, count=1)
    return stripped if stripped.strip() else text


# --- leaked whole tool-call scrub --------------------------------------------
#
# The allowlist of names is sourced from the competitor tool catalogue so it can
# never drift: a brace group is treated as a leak only when its ``name``/
# ``function`` string *value* is exactly one of these. Ordinary prose about JSON
# or functions, generic ``{}``/regex ``{2,4}``, flag-format examples, and even a
# *hallucinated* tool name all fail the gate — the last deliberately, so a
# genuinely broken call stays visible rather than being quietly masked.
_TOOL_NAME_ALT = "|".join(re.escape(n) for n in competitor_tool_names())

# Inside a candidate brace group: a ``name``/``function`` key whose quoted value
# is one of our tools. Keys are normally double-quoted; single quotes are
# tolerated for a sloppy local model.
_NAMES_A_TOOL = re.compile(
    r"""["']?(?:name|function)["']?\s*:\s*["'](?:%s)["']""" % _TOOL_NAME_ALT
)

# A dangling lead-in that introduces a (now-removed) call, e.g. "Here is the JSON
# for the function call:" or the barer "Here is the JSON:" — a line mentioning a
# json/function/tool and ending in a colon. Only used on the in-place-excision
# fallback path, which is reached only when the whole message was essentially the
# leak, so a broad match here can't eat a real answer.
_DANGLING_LEADIN = re.compile(
    r"(?im)^[^\n]*\b(?:json|function|tool)\b[^\n]*:[ \t]*\n?"
)

_ALL_LEAK_FALLBACK = (
    "Sorry — I got tangled up trying to look that up. Could you ask again?"
)


def _iter_brace_groups(text: str):
    """Yield ``(start, end)`` spans of every top-level ``{...}`` group with
    balanced braces, so an arbitrarily nested call (``{"parameters": {}}``) is
    matched whole. Quotes/escapes aren't interpreted — a leaked tool call never
    contains a braced string literal, and odd text just fails to close a group
    (fail-safe: skipped, never over-stripped)."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield start, i + 1


def _leak_spans(text: str) -> list[tuple[int, int]]:
    """Spans of top-level brace groups that name one of our tools."""
    return [
        (s, e)
        for s, e in _iter_brace_groups(text)
        if _NAMES_A_TOOL.search(text[s:e])
    ]


def _tidy(text: str) -> str:
    text = re.sub(r"^(?:\n[ \t]*\n)+", "", text)
    text = re.sub(r"(?:\n[ \t]*\n)+$", "", text)
    return re.sub(r"(?:\n[ \t]*\n){2,}", "\n\n", text)


def _excise_objects(text: str) -> str:
    """Remove each leaked-call brace group in place (right-to-left so earlier
    spans stay valid) and drop any dangling lead-in line."""
    for s, e in reversed(_leak_spans(text)):
        text = text[:s] + text[e:]
    text = _DANGLING_LEADIN.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return _tidy(text.strip())


def scrub_leaked_tool_calls(text: str) -> str:
    """Remove leaked tool-call JSON naming a known competitor tool from output.

    Coarsest-first, so the smallest legitimate surface is ever cut:

    1. Drop the whole double-newline block containing a JSON object that names a
       known tool — the block is the unit a model uses to separate its
       intent-to-call from the real answer, so this takes the dangling lead-in
       with it while leaving adjacent good paragraphs untouched.
    2. If that would empty the message (lead-in + JSON on consecutive
       single-newline lines), excise just the object(s) and any dangling lead-in
       in place, so the raw literal still never renders.
    3. If even that empties it (the message was *nothing but* a mis-emitted
       call), return a short honest placeholder rather than raw JSON or a blank
       bubble — reachable only when no prose survives, so it can never replace a
       real answer.

    Idempotent; safe on empty input; a no-op when nothing names a known tool. The
    one accepted false positive — a competitor answer that literally quotes one of
    our internal call objects — is byte-indistinguishable from a real leak and
    vanishingly unlikely (the preamble already forbids naming internal tools).
    """
    if not text or "{" not in text:
        return text

    parts = re.split(r"(\n[ \t]*\n)", text)
    kept: list[str] = []
    dropped_any = False
    for part in parts:
        if "{" in part and _leak_spans(part):
            dropped_any = True
            continue
        kept.append(part)

    if not dropped_any:
        return text

    result = _tidy("".join(kept))
    if result.strip():
        return result

    salvaged = _excise_objects(text)
    if salvaged.strip():
        return salvaged
    return _ALL_LEAK_FALLBACK
