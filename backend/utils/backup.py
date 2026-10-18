"""Platform export / import — a full-fidelity, selective backup (Phase 9 owner ask).

Export serialises whole tables to a single versioned JSON document; the admin
picks which **sections** to include (checkboxes). Import reads that document back
**additively** — it *creates records that don't already exist and never modifies
or deletes* what's there (owner decision). See ADR-0016.

Design: rather than hand-code every entity, a generic column (de)serialiser plus
a declared ``SPECS`` registry does the work. Each :class:`Spec` names a table,
its section, which FK columns to remap (via id maps built during import), whether
it is *owned by a competition* (so it's skipped wholesale when that competition
already exists), and how to detect an already-present row (``natural_key``). New
ids are minted on create and cross-references rewritten through the id maps, so a
document restores cleanly into a different install.

Excluded by design: ``refresh_sessions`` and ``api_tokens`` (live bearer
credentials), and the transient/derived ``notifications`` / ``collab_documents``
/ ``dashboard_layouts`` / ``ai_conversations`` / ``ai_messages`` (chat transcripts
whose retention follows the competition lifecycle, #98) — none belong in a
portable backup. ``ai_competition_settings`` (the per-competition competitor-
assistant toggles, #98 Phase 3) is likewise omitted: it depends on install-level
AI provider config that itself isn't exported, so it resets to its safe defaults
(assistant off, challenge-metadata off) on restore rather than travelling with a
competition.

Also excluded: the code judge's ``judge_settings`` and ``judge_languages``
(#447, ADR-0042). The settings point at a host-specific container endpoint (the
``instance_settings`` reasoning), and a language *is* an image plus commands the
judge executes — exactly the kind of row GHSA-x8v4 showed must not be plantable
through an import. An operator restoring onto new infrastructure re-registers
languages, which is also when they should check the images.

Also excluded, for the same credential reason: ``identity_providers``,
``user_external_identities`` and ``auth_login_states`` (#58, ADR-0022 §7), and
``ai_settings`` (#98, ADR-0023). A provider row holds a **secret** — an OIDC
client secret, a SAML SP key or LDAP bind password, or the AI provider's API key —
a credential the operator was issued, encrypted with a per-install key
(ADR-0020), so it would restore as undecryptable ciphertext on any other install
anyway. The AI/provider endpoint config is install-specific and re-entered on
restore, which is also the moment to rotate the secret. The identity links are meaningless without their
providers, and login states are in-flight requests measured in minutes. An
operator restoring onto new infrastructure re-enters provider config, which is
also the moment to rotate the secret.

The credential exclusion is the load-bearing one. Only a token's SHA-256 is
stored, but that hash is exactly what authentication compares against: exporting
it and importing elsewhere would re-arm the original raw token on the target
install, bound by natural key to whichever local account matches — grafting a
working credential the receiving operator never issued and cannot trace. Import
is additive and cross-install by design (ADR-0016), so credentials must not ride
along. Tokens are per-install and cheap to re-issue from /profile.

The same logic applies **per column** to a retrievable secret that lives on an
otherwise-portable row: ``site_settings.smtp_password`` is encrypted with a
per-install key (ADR-0020), so it's dropped via ``Spec.secret_columns`` while the
rest of the settings row (branding, rules, registration policy) still travels.
SMTP config is install-specific and re-entered on restore — the same posture as
the excluded OIDC provider secret.

One column is deliberately *not* dropped despite carrying passwords:
``site_settings.demo_credentials`` (#360) is a list of throwaway demo-account
credentials, in **plaintext by necessity** (the login card fills them). It rides
the backup on purpose — the point is that a demo baseline carries its own
click-to-login card — and is only ever exposed on an instance running in demo
mode. This is one more reason a backup file is sensitive (ADR-0016): a demo
export contains those plaintext demo passwords.
"""

from __future__ import annotations

import asyncio
import base64
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable
from uuid import uuid4

from sqlalchemy import DateTime, LargeBinary, func, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from auth.containment import holds_every_permission
from auth.membership import effective_permissions
from db import UtcDateTime, utcnow
from models.announcement import Announcement
from models.attachment import Attachment
from models.audit_log import AuditLogEntry
from models.automation import Achievement, AutomationRule
from models.challenge import Category, Challenge
from models.challenge_instancing import ChallengeDeployment
from models.registration_field import RegistrationField
from models.competition import Competition, generate_invite_code
from models.competition_module import CompetitionModule
from models.feedback import (
    ChallengeRating,
    Survey,
    SurveyAnswer,
    SurveyQuestion,
    SurveyResponse,
)
from models.hint import Hint, HintReveal
from models.judge_problem import JudgeProblem
from models.mc_guess_reset import MCGuessReset
from models.page import Page
from models.role import Role, RoleAssignment
from models.score_adjustment import ScoreAdjustment
from models.site_settings import (
    DEFAULT_ACCENT,
    DEFAULT_PALETTE,
    DEFAULT_PLATFORM_NAME,
    SITE_SETTINGS_ID,
    SiteSettings,
)
from models.theme_preset import ThemePreset
from models.submission import Submission
from models.team import Team, TeamMembership
from models.ticket import Ticket, TicketMessage
from models.ticket_attachment import TicketAttachment
from models.user import User
from storage.base import ObjectStorage
from utils.theme_tokens import (
    RESERVED_PALETTE_IDS,
    ThemeValidationError,
    validate_theme_mode,
    validate_theme_tokens,
)
from utils.uploads import safe_filename

SCHEMA_VERSION = 1

# Everything the ``rebuild_object`` hooks may unpack across one import — the
# problem-package import's ceiling (``problem_package.MAX_TOTAL_DECOMPRESSED``),
# so a single document can't carry hundreds of maximal problems (GHSA-4wrj).
MAX_IMPORT_UNPACKED = 512 * 1024 * 1024

# The selectable export/import units, in the order the UI lists them.
SECTIONS: tuple[str, ...] = (
    "site_settings",
    "users",
    "roles",
    "competitions",
    "automations",
    "audit_log",
)


# --- generic column (de)serialisation ---------------------------------------

