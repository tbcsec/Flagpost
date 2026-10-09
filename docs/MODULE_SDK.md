# Building & signing content packs — the module SDK

> Status: **v1** (#390, ADR-0040). Covers **content packs** (Tier 0) end-to-end.
> Build/validate for declarative/code modules works too; installing them lands
> with those tiers (#388/#391).

The SDK is the authoring counterpart to the install pipeline (`utils/marketplace_verify`
+ `utils/content_packs`): it builds a signed `.fpmod` artifact that a registry
serves, that the verifier checks, and that the installer applies. Because it reuses
the platform's own manifest model and verifier, "valid here" means "installs
there" — the `tests/test_sdk.py` suite pins that a built+signed pack verifies and
parses on the install side.

Run it from `backend/`:

    python -m sdk <command>

## The loop

1. **Scaffold** a pack (a manifest that already validates + the payload layout):

       python -m sdk init ./my-theme --kind pack --pack-type theme --id you.my-theme --name "My Theme"

   A theme pack is scaffolded with a starter `payload/themes.json`; for a challenge
   pack, drop a ctfcli export at `payload/challenges.zip`.

2. **Build** — validates the manifest, then deterministically zips the source
   (same source → same digest, the content address):

       python -m sdk build ./my-theme -o my-theme.fpmod
       # digest: sha256:…

3. **Generate a signing key** once; keep the private key secret:

       python -m sdk keygen
       # public_key:  <base64>
       # private_key: <base64>

4. **Sign** the artifact:

       python -m sdk sign my-theme.fpmod --key <private-b64> --key-id you:1 -o my-theme.sig.json

5. **Publish** the artifact + its digest + signature through the registry
   (`resolve-response`), or hand them to an operator for a file/URL install.

## Trust setup (operator side)

An operator installs a signed pack only if it validates under their trust policy.
For a third-party key: **Admin → Marketplace → Registry & trust → Trusted keys**,
add the **public** key (`key_id` + base64 public key; mark it *verified* to accept
under the `verified` policy). The code/URL install then verifies the signature
against it. The project **root** key (for `official`/`verified`) is configured out
of band via `MARKETPLACE_ROOT_PUBLIC_KEY`.

## Commands

| Command | Does |
|---|---|
| `keygen [--json]` | Generate an ed25519 keypair (base64). |
| `init DEST --kind pack\|module --id ID [--pack-type …] [--trust-tier …]` | Scaffold a born-valid skeleton. |
| `build SRC -o OUT.fpmod` | Validate the manifest + build a deterministic artifact; print its digest. |
| `sign ARTIFACT --key PRIV [--key-id ID] [-o SIG.json]` | Detached ed25519 signature in the wire shape. |
| `validate SRC\|ARTIFACT` | Validate a source tree or a built artifact's manifest. |

## Notes

- **Signing ⟂ entitlement** (docs/MODULES.md §7): the signature proves authorship +
  integrity; a paid artifact's entitlement is a separate, download-time concern.
- The `.fpmod` container is a deterministic zip (sorted entries, fixed mtime).
- Module (code/declarative) scaffolding is included for authoring, but those tiers
  aren't installable yet (#388/#391) — `build`/`validate` work; `install` lands
  with them.
