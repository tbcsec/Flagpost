"""Regex flag matching (ADR-0018): normal grading, malformed-pattern fail-closed,
and — the point of the ADR — that a catastrophic-backtracking pattern is contained
by the match timeout instead of hanging the single-process runtime.

Tests are ``async def`` only to sit on the suite's asyncio machinery (the autouse
schema fixture is async); ``verify_regex_flag`` itself is synchronous.
"""

import time

from utils.flags import REGEX_MATCH_TIMEOUT_SECONDS, verify_regex_flag


async def test_regex_flag_matches_and_rejects():
    assert verify_regex_flag("CTF{123}", r"CTF\{[0-9]+\}", False)
    assert not verify_regex_flag("CTF{abc}", r"CTF\{[0-9]+\}", False)
    # fullmatch semantics — a partial match isn't a match.
    assert not verify_regex_flag("xCTF{1}", r"CTF\{[0-9]+\}", False)


async def test_regex_flag_case_insensitivity():
    assert verify_regex_flag("ctf{ABC}", r"CTF\{[A-Z]+\}", True)
    assert not verify_regex_flag("ctf{ABC}", r"CTF\{[A-Z]+\}", False)


async def test_malformed_pattern_fails_closed():
    # An unbalanced group must fail closed (no match), never raise / 500.
    assert verify_regex_flag("anything", r"CTF\{(", False) is False


async def test_catastrophic_pattern_is_timed_out_not_hung():
    """A pathological pattern that backtracks ~forever under stdlib ``re`` must
    return within a small multiple of the match budget, proving ADR-0018 contains
    it rather than freezing the process."""
    evil = r"(a+)+$"
    trigger = "a" * 45 + "!"  # 45 a's then a non-match → exponential backtracking
    start = time.monotonic()
    result = verify_regex_flag(trigger, evil, False)
    elapsed = time.monotonic() - start
    assert result is False
    # Bounded by the timeout (+ scheduling slack) — not the effectively infinite
    # time stdlib `re` would spend here.
    assert elapsed < REGEX_MATCH_TIMEOUT_SECONDS + 2.0