def serialize_row(obj, skip: tuple[str, ...] = ()) -> dict:
    """A JSON-safe dict of every column: datetimes → ISO strings, bytes → base64,
    everything else (incl. ``JSON`` list/dict columns) passes through.

    ``skip`` names columns to omit entirely — used for secret columns. It skips
    *before* the ``getattr``, which matters: a deferred secret (smtp_password)
    that wasn't undeferred would otherwise trigger a forbidden async lazy-load
    here, and reading it at all would decrypt it. Skipping keeps the secret out
    of the export without ever touching it."""
    out: dict = {}
    for col in obj.__table__.columns:
        if col.name in skip:
            continue
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            out[col.name] = val.isoformat()
        elif isinstance(val, (bytes, bytearray)):
            out[col.name] = base64.b64encode(val).decode("ascii")
        else:
            out[col.name] = val
    return out


def _typed_cols(model) -> tuple[set[str], set[str]]:
    dt = {c.name for c in model.__table__.columns if isinstance(c.type, (DateTime, UtcDateTime))}
    bin_ = {c.name for c in model.__table__.columns if isinstance(c.type, LargeBinary)}
    return dt, bin_


def load_row(model, row: dict) -> dict:
    """Inverse of :func:`serialize_row`, keyed off column types; drops any keys
    that aren't real columns (e.g. the attachment's side-car ``_object_data``)."""
    dt_cols, bin_cols = _typed_cols(model)
    cols = {c.name for c in model.__table__.columns}
    out: dict = {}
    for key, val in row.items():
        if key not in cols:
            continue
        if val is not None and key in dt_cols:
            val = datetime.fromisoformat(val)
        elif val is not None and key in bin_cols:
            val = base64.b64decode(val)
        out[key] = val
    return out


# --- registry ----------------------------------------------------------------

NaturalKey = Callable[[AsyncSession, dict], Awaitable[str | None]]


@dataclass(frozen=True)
class Spec:
    table: str
    model: type
    section: str
    id_map: str | None = None
    # (column, map_name, required): if the column is non-null it's rewritten via
    # the map; ``required`` non-null values that don't resolve skip the whole row,
    # otherwise the column is nulled (mirrors SET NULL vs CASCADE FKs).
    remaps: tuple[tuple[str, str, bool], ...] = ()
    owned_by_competition: bool = False
    natural_key: NaturalKey | None = None
    regenerate: tuple[str, ...] = ()
    singleton: bool = False
    keep_id: bool = False
    # Columns dropped from the export. For an `EncryptedString` secret, the
    # generic serialiser reads through the ORM and hands back *plaintext*, and
    # ciphertext would be undecryptable on a target install with a different key
    # anyway — so a per-install secret has no business in a portable backup
    # (ADR-0020). This is the column-level form of the whole-table exclusion the
    # identity_providers row gets; site_settings can't be dropped wholesale because
    # its branding/rules/registration fields are portable and wanted. Import
    # tolerates the absent key (load_row only sets present columns), so the
    # secret is simply re-entered after a restore.
    secret_columns: tuple[str, ...] = ()
    # Columns an import must NEVER write, even when present in the payload. These
    # are install-local facts, not portable content: clearing
    # `site_settings.setup_completed_at` on import would re-open the
    # unauthenticated first-run setup wizard on a live install (security F2), and
    # the update check's state would let a document stop the check or hide its
    # notice (GHSA-4wrj). Unlike `secret_columns` (dropped on *export*), these are
    # ignored on *import* — an attacker who hand-crafts the backup can't set them.
    immutable_columns: tuple[str, ...] = ()
    # Set for tables whose rows point at an object-storage blob. The engine then
    # carries the bytes in a ``_object_data`` side-car on export and re-puts them
    # on import under a freshly-minted key built by this callable (the old key
    # embeds ids that no longer exist in the destination install). Declaring it
    # per-table keeps the object handling generic instead of special-casing table
    # names in the export/import loops.
    object_key_for: Callable[[dict], str] | None = None
    # For an object the app later *parses* (the judge's test-data zip), the
    # side-car bytes are re-derived on import instead of stored verbatim: called
    # (off the event loop) with the validated row, the decoded bytes and how
    # many bytes this import may still unpack (``MAX_IMPORT_UNPACKED``), it
    # returns the bytes to store and how many it unpacked, and may rewrite the
    # row to match. ``validate_row`` never sees the bytes, so without this an
    # archive's contents skip every authoring limit (GHSA-4wrj). Raises
    # :class:`ImportError_` to reject.
    rebuild_object: Callable[[dict, bytes, int], tuple[bytes, int]] | None = None
    # A per-row content validator run on import, right before the ORM row is
    # built. ``load_row`` does no content validation, so a table whose CRUD routes
    # enforce a content invariant (e.g. ``theme_presets``' ``#RRGGBB`` token
    # boundary) must repeat it here — otherwise a hand-crafted backup bypasses the
    # boundary the interactive routes guard (#323 review). It raises
    # :class:`ImportError_` to reject the whole document with a 400, or returns
    # ``False`` to drop just this row (counted as skipped).
    validate_row: Callable[[dict], bool | None] | None = None
    # A global grant this table needs on top of its section's gate, for a table
    # that rides a section whose grant doesn't govern it: ``pages`` travels with
    # site_settings (older files carry it there, so it can't move) but is
    # authored under manage_pages (GHSA-3r5x). When the actor lacks it, export
    # leaves the table out and import skips its rows; internal callers (no
    # actor) move it like any other table.
    permission: str | None = None


def _stored_name(row: dict, default: str) -> str:
    """The row's filename as the upload routes store it: a bare leaf, never a
    path (GHSA-wvjv-56qv-9v42)."""
    name = row.get("filename")
    return safe_filename(name if isinstance(name, str) else None, default=default)


# The key builders run before validate_row, so they clean the name themselves.
def _challenge_object_key(row: dict) -> str:
    return f"{row['competition_id']}/{row['challenge_id']}/{uuid4().hex}_{_stored_name(row, 'file')}"


