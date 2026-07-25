"""Pure demo-instance constants — no ORM / app imports.

Shared by the demo seed (``auth/demo.py``, which builds the DB rows) and the demo
activity simulator (``demo_simulator.py``, which drives the HTTP API). Keeping the
data here means the simulator can import the challenge answers without pulling in
the SQLAlchemy models, argon2, or app config — it only needs ``httpx`` at runtime.
"""

from __future__ import annotations

DEMO_PASSWORD = "password"
DEMO_COMPETITION_NAME = "Flagpost Demo CTF"

# Correct submissions for each seeded challenge, keyed by title — the single
# source of truth shared by the seed and the simulator. The static/multiple-choice/
# dynamic entries are the exact stored answers; the two regex entries are valid
# *examples* matching their patterns.
DEMO_SOLUTIONS: dict[str, str] = {
    # Web
    "Inspect the Source": "flag{view_source_hero}",
    "Little Bobby Tables": "flag{sql_injection_101}",
    "Reflected": "flag{xss_alert_1}",  # regex: matches flag\{xss_[a-z0-9_]+\}
    # Crypto
    "Base What?": "flag{base64_is_not_encryption}",
    "Caesar's Secret": "flag{r0t13_caesar}",  # regex: matches flag\{r0t13_[a-z]+\}
    "XOR-cism": "flag{single_byte_xor_ftw}",
    "RSA Rookie": "flag{small_e_big_mistake}",  # dynamic (decay)
    # Pwn
    "Warm Up": "flag{stack_smashing_101}",  # dynamic (decay)
    "Ret2Win": "flag{ret2win_classic}",  # dynamic (decay)
    # Reversing
    "Strings Attached": "flag{just_run_strings}",
    "Packed Lunch": "flag{upx_unpacked_me}",
    # Forensics
    "Hidden in Plain Sight": "flag{exif_holds_secrets}",
    "Packet Detective": "flag{follow_the_tcp_stream}",
    # Misc / OSINT
    "Quick Quiz": "Capture The Flag",  # MC: the correct option's text
    "Who Am I?": "flag{geolocated_by_reflection}",
}

# Plausible-looking wrong answers the simulator mixes in (failed submissions, so
# the activity isn't a suspicious 100 % solve rate).
DEMO_WRONG_FLAGS: tuple[str, ...] = (
    "flag{not_quite}",
    "flag{try_harder}",
    "flag{almost_there}",
    "flag{just_guessing}",
    "flag{0ff_by_one}",
    "test123",
)
