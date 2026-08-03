"""one identity_providers table for all provider kinds (ADR-0022 Phase 0)

Generalizes ADR-0021's OIDC-only provider model so SAML (#100) and LDAP (#101)
can share one table, one identity-link FK and one admin surface. Live OIDC rows
are carried across with ``kind="oidc"`` / ``posture="open"``, their
issuer/client_id/scopes folded into the ``config`` JSON and the client secret
moved into the generic ``secret`` column.

Portability notes (this file runs on real Postgres *and* dev/test SQLite):

- **No in-place FK repoint.** SQLite can't ALTER a foreign key, so the child
  table is rebuilt. And it can't be rebuilt *alongside* the old table: the
  alembic env applies the naming convention to migrations too, so the old
  table's constraints already hold the convention names (``pk_…``, ``uq_…``),
  and on Postgres those are schema-global relation names — a sibling table
  can't reuse them. Data therefore moves through an **unconstrained holding
  table**: copy → drop old → create final (with the exact convention names a
  fresh ``Base.metadata`` install gets) → copy back. Deterministic on both
  engines, no reflection, no rename step.
- **The secret is moved as a raw column value, never through the ORM.** The
  stored string is Fernet ciphertext (ADR-0020); reading it through
  ``EncryptedString`` would decrypt and needlessly couple this migration to
  the encryption key. A straight copy round-trips because the type keys off
  the ``gAAAAA`` prefix at read time.
- ``oidc_login_states`` rows are in-flight logins with a 10-minute TTL, so the
  table is dropped and recreated (as ``auth_login_states``) rather than copied
  — losing a pending login costs one retry, not data.

Revision ID: f3a9c8d1e5b2
Revises: e7c1f9a4b206
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a9c8d1e5b2"
down_revision = "e7c1f9a4b206"
branch_labels = None
depends_on = None


def _oidc_providers_table() -> sa.TableClause:
    """Typed handle on the legacy table so SELECTs come back with real
    datetimes/bools on both engines (a bare ``sa.text`` SELECT on SQLite would
    return strings that the typed INSERT then rejects)."""
    return sa.table(
        "oidc_providers",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("issuer", sa.String),
        sa.column("client_id", sa.String),
        sa.column("client_secret", sa.String),
        sa.column("scopes", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )


def _identity_providers_table() -> sa.TableClause:
    return sa.table(
        "identity_providers",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("posture", sa.String),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("email_is_authoritative", sa.Boolean),
        sa.column("secret", sa.String),
        sa.column("config", sa.JSON),
        sa.column("enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 0. ADR-0022 §6: every row that will be copied must round-trip the config
    #    rules, so a drifted legacy row (a direct DB edit the API never saw)
    #    fails the upgrade loudly here — where the operator is watching —
    #    instead of shipping a provider whose login 404s for every user. Runs
    #    **before any DDL**: SQLite's DDL is non-transactional, so raising
    #    mid-migration would strand a half-built schema and break the re-run
    #    after the operator fixes the row. The bounds are a frozen copy of
    #    OidcConfig's at the time this migration was written, deliberately not
    #    an import: the live model may grow stricter later, and this migration
    #    must keep meaning what it meant when it shipped.
    rows = conn.execute(sa.select(_oidc_providers_table())).mappings().all()
    for row in rows:
        issuer = row["issuer"] or ""
        client_id = row["client_id"] or ""
        # No coalesce for scopes: step 2 stores the raw value, and a NULL (only
        # possible on a tampered schema — the legacy column is NOT NULL) would
        # pass a coalesced length check here yet fail the OidcConfig re-parse
        # at login, which is exactly the quiet outcome this step exists to stop.
        scopes = row["scopes"]
        if (
            not 0 < len(issuer) <= 500
            or not 0 < len(client_id) <= 500
            or scopes is None
            or len(scopes) > 500
        ):
            raise RuntimeError(
                f"oidc_providers row {row['slug']!r} has invalid config "
                "(issuer and client_id must be 1-500 chars, scopes at most "
                "500); fix the row, then re-run the upgrade"
            )

    # 1. The unified table.
    identity_providers = op.create_table(
        "identity_providers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("posture", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("email_is_authoritative", sa.Boolean(), nullable=False),
        # Fernet ciphertext (EncryptedString) — plain text at the DB layer.
        sa.Column("secret", sa.String(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_identity_providers"),
    )
    op.create_index(
        "ix_identity_providers_slug", "identity_providers", ["slug"], unique=True
    )

    # 2. Backfill from oidc_providers (validated in step 0). Every existing
    #    provider is an open OIDC one by definition (ADR-0022 §2); the
    #    ciphertext moves verbatim.
    if rows:
        op.bulk_insert(
            identity_providers,
            [
                {
                    "id": row["id"],
                    "kind": "oidc",
                    "posture": "open",
                    "name": row["name"],
                    "slug": row["slug"],
                    "email_is_authoritative": False,
                    "secret": row["client_secret"],
                    "config": {
                        "issuer": row["issuer"],
                        "client_id": row["client_id"],
                        "scopes": row["scopes"],
                    },
                    "enabled": row["enabled"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        )

    # 3. Rebuild user_external_identities against the new parent, via an
    #    unconstrained holding table (see module docstring for why the final
    #    table can't be created while the old one still holds the convention
    #    constraint names). Same storage format both sides — plain SQL copies,
    #    no type munging.
    conn.execute(
        sa.text(
            "CREATE TABLE _uei_copy AS "
            "SELECT id, user_id, provider_id, subject, email, created_at "
            "FROM user_external_identities"
        )
    )
    op.drop_table("user_external_identities")
    op.create_table(
        "user_external_identities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_external_identities_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["identity_providers.id"],
            ondelete="CASCADE",
            name="fk_user_external_identities_provider_id_identity_providers",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_external_identities"),
        sa.UniqueConstraint("provider_id", "subject", name="uq_external_identity"),
    )
    conn.execute(
        sa.text(
            "INSERT INTO user_external_identities "
            "(id, user_id, provider_id, subject, email, created_at) "
            "SELECT id, user_id, provider_id, subject, email, created_at "
            "FROM _uei_copy"
        )
    )
    conn.execute(sa.text("DROP TABLE _uei_copy"))
    op.create_index(
        "ix_user_external_identities_user_id", "user_external_identities", ["user_id"]
    )
    op.create_index(
        "ix_user_external_identities_provider_id",
        "user_external_identities",
        ["provider_id"],
    )

    # 4. In-flight login state: ephemeral, so replaced rather than copied.
    op.drop_table("oidc_login_states")
    op.create_table(
        "auth_login_states",
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        # Nullable so a SAML request (no PKCE, no nonce) can share the table.
        sa.Column("code_verifier", sa.String(), nullable=True),
        sa.Column("nonce", sa.String(), nullable=True),
        sa.Column("return_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["identity_providers.id"],
            ondelete="CASCADE",
            name="fk_auth_login_states_provider_id_identity_providers",
        ),
        sa.PrimaryKeyConstraint("state", name="pk_auth_login_states"),
    )

    # 5. Nothing references the legacy table any more.
    op.drop_index("ix_oidc_providers_slug", table_name="oidc_providers")
    op.drop_table("oidc_providers")


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Recreate the legacy table and unfold the oidc rows back into it.
    oidc_providers = op.create_table(
        "oidc_providers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_secret", sa.String(), nullable=True),
        sa.Column("scopes", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oidc_providers_slug", "oidc_providers", ["slug"], unique=True)
    idp = _identity_providers_table()
    rows = (
        conn.execute(sa.select(idp).where(idp.c.kind == "oidc")).mappings().all()
    )
    if rows:
        op.bulk_insert(
            oidc_providers,
            [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "issuer": (row["config"] or {}).get("issuer", ""),
                    "client_id": (row["config"] or {}).get("client_id", ""),
                    "client_secret": row["secret"],
                    "scopes": (row["config"] or {}).get(
                        "scopes", "openid email profile"
                    ),
                    "enabled": row["enabled"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        )

    # 2. Rebuild the identity links against the legacy parent — the same
    #    holding-table dance as the upgrade, filtered to links whose provider
    #    survives the downgrade (non-oidc kinds don't exist pre-ADR-0022, so
    #    their links can't either). Constraint names land back on the exact
    #    convention names the original migration produced.
    conn.execute(
        sa.text(
            "CREATE TABLE _uei_copy AS "
            "SELECT id, user_id, provider_id, subject, email, created_at "
            "FROM user_external_identities "
            "WHERE provider_id IN (SELECT id FROM oidc_providers)"
        )
    )
    op.drop_table("user_external_identities")
    op.create_table(
        "user_external_identities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_external_identities_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["oidc_providers.id"],
            ondelete="CASCADE",
            name="fk_user_external_identities_provider_id_oidc_providers",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_external_identities"),
        sa.UniqueConstraint("provider_id", "subject", name="uq_external_identity"),
    )
    conn.execute(
        sa.text(
            "INSERT INTO user_external_identities "
            "(id, user_id, provider_id, subject, email, created_at) "
            "SELECT id, user_id, provider_id, subject, email, created_at "
            "FROM _uei_copy"
        )
    )
    conn.execute(sa.text("DROP TABLE _uei_copy"))
    op.create_index(
        "ix_user_external_identities_user_id", "user_external_identities", ["user_id"]
    )
    op.create_index(
        "ix_user_external_identities_provider_id",
        "user_external_identities",
        ["provider_id"],
    )

    # 3. In-flight state back to the OIDC-only shape (ephemeral — not copied).
    op.drop_table("auth_login_states")
    op.create_table(
        "oidc_login_states",
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("code_verifier", sa.String(), nullable=False),
        sa.Column("nonce", sa.String(), nullable=False),
        sa.Column("return_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["oidc_providers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("state"),
    )

    # 4. Drop the unified table last (children were repointed above).
    op.drop_index("ix_identity_providers_slug", table_name="identity_providers")
    op.drop_table("identity_providers")