def _judge_object_key(row: dict) -> str:
    from utils.judge_testdata import new_key

    return new_key(row["competition_id"], row["challenge_id"])


def _ticket_object_key(row: dict) -> str:
    return f"{row['competition_id']}/tickets/{row['ticket_id']}/{uuid4().hex}_{_stored_name(row, 'image')}"


async def _nk_user(db: AsyncSession, row: dict) -> str | None:
    name = (row.get("display_name") or "").strip().lower()
    hit = await db.scalar(select(User.id).where(func.lower(User.display_name) == name))
    if hit is None and row.get("email"):
        hit = await db.scalar(
            select(User.id).where(func.lower(User.email) == row["email"].strip().lower())
        )
    return hit


async def _nk_role(db: AsyncSession, row: dict) -> str | None:
    return await db.scalar(select(Role.id).where(Role.name == row["name"]))


async def _nk_page(db: AsyncSession, row: dict) -> str | None:
    return await db.scalar(select(Page.id).where(Page.slug == row["slug"]))


async def _nk_theme(db: AsyncSession, row: dict) -> str | None:
    # The id is a stable slug, so it's the natural key: a preset already present
    # by that id is left untouched (additive import), matching pages.
    return await db.scalar(
        select(ThemePreset.id).where(ThemePreset.id == row.get("id"))
    )


def _validate_site_settings_row(row: dict) -> None:
    """Enforce the boundary the settings routes apply — ``SiteSettingsUpdate``
    (branding, the sign-in notice's size/shape cap, the demo accounts),
    ``OperationalSettingsUpdate``, ``RulesSettingsUpdate`` and the logo upload's
    checks — on an imported ``site_settings`` row. ``load_row`` does no content
    validation, and most of this row is served on the *unauthenticated* GET
    /api/site-settings paint (the logo on its own public GET), so without this
    a hand-crafted backup could publish what no route accepts (#360 review,
    GHSA-4wrj). Strict, like ``_validate_deployment_row``: the raw stored types
    are the contract. What's stored is the validated value, normalised as the
    route would store it (unknown keys dropped from a demo account, domains
    lower-cased, an empty notice null). Only the columns present are judged —
    a partial row leaves the rest as they are."""
    from pydantic import ValidationError

    from routers.site_settings import MAX_LOGO_BYTES
    from schemas.rules import RulesSettingsUpdate
    from schemas.site_settings import OperationalSettingsUpdate, SiteSettingsUpdate
    from utils.image_sniff import exceeds_pixel_budget, sniff_logo_type

    columns = SiteSettings.__table__.columns
    # The schemas' required fields at their fresh-install values, so a row that
    # omits one is judged on what it does carry.
    baseline = {
        "platform_name": DEFAULT_PLATFORM_NAME,
        "default_palette": DEFAULT_PALETTE,
        "accent": DEFAULT_ACCENT,
        "registration_open": True,
    }
    for schema in (SiteSettingsUpdate, OperationalSettingsUpdate, RulesSettingsUpdate):
        fields = {key: val for key, val in baseline.items() if key in schema.model_fields}
        present: list[str] = []
        for key in schema.model_fields:
            if key not in row or key not in columns:
                continue
            if row[key] is None:
                if not columns[key].nullable:
                    raise ImportError_(f"site_settings.{key} can't be empty")
                continue  # an unset optional column
            fields[key] = row[key]
            present.append(key)
        try:
            validated = schema.model_validate(fields, strict=True).model_dump()
        except ValidationError as exc:
            raise ImportError_(f"site_settings: {exc}") from exc
        for key in present:
            row[key] = validated[key]

    # The logo is held to the upload route's checks, and its served type is
    # always the one sniffed from the bytes — never the document's say-so. A
    # logo that fails them (one stored before those checks existed, say) is
    # left out rather than failing the restore: the current logo stays.
    logo_keys = ("logo_data", "logo_content_type", "logo_updated_at")
    if "logo_data" not in row:
        row.pop("logo_content_type", None)
        return
    if row["logo_data"] is None:
        row["logo_content_type"] = None
        return
    try:
        data = base64.b64decode(row["logo_data"], validate=True)
    except (TypeError, ValueError):
        data = b""
    content_type = sniff_logo_type(data) if data else None
    if (
        content_type is None
        or len(data) > MAX_LOGO_BYTES
        or exceeds_pixel_budget(data, content_type)
    ):
        for key in logo_keys:
            row.pop(key, None)
        return
    row["logo_content_type"] = content_type


def _validate_theme_row(row: dict) -> None:
    """Enforce the theme boundary the CRUD routes apply — ``validate_theme_tokens``
    / ``validate_theme_mode`` plus the reserved-id guard — on an imported
    ``theme_presets`` row. ``load_row`` does no content validation and
    ``ThemePreset.tokens`` is a generic JSON column, so without this a
    hand-crafted backup could persist a non-``#RRGGBB`` (or non-dict) token map, a
    bad mode, or a reserved id that shadows a built-in palette — bypassing the
    module's whole safety boundary (``theme_tokens`` header) and, once named by
    ``default_palette``, 500-ing the *public* site-settings paint (#323 review)."""
    try:
        validate_theme_tokens(row.get("tokens"))
        validate_theme_mode(row.get("mode"))
    except ThemeValidationError as exc:
        raise ImportError_(f"theme_presets {row.get('id')!r}: {exc}") from exc
    if row.get("id") in RESERVED_PALETTE_IDS:
        raise ImportError_(
            f"theme_presets id {row.get('id')!r} collides with a built-in palette"
        )


