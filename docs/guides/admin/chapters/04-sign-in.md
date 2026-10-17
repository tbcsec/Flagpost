Local username/password sign-in works out of the box. **Site settings →
Auth** (its own grant) adds external identity providers alongside it — each
redirect-based one appears as a **Sign in with …** button.

## What you can connect

| Kind | Typical use |
|---|---|
| **Quick set up** presets | Google, Microsoft, Microsoft (multi-tenant), GitHub, Discord — paste client credentials and go |
| **OpenID Connect** | any standards-compliant IdP (Okta, Keycloak, Auth0, Entra…) |
| **OAuth 2.0 (no OpenID Connect)** | providers without an ID token — identity comes from a userinfo call and a claim map (what GitHub and Discord use) |
| **SAML 2.0** | campus and enterprise IdPs that predate OIDC |
| **LDAP / Active Directory** | direct directory sign-in — no button; the normal login form checks the directory when local verification fails |

New providers **start disabled**: configure, register the **Redirect URI**
(or the **SP metadata** URL for SAML) at the IdP, test, then **Enable**. The
protocol and slug are fixed after creation. Prefer **Disable** to **Delete**
— a user who only ever signed in through a provider has no password to fall
back on.

!!! note "Multi-tenant Microsoft trusts every tenant"
    The multi-tenant preset admits any Microsoft work or school account.
    Pair it with the email domain allowlist (Site settings → Email) to keep
    the roster to your organisation.

## Sign-in policy

An OpenID Connect or OAuth 2.0 provider is **Open** or **Closed**; SAML and
LDAP are always closed.

- **Open — public provider, registration rules apply.** A new account must
  pass the same checks as the sign-up form: registration open, and the
  email domain allowlist. Right for Google or GitHub on a public event.
- **Closed — being in this directory is the admission.** Anyone who can
  sign in at that IdP gets in, *even while public registration is closed*.
  Right for your own corporate or campus directory.

## One account model

A first sign-in creates an account with **no role** — it becomes a
Participant per competition on joining, like self-registration — and later
sign-ins link by the provider's stable subject, so a changed email at the
IdP doesn't fork the account. A first sign-in attaches to an *existing*
local account with the same email only when the address is trusted
(asserted verified by an open provider, or **Trust this provider's email
addresses** ticked for a closed one). If the local account's email was never
verified, the sign-in is refused rather than linked; if the provider's
address isn't trusted, no linking is attempted and a separate account is
created with no email on it.

## Practical notes

- **Local login stays available** as the break-glass path. A provider-
  created user has no usable local password until one is set — through
  **Forgot password?** (needs an email and SMTP) or by you in Admin → Users
  → Edit — and they'll need one to create API tokens. Keep at least one
  local administrator account you control.
- Provider secrets are stored encrypted and never shown back; they're left
  out of backups.
- A sign-in must finish in the browser that started it; a callback opened
  elsewhere gets *That sign-in link has expired or was already used*.
- **SAML needs HTTPS.** The IdP hands the sign-in back with a form post from
  its own site, and the cookie tying it to the browser that started it only
  travels with that post over HTTPS. Over plain HTTP, SAML works only with an
  IdP on the same site.
- Redirect-based providers need the IdP to know your site's public URL — if
  a provider rejects the callback, the URL registered at the IdP and the one
  the site runs behind disagree. The deployment side lives at
  docs.flagpost.io.
