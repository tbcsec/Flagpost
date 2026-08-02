# ADR-0020: Hash what is only verified, encrypt what must be retrieved

**Status:** Accepted
**Date:** 2026-07-29
**Architecture reference:** `ARCHITECTURE.md` §7.7 (auth), §13.2 (flag storage),
§15 (open questions); ADR-0016 (platform export/import), ADR-0019 (per-install
key derivation). Facility tracked in #109.

## Context

Every piece of sensitive data the platform has stored so far happens to be
**verify-only**: the app never needs the original value back, it only needs to
answer "does the value just supplied match the one on file?". One-way hashing is
the correct and complete answer for all of them, and because the question never
came up, nobody had to make a decision:

- `User.password_hash` — argon2 (ADR-0003)
- `RefreshSession.token_hash` — SHA-256 (ADR-0008)
- `PasswordResetToken.token_hash`, `EmailVerificationToken.token_hash` — SHA-256
- `Challenge.flag_hash` + `flag_salt` — salted hash (§13.2)

`SiteSettings.smtp_password` quietly broke that pattern. The app has to present
the *actual* password to the SMTP server, so hashing is impossible — and with no
encryption facility in the codebase (no `cryptography`/`fernet`/`nacl`, then or
now), it went in as a plain `String` column. Tolerable as a one-off for a
moderate-value credential guarded by `manage_site_settings`.

It stops being a one-off. Two planned features need the same *kind* of
storage — a secret the platform must recover to hand to a third party:

- the AI provider `api_key` (#98), where a leak bills the organiser directly
- the OIDC `client_secret` (#58)

And with no stated rule, each design re-decides independently, badly. That is
already visible: #98's spec asks for *"Encrypted at rest; write-only in the UI
(same treatment as the SMTP password)"* — which is self-contradictory, because
the SMTP-password treatment *is* plaintext — while #58's plan proposes matching
the plaintext precedent and files it as an open question. **The missing rule is
the real problem; the missing facility is the smaller half of it.**

The options actually on the table:

1. **Encrypt everything sensitive, uniformly.** Superficially consistent and
   badly wrong: it would *weaken* every credential above by making it
   recoverable where it is currently not, and verification would have to
   decrypt. A stolen key would expose passwords that argon2 protects even after
   full database disclosure. Rejected outright.
2. **Keep deciding per feature.** The status quo. Produces exactly the drift
   already present in #98 and #58, re-litigates the same question in every PR
   touching a new credential, and makes "did this one get it right?" a review
   burden rather than a property of the design.
3. **Classify by access requirement.** Ask one mechanical question at design
   time — *does anything ever need the original value back?* — and let the
   answer choose the storage. It is answerable from the feature's own
   requirements, with no judgement about how "secret" something feels.

## Decision

Option 3. Sensitive data is classified by whether the platform must recover it:

- **Verified only** — the platform's only need is to compare a supplied value
  against the stored one. Store a **one-way hash**, never encryption. This
  covers passwords, session/reset/verification tokens, and challenge flags, and
  is what the codebase already does.
- **Must be retrieved** — the platform must recover the plaintext to present it
  to an external system (an SMTP server, an OAuth token endpoint, a model
  provider's API). Store it through the **encrypted-at-rest facility** (#109),
  never a plain column.

The deciding question is *"does anything need the original value back?"* — not
"how sensitive does this feel". A new secret-bearing column declares its intent
in the model (an `EncryptedString` column type) rather than at call sites, so
the safe path is the default and an author cannot forget to apply it.

Existing hashed columns are already correct and **must not** be migrated to
encryption. `SiteSettings.smtp_password` is the one existing value that changes
category. Personal API tokens (#75) are verify-only and therefore hashed, not
encrypted.

Keying follows the ADR-0019 pattern — honour an explicit environment variable,
otherwise derive a strong key and persist it to the data volume — so operators
have one mental model for both secrets, and zero-config dev keeps working.

Two things this ADR deliberately does **not** decide, both tracked in #109:
how secret columns appear in the ADR-0016 backup export (ciphertext breaks
cross-install portability, plaintext preserves the current exposure — a genuine
tension needing its own resolution), and the migration mechanics for the
existing plaintext `smtp_password`.

## Consequences

- **Positive:** one mechanical question replaces a per-feature debate, so #98
  and #58 inherit an answer instead of carrying an open question. Hashed
  columns are explicitly protected from a well-meaning "encrypt all the
  secrets" refactor that would weaken them. Declaring encryption in the column
  type makes the correct behaviour the default rather than a thing reviewers
  must remember to check. And it removes the contradiction currently sitting in
  #98's spec.
- **Negative / cost:** the facility has to exist before the rule can be
  followed (#109), which adds a `cryptography` dependency and a second piece of
  operator key state alongside `JWT_SECRET`. Losing the key means stored
  secrets are unrecoverable and must be re-entered — recoverable, but an
  operational footgun worth documenting. Encrypted columns are not searchable
  or indexable; irrelevant for these values, but it forecloses that option
  silently if someone forgets. The protection is also **bounded and should be
  described as such**: a key on the same host defends against database-only
  disclosure (a leaked export, a stolen dump, a misconfigured replica, a
  discarded disk) and **not** against an attacker with code execution on the
  application host, because the app must be able to decrypt.
- **Forecloses:** no new plaintext-recoverable secret columns. A future feature
  that genuinely needs a *searchable* secret, or that wants to hash something
  an integration must actually send, has to come back and change this ADR
  rather than quietly diverge.

## Resolutions (the two items #109 left open)

Both deferred questions were settled when #109 applied the facility to
`SiteSettings.smtp_password`:

- **Backup export.** A retrievable secret is **excluded** from the ADR-0016
  export and re-entered after a restore — whole-table for `oidc_providers`,
  per-column (`Spec.secret_columns`) for `smtp_password`, which shares an
  otherwise-portable row. Ciphertext in a backup is useless on a target install
  with a different key, and shipping the plaintext would preserve exactly the
  exposure the encryption is meant to remove. This matches the "config is
  install-specific, re-enter on new infra" posture SMTP and OIDC already have.
- **Migration mechanics.** The `EncryptedString` type tolerates plaintext on
  read and re-encrypts on write, so no schema change is needed. For the one
  existing value, a one-shot data migration (`e7c1f9a4b206`) encrypts it in
  place on upgrade rather than waiting for a chance re-save, so it isn't left at
  rest in the clear indefinitely.

## Decryption raises, so encrypted columns on hot-path tables are deferred

`EncryptedString` decrypts when the column loads and **raises** on a key
mismatch — deliberately, so a key problem surfaces loudly rather than as a
silent "no secret". The corollary: an eager (non-deferred) encrypted column
makes *loading the row at all* fail when the key is wrong, taking down every
read of that row, not just the ones that need the secret.

That is fine for a row read only where the secret is used (an OIDC provider,
loaded during the login flow), but wrong for a row on a hot or recovery path.
`SiteSettings` is read on the public pre-auth branding path and on the admin
settings page — the page an operator uses to re-enter a secret after losing the
key. So `smtp_password` is a **deferred** column: ordinary loads never touch it,
the mailer (its one point of use) undefers it explicitly, and `smtp_password_set`
is derived from the raw ciphertext without decrypting. A lost key then breaks
only the actual SMTP send, leaving the recovery path usable. New encrypted
columns on frequently-loaded tables should follow this pattern.

## Key rotation

Rotating `SECRET_ENCRYPTION_KEY` (or losing the key file) invalidates every
stored secret: `EncryptedString` raises on a decrypt failure with instructions
to restore the key or clear and re-enter the affected values. That is the
supported rotation path today — **stop, swap the key, re-enter the handful of
secrets**. Zero-downtime rotation (decrypt-with-old, re-encrypt-with-new,
keeping a key history) is intentionally **not** built: with two secret columns
in the whole platform the demand doesn't justify the key-management surface. If
that changes it's a follow-up, not a change to this decision.