def _validate_deployment_row(row: dict) -> None:
    """Enforce the deployment-authoring boundary the CRUD route applies
    (``DeploymentUpdate.validate_shape``) on an imported ``challenge_deployments``
    row. ``load_row`` does no content validation, so without this a hand-crafted
    backup could persist an internally-inconsistent spec (e.g. a ``docker`` spec
    with no image, a ``tcp`` spec with no ports, or a ``unique_per_instance``
    template missing its ``<random>`` placeholder) that the interactive editor
    would have rejected — the #323/#324 lesson: the backup import must repeat any
    invariant the route guards.

    One exception, made in place so the row that lands is the cleaned one:
    ``resource_limits`` is first normalised into today's bounds
    (``normalise_resource_limits``) rather than validated as-is. GHSA-vgrr
    tightened those bounds after v1.7.x, and refusing a value an earlier
    release accepted would fail the whole restore of an otherwise-valid
    backup; the cleaned value is the one the provisioners would run anyway."""
    from pydantic import ValidationError

    from schemas.instances import DeploymentUpdate
    from utils.provisioners import normalise_resource_limits

    if "resource_limits" in row:
        row["resource_limits"] = normalise_resource_limits(row["resource_limits"])

    # STRICT validation — no coercion. ``load_row`` persists the raw row as-is, so
    # validating a *coerced* copy (e.g. accepting "1337" as a port and then
    # storing the string) would let wrong types through the boundary; strict mode
    # makes the raw types themselves the contract. It also rejects a row missing
    # the NOT-NULL ``backend`` (absent → the required field errors) with a clean
    # 400 instead of a NULL-insert 500 at flush. Extra keys (id/timestamps) are
    # ignored. Our own exports are always correctly typed, so this only bites a
    # hand-crafted backup.
    try:
        upd = DeploymentUpdate.model_validate(row, strict=True)
    except ValidationError as exc:
        raise ImportError_(f"challenge_deployments {row.get('id')!r}: {exc}") from exc
    err = upd.validate_shape()
    if err:
        raise ImportError_(f"challenge_deployments {row.get('id')!r}: {err}")


def _validate_registration_field_row(row: dict) -> None:
    """Re-apply the field-authoring invariants (``RegistrationFieldIn``) on an
    imported ``registration_fields`` row (#350). ``load_row`` does no content
    validation, so without this a hand-crafted backup could persist an invalid
    field — an unknown ``field_type`` or a ``select`` with no options — that the
    authoring route would reject. The #324 lesson. Strict, so the raw stored
    types are the contract; extra keys (id/timestamps/competition_id) are
    ignored."""
    from pydantic import ValidationError

    from schemas.registration_field import RegistrationFieldIn

    try:
        RegistrationFieldIn.model_validate(row, strict=True)
    except ValidationError as exc:
        raise ImportError_(f"registration_fields {row.get('id')!r}: {exc}") from exc


def _validate_automation_rule_row(row: dict) -> None:
    """Re-apply the rule-authoring invariant (``schemas.automation.RuleCreate``)
    on an imported ``automation_rules`` row (GHSA-x8v4). ``load_row`` does no
    content validation, so without this a crafted backup could persist arbitrary
    ``trigger_type``/``actions`` JSON the visual builder's schema would reject —
    an unknown trigger, or an action with no valid ``type`` — which the engine
    would then execute (score tampering, forged announcements, webhook exfil of
    event payloads). The #323/#324 class. The import route's section gate
    additionally bounds *who* may import the automations section at all."""
    from pydantic import ValidationError

    from schemas.automation import PersonalRuleCreate, RuleCreate

    # A personal rule (owner set) is held to the personal schema — notify-self
    # only — exactly as the personal route holds it; validating it as an org
    # rule would let a backup plant an owner-only rule nobody else can see that
    # still runs org actions (GHSA-x8v4-p7x5-v6c8).
    schema = PersonalRuleCreate if row.get("owner_user_id") else RuleCreate
    try:
        schema.model_validate(
            {
                "name": row.get("name"),
                "trigger_type": row.get("trigger_type"),
                "conditions": row.get("conditions") or [],
                "actions": row.get("actions") or [],
            }
        )
    except ValidationError as exc:
        raise ImportError_(f"automation_rules {row.get('id')!r}: {exc}") from exc


def _validate_page_row(row: dict) -> None:
    """Re-apply the page-authoring invariants (``schemas.page.PageCreate``) on an
    imported ``pages`` row (GHSA-4wrj). ``load_row`` does no content validation,
    so without this a crafted backup could publish a page — ``visibility:public``,
    ``draft:false`` — that skips the slug regex, the reserved-slug list, and the
    rich-text size/shape cap the authoring route enforces, landing on the
    unauthenticated ``GET /api/pages/{slug}``. The #323/#324 class. Validates the
    content subset (``PageCreate`` forbids extra keys, so id/timestamps/
    competition_id are dropped first)."""
    from pydantic import ValidationError

    from schemas.page import PageCreate

    fields = {
        key: row[key]
        for key in (
            "slug", "title", "content", "icon", "nav_order", "visibility", "draft"
        )
        if key in row
    }
    try:
        PageCreate.model_validate(fields)
    except ValidationError as exc:
        raise ImportError_(f"pages {row.get('slug')!r}: {exc}") from exc


def _rebuild_judge_testdata(row: dict, blob: bytes, allowance: int) -> tuple[bytes, int]:
    """Store an imported problem's test data only as a zip rebuilt from its
    contents, held to the caps an upload is (GHSA-4wrj): exactly the members
    the manifest implies, each within the per-file and per-problem limits, and
    within what the import may still unpack. The stored zip is what the problem
    page, the editor and the judge worker read, so a crafted one must never
    reach storage; the manifest is rewritten from what was actually read."""
    from utils import judge_testdata as td

    try:
        data, row["testcases"] = td.rebuild(blob, row["testcases"], budget=allowance)
    except td.TestdataError as exc:
        raise ImportError_(f"judge_problems {row.get('id')!r}: {exc}") from exc
    return data, sum(t["input_bytes"] + t["answer_bytes"] for t in row["testcases"])


def _validate_judge_problem_row(row: dict) -> None:
    """Re-apply the problem-authoring invariants (``JudgeProblemUpdate``) on an
    imported ``judge_problems`` row (#447) — limits in range, a known compare
    mode, a list of language keys — plus the manifest shape the editor and the
    executor rely on. The #323/#324 class.

    The row must also point only at its *own* re-stored zip: the engine mints a
    fresh ``{competition}/judge/{challenge}/`` key when the side-car carries
    bytes, so any other key (a problem exported with no test data, or a crafted
    row naming another competition's object) is dropped with its manifest
    rather than imported as a dangling or foreign reference."""
    from pydantic import ValidationError

    from schemas.judge import JudgeProblemUpdate

    where = f"judge_problems {row.get('id')!r}"
    try:
        JudgeProblemUpdate.model_validate(
            {
                key: row[key]
                for key in (
                    "time_limit_ms", "memory_limit_mb", "output_limit_kb",
                    "compare_mode", "float_tolerance", "allowed_languages",
                    "case_insensitive",
                )
                if key in row
            },
            strict=True,
        )
    except ValidationError as exc:
        raise ImportError_(f"{where}: {exc}") from exc
    # An imported package's accepted solution (#451): within the submission cap,
    # and a language key fit to name an exported file.
    from schemas.judge import _KEY_RE
    from utils.problem_package import MAX_SOURCE_BYTES

    language, source = row.get("reference_language"), row.get("reference_source")
    if language is not None and not (isinstance(language, str) and _KEY_RE.fullmatch(language)):
        raise ImportError_(f"{where}: reference_language must be a language key")
    if source is not None and not (isinstance(source, str) and len(source.encode()) <= MAX_SOURCE_BYTES):
        raise ImportError_(f"{where}: reference_source must be text within {MAX_SOURCE_BYTES // 1024} KB")

    own = f"{row.get('competition_id')}/judge/{row.get('challenge_id')}/"
    if not str(row.get("object_key") or "").startswith(own):
        row["object_key"] = None
        row["testcases"] = []
        return
    manifest = row.get("testcases")
    if not isinstance(manifest, list) or not manifest:
        raise ImportError_(f"{where}: test data without a test-case list")
    for entry in manifest:
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and isinstance(entry.get("sample"), bool)
            and isinstance(entry.get("input_bytes"), int)
            and isinstance(entry.get("answer_bytes"), int)
        ):
            raise ImportError_(f"{where}: malformed test-case entry")


def _validate_attachment_row(row: dict) -> bool:
    """Reduce an imported attachment's ``filename`` to the bare leaf the upload
    route stores (GHSA-wvjv-56qv-9v42). ``load_row`` does no content validation,
    so a crafted backup — or one taken before the ctfcli importer cleaned names
    — would otherwise land a traversal name that the challenge export writes
    into its zip. Normalised rather than refused, so such a backup still
    restores. The #323/#324 class.

    The row is kept only if it points at its *own* re-stored object, as
    ``_validate_judge_problem_row`` requires. With no bytes in the backup it
    would keep the source install's key — or any key a crafted row names,
    another competition's object included, which the download route would
    then serve and a purge delete — so it's dropped."""
    row["filename"] = _stored_name(row, "file")
    own = f"{row.get('competition_id')}/{row.get('challenge_id')}/"
    return str(row.get("object_key") or "").startswith(own)


def _validate_ticket_attachment_row(row: dict) -> bool:
    """The same for a ticket's image (its route's default name is ``image``)."""
    row["filename"] = _stored_name(row, "image")
    own = f"{row.get('competition_id')}/tickets/{row.get('ticket_id')}/"
    return str(row.get("object_key") or "").startswith(own)


async def _nk_competition(db: AsyncSession, row: dict) -> str | None:
    return await db.scalar(select(Competition.id).where(Competition.name == row["name"]))


async def _nk_assignment(db: AsyncSession, row: dict) -> str | None:
    stmt = select(RoleAssignment.id).where(
        RoleAssignment.user_id == row.get("user_id"),
        RoleAssignment.role_id == row.get("role_id"),
        RoleAssignment.competition_id.is_(None)
        if row.get("competition_id") is None
        else RoleAssignment.competition_id == row.get("competition_id"),
    )
    return await db.scalar(stmt)


async def _nk_automation(db: AsyncSession, row: dict) -> str | None:
    stmt = select(AutomationRule.id).where(
        AutomationRule.name == row.get("name"),
        AutomationRule.trigger_type == row.get("trigger_type"),
        AutomationRule.competition_id.is_(None)
        if row.get("competition_id") is None
        else AutomationRule.competition_id == row.get("competition_id"),
        AutomationRule.owner_user_id.is_(None)
        if row.get("owner_user_id") is None
        else AutomationRule.owner_user_id == row.get("owner_user_id"),
    )
    return await db.scalar(stmt)


async def _nk_audit(db: AsyncSession, row: dict) -> str | None:
    return await db.scalar(select(AuditLogEntry.id).where(AuditLogEntry.id == row.get("id")))


_COMP = ("competition_id", "competition", True)

# Order matters: a table's referenced entities must be imported before it.
SPECS: tuple[Spec, ...] = (
    Spec("site_settings", SiteSettings, "site_settings", singleton=True,
         secret_columns=("smtp_password",),
         immutable_columns=(
             "setup_completed_at", "last_update_check_at", "last_update_attempt_at",
             "last_update_check_status", "latest_known_version", "dismissed_update_version",
         ),
         validate_row=_validate_site_settings_row),
    # Custom pages (#198, ADR-0034). Site-level, no foreign keys and no secrets,
    # so it needs nothing but a natural key: `slug` is unique and is the page's
    # address, which makes it the right identity for the additive import — a
    # restore onto an install that already has /p/about leaves that page alone
    # rather than creating a second one that can't have the URL. Drafts and
    # publishing are manage_pages business, which manage_site_settings isn't.
    Spec("pages", Page, "site_settings", id_map="page", natural_key=_nk_page,
         validate_row=_validate_page_row, permission="manage_pages"),
    # Custom brand themes (#323) — portable branding. keep_id: the slug id is what
    # default_palette points at, so it must survive the round-trip. created_by is
    # install-local authorship (a user id that may not exist on the target), so
    # it's dropped on export like a non-portable column rather than dangling a FK.
    Spec("theme_presets", ThemePreset, "site_settings", keep_id=True,
         natural_key=_nk_theme, secret_columns=("created_by",),
         validate_row=_validate_theme_row),
    Spec("users", User, "users", id_map="user", natural_key=_nk_user),
    Spec("roles", Role, "roles", id_map="role", natural_key=_nk_role),
    Spec("competitions", Competition, "competitions", id_map="competition",
         natural_key=_nk_competition, regenerate=("invite_code",)),
    # Competition-owned live data (skipped wholesale when the competition exists).
    Spec("categories", Category, "competitions", id_map="category",
         remaps=(_COMP,), owned_by_competition=True),
    # Custom registration-field DEFINITIONS ride the backup as competition config
    # (#350), validated on import (#324). The per-subject VALUES do NOT: their
    # ``subject_id`` is a user/team id that doesn't survive the import remap (the
    # same reason bracket memberships are excluded), and the operator's answer
    # export is the CSV, not the portable backup.
    Spec("registration_fields", RegistrationField, "competitions",
         remaps=(_COMP,), owned_by_competition=True,
         validate_row=_validate_registration_field_row),
    Spec("challenges", Challenge, "competitions", id_map="challenge",
         remaps=(_COMP, ("category_id", "category", False)), owned_by_competition=True),
    # Deployment spec (#266/#320, ADR-0036 §5): authoring content — one per
    # challenge — so it rides the backup with the rest of the competition.
    # image_ref/env/flag_template are non-secret authoring fields (no rendered
    # flag, no credential — those live in InstanceSettings, which is never
    # exported), so nothing is dropped. Instances (runtime state) are never
    # exported. validate_row repeats the authoring invariant the route enforces.
    Spec("challenge_deployments", ChallengeDeployment, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True)), owned_by_competition=True,
         validate_row=_validate_deployment_row),
    # Programming problem (#447): limits/compare/languages plus ONE test-data zip
    # carried in the object side-car like an attachment — rebuilt, not stored
    # as sent (GHSA-4wrj).
    Spec("judge_problems", JudgeProblem, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True)), owned_by_competition=True,
         object_key_for=_judge_object_key, validate_row=_validate_judge_problem_row,
         rebuild_object=_rebuild_judge_testdata),
    Spec("hints", Hint, "competitions", id_map="hint",
         remaps=(_COMP, ("challenge_id", "challenge", True)), owned_by_competition=True),
    Spec("attachments", Attachment, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True)), owned_by_competition=True,
         object_key_for=_challenge_object_key, validate_row=_validate_attachment_row),
    Spec("teams", Team, "competitions", id_map="team",
         remaps=(_COMP,), owned_by_competition=True, regenerate=("invite_code",)),
    Spec("team_memberships", TeamMembership, "competitions",
         remaps=(_COMP, ("team_id", "team", True), ("user_id", "user", True)),
         owned_by_competition=True),
    Spec("submissions", Submission, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True), ("user_id", "user", True),
                 ("team_id", "team", False)), owned_by_competition=True),
    Spec("score_adjustments", ScoreAdjustment, "competitions",
         remaps=(_COMP, ("user_id", "user", False), ("team_id", "team", False),
                 ("rule_id", "automation_rule", False)), owned_by_competition=True),
    Spec("surveys", Survey, "competitions", id_map="survey",
         remaps=(_COMP,), owned_by_competition=True),
    Spec("survey_questions", SurveyQuestion, "competitions", id_map="survey_question",
         remaps=(_COMP, ("survey_id", "survey", True)), owned_by_competition=True),
    Spec("survey_responses", SurveyResponse, "competitions", id_map="survey_response",
         remaps=(_COMP, ("survey_id", "survey", True), ("user_id", "user", True)),
         owned_by_competition=True),
    Spec("survey_answers", SurveyAnswer, "competitions",
         remaps=(_COMP, ("response_id", "survey_response", True),
                 ("question_id", "survey_question", True)), owned_by_competition=True),
    # Before tickets: a ticket message sent as a clarification (#450) points at
    # its announcement.
    Spec("announcements", Announcement, "competitions", id_map="announcement",
         remaps=(_COMP, ("created_by", "user", False), ("challenge_id", "challenge", True)),
         owned_by_competition=True),
    Spec("tickets", Ticket, "competitions", id_map="ticket",
         remaps=(_COMP, ("challenge_id", "challenge", False), ("opener_user_id", "user", True),
                 ("team_id", "team", False), ("assignee_user_id", "user", False)),
         owned_by_competition=True),
    Spec("ticket_messages", TicketMessage, "competitions", id_map="ticket_message",
         remaps=(_COMP, ("ticket_id", "ticket", True), ("author_user_id", "user", True),
                 ("announcement_id", "announcement", False)),
         owned_by_competition=True),
    Spec("ticket_attachments", TicketAttachment, "competitions",
         remaps=(_COMP, ("ticket_id", "ticket", True),
                 ("message_id", "ticket_message", True),
                 ("uploader_user_id", "user", True)),
         owned_by_competition=True, object_key_for=_ticket_object_key,
         validate_row=_validate_ticket_attachment_row),
    Spec("hint_reveals", HintReveal, "competitions",
         remaps=(_COMP, ("hint_id", "hint", True), ("challenge_id", "challenge", True),
                 ("user_id", "user", True), ("team_id", "team", False)),
         owned_by_competition=True),
    Spec("mc_guess_resets", MCGuessReset, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True), ("user_id", "user", False),
                 ("team_id", "team", False), ("reset_by", "user", False)),
         owned_by_competition=True),
    Spec("challenge_ratings", ChallengeRating, "competitions",
         remaps=(_COMP, ("challenge_id", "challenge", True), ("user_id", "user", True)),
         owned_by_competition=True),
    Spec("achievements", Achievement, "competitions",
         remaps=(_COMP, ("user_id", "user", False), ("team_id", "team", False),
                 ("rule_id", "automation_rule", False),
                 ("awarded_by_user_id", "user", False)), owned_by_competition=True),
    Spec("competition_modules", CompetitionModule, "competitions",
         remaps=(_COMP,), owned_by_competition=True),
    # Cross-cutting collections — additive per row (own natural key), imported
    # after competitions so their competition refs resolve.
    Spec("role_assignments", RoleAssignment, "roles",
         remaps=(("user_id", "user", True), ("role_id", "role", True),
                 ("competition_id", "competition", True)), natural_key=_nk_assignment),
    Spec("automation_rules", AutomationRule, "automations", id_map="automation_rule",
         remaps=(("competition_id", "competition", True), ("owner_user_id", "user", True)),
         natural_key=_nk_automation,
         validate_row=_validate_automation_rule_row),
    Spec("audit_log", AuditLogEntry, "audit_log", natural_key=_nk_audit, keep_id=True),
)


async def _actor_global(db: AsyncSession, actor: User | None) -> set[str] | None:
    """The actor's global permission set, or None for an internal caller."""
    if actor is None:
        return None
    return set((await effective_permissions(db, actor.id)).get("global", ()))


def _withheld(spec: Spec, actor_global: set[str] | None) -> bool:
    """Whether the actor lacks the extra grant ``spec.permission`` names."""
    return (
        actor_global is not None
        and spec.permission is not None
        and spec.permission not in actor_global
    )


# --- export ------------------------------------------------------------------

async def export_data(
    db: AsyncSession,
    storage: ObjectStorage,
    sections: list[str],
    actor: User | None = None,
) -> dict:
    picked = [s for s in SECTIONS if s in sections]
    actor_global = await _actor_global(db, actor)
    data: dict[str, list[dict]] = {}
    for spec in SPECS:
        if spec.section not in picked or _withheld(spec, actor_global):
            continue
        stmt = select(spec.model)
        # Undefer deferred columns (e.g. the site-settings logo blob) so
        # serialising them here doesn't trigger a forbidden async lazy-load —
        # but NOT the secret ones: they're dropped from the export anyway
        # (ADR-0020), and undeferring smtp_password would decrypt it for nothing
        # and 500 the export on a key mismatch. serialize_row(skip=...) omits
        # them before the getattr, so the deferred-and-not-undeferred secret is
        # never touched.
        deferred = [
            a.key
            for a in sa_inspect(spec.model).column_attrs
            if a.deferred and a.key not in spec.secret_columns
        ]
        if deferred:
            stmt = stmt.options(*[undefer(getattr(spec.model, k)) for k in deferred])
        rows = (await db.scalars(stmt)).all()
        serialised: list[dict] = []
        for r in rows:
            d = serialize_row(r, skip=spec.secret_columns)
            if spec.object_key_for is not None:
                try:
                    d["_object_data"] = base64.b64encode(storage.get(r.object_key)).decode("ascii")
                except Exception:  # noqa: BLE001 — a missing object shouldn't abort the export
                    d["_object_data"] = None
            serialised.append(d)
        data[spec.table] = serialised
    return {
        "flagpost_export": True,
        "schema_version": SCHEMA_VERSION,
        "exported_at": utcnow().isoformat(),
        "sections": picked,
        "data": data,
    }


# --- import ------------------------------------------------------------------

@dataclass
class _State:
    maps: dict[str, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))
    skipped_competitions: set[str] = field(default_factory=set)
    unpack_left: int = field(default_factory=lambda: MAX_IMPORT_UNPACKED)


class ImportError_(ValueError):
    """Raised for a malformed or unsupported export document."""


class ImportForbidden(Exception):
    """Raised when an import would grant permissions the actor doesn't hold.

    Distinct from :class:`ImportError_` (a bad document, 400) — this is an
    authorization refusal (403): the import path must honour the same grant
    containment ``routers.roles._assert_may_grant`` enforces interactively, or
    ``manage_roles`` becomes a delegation of everything.
    """


async def _assert_import_within_grant(
    db: AsyncSession, spec: "Spec", obj, actor_global: set[str]
) -> None:
    """Refuse to import a role or role-assignment carrying permissions beyond the
    actor's own global set, or an automation rule on a trigger they may not
    observe (backup escalation guard). Mirrors the bound in
    ``routers.roles._assert_may_grant``; a full Administrator holds the whole
    catalog, so their restores are unaffected."""
    if spec.table == "roles":
        excess = set(obj.permissions or ()) - actor_global
        target = f"role {obj.name!r}"
    elif spec.table == "role_assignments":
        role = await db.get(Role, obj.role_id)
        excess = set(role.permissions or ()) - actor_global if role is not None else set()
        target = "a role assignment"
    elif spec.table == "automation_rules":
        # The interactive route only lets you automate on an event you may
        # observe (_authorize_trigger). An import is a site-wide write, so the
        # importer must hold the trigger's governing permission site-wide
        # (GHSA-x8v4-p7x5-v6c8). A personal row is also bound by its *owner's*
        # grants, which the engine re-checks every time the rule would run
        # (automation_engine._owner_may_observe).
        from utils.automation_catalog import required_permission

        permission = required_permission(obj.trigger_type)
        excess = {permission} - actor_global
        target = f"automation rule {obj.name!r} (trigger {obj.trigger_type!r})"
    else:
        return
    if excess:
        raise ImportForbidden(
            f"This import would grant permissions you don't hold yourself via "
            f"{target}: " + ", ".join(sorted(excess))
        )


# The mail transport: where every password-reset link is delivered (and, via
# the From address, where bounces return). Changing it needs an Administrator on
# the operational settings route (GHSA-mwhq-j3jg-p339); the site_settings
# section must not be a way around that.
_MAIL_TRANSPORT_COLUMNS = (
    "smtp_host", "smtp_port", "smtp_username", "smtp_from", "smtp_starttls",
    "smtp_password",
)


async def _assert_import_keeps_mail_transport(
    db: AsyncSession, row: dict, actor: User
) -> None:
    """Refuse a site_settings row that would change the mail transport, unless
    the actor is an Administrator. An export never carries ``smtp_password``
    (a secret column), so one present in the row is always a change."""
    incoming = load_row(
        SiteSettings, {k: row[k] for k in _MAIL_TRANSPORT_COLUMNS if k in row}
    )
    if not incoming:
        return
    current = await db.get(SiteSettings, SITE_SETTINGS_ID)
    changed = "smtp_password" in incoming or any(
        value != (getattr(current, key) if current is not None else None)
        for key, value in incoming.items()
    )
    if changed and not await holds_every_permission(db, actor):
        raise ImportForbidden(
            "This import would change mail delivery, which needs an "
            "Administrator: password-reset links travel through it"
        )


async def import_data(
    db: AsyncSession,
    storage: ObjectStorage,
    payload: dict,
    sections: list[str],
    actor: User | None = None,
) -> dict[str, dict[str, int]]:
    # Objects are put as their rows are built, before the one commit. A rejected
    # import (a later row failing validation, the grant check, the commit itself)
    # rolls every row back, so the objects it already stored would be orphans
    # nothing references — remove them (GHSA-4wrj). Best-effort: a delete that
    # fails leaves an orphan, never a dangling row.
    stored: list[str] = []
    try:
        return await _import_rows(db, storage, payload, sections, actor, stored)
    except BaseException:
        for key in stored:
            try:
                storage.delete(key)
            except Exception:  # noqa: BLE001 — the original error is the one to surface
                pass
        raise


async def _import_rows(
    db: AsyncSession,
    storage: ObjectStorage,
    payload: dict,
    sections: list[str],
    actor: User | None,
    stored: list[str],
) -> dict[str, dict[str, int]]:
    if not isinstance(payload, dict) or not payload.get("flagpost_export"):
        raise ImportError_("Not a Flagpost export file")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ImportError_(
            f"Unsupported export version {payload.get('schema_version')!r} "
            f"(this install reads v{SCHEMA_VERSION})"
        )
    data = payload.get("data") or {}
    picked = [s for s in SECTIONS if s in sections]
    state = _State()
    result: dict[str, dict[str, int]] = {}

    # The actor's global set bounds three things. Grant containment: no imported
    # role or assignment may carry permissions beyond it — the same bound the
    # interactive role editor enforces, which the generic import would otherwise
    # bypass. Trigger authorization: an imported automation rule's trigger must
    # be one the actor may observe. And Spec.permission: a table needing a grant
    # the actor lacks is skipped. None applies when no actor is supplied
    # (internal callers).
    actor_global = await _actor_global(db, actor)

    for spec in SPECS:
        if spec.section not in picked:
            continue
        created = skipped = 0
        withheld = _withheld(spec, actor_global)
        for raw in data.get(spec.table, []):
            if withheld:
                skipped += 1
                continue
            row = dict(raw)
            object_data = row.pop("_object_data", None)

            if spec.singleton:
                # The singleton path skips the generic validate_row call below, so
                # apply it here — otherwise an imported site_settings row bypasses
                # content validation entirely (#360 review).
                if spec.validate_row is not None:
                    spec.validate_row(row)
                if spec.model is SiteSettings and actor is not None:
                    await _assert_import_keeps_mail_transport(db, row, actor)
                await _upsert_singleton(db, spec.model, row, spec.immutable_columns)
                created += 1
                continue

            # A row belonging to an already-present competition is skipped whole.
            if spec.owned_by_competition and row.get("competition_id") in state.skipped_competitions:
                skipped += 1
                continue

            if not _remap(row, spec, state):
                skipped += 1
                continue

            old_id = row.get("id")
            if spec.natural_key is not None:
                existing = await spec.natural_key(db, row)
                if existing is not None:
                    if spec.id_map and old_id is not None:
                        state.maps[spec.id_map][old_id] = existing
                    if spec.table == "competitions" and old_id is not None:
                        state.skipped_competitions.add(old_id)
                    skipped += 1
                    continue

            new_id = old_id if spec.keep_id else str(uuid4())
            if "id" in row:
                row["id"] = new_id
            for col in spec.regenerate:
                row[col] = generate_invite_code()
            if spec.object_key_for is not None and object_data:
                row["object_key"] = spec.object_key_for(row)

            # Re-apply any content invariant the CRUD routes guard (load_row does
            # not) before the row lands — see Spec.validate_row (#323 review).
            if spec.validate_row is not None and spec.validate_row(row) is False:
                skipped += 1
                continue
            blob: bytes | None = None
            if spec.object_key_for is not None and object_data and row.get("object_key"):
                try:
                    blob = base64.b64decode(object_data)
                except (TypeError, ValueError) as exc:
                    raise ImportError_(f"{spec.table}: an attached object isn't base64") from exc
                if spec.rebuild_object is not None:
                    blob, unpacked = await asyncio.to_thread(
                        spec.rebuild_object, row, blob, state.unpack_left
                    )
                    state.unpack_left -= unpacked

            obj = spec.model(**load_row(spec.model, row))
            if actor_global is not None:
                await _assert_import_within_grant(db, spec, obj, actor_global)
            db.add(obj)
            await db.flush()

            if blob is not None:
                stored.append(row["object_key"])  # before the put: it may fail part-way
                storage.put(row["object_key"], blob, obj.content_type)
            if spec.id_map and old_id is not None:
                state.maps[spec.id_map][old_id] = new_id
            created += 1

        result[spec.table] = {"created": created, "skipped": skipped}

    await db.commit()
    return result


def _remap(row: dict, spec: Spec, state: _State) -> bool:
    """Rewrite FK columns through the id maps. Returns False if the row must be
    dropped (a required reference didn't resolve)."""
    for col, map_name, required in spec.remaps:
        old = row.get(col)
        if old is None:
            continue
        new = state.maps[map_name].get(old)
        if new is None:
            if required:
                return False
            row[col] = None
        else:
            row[col] = new
    return True


async def _upsert_singleton(
    db: AsyncSession, model, row: dict, immutable_columns: tuple[str, ...] = ()
) -> None:
    obj = await db.get(model, SITE_SETTINGS_ID)
    if obj is None:
        obj = model(id=SITE_SETTINGS_ID)
        db.add(obj)
    for key, val in load_row(model, row).items():
        # `id` is fixed; immutable columns are one-way security flags the import
        # must never touch (F2 — e.g. setup_completed_at).
        if key == "id" or key in immutable_columns:
            continue
        setattr(obj, key, val)
