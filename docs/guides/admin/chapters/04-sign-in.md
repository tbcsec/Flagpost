Local username/password sign-in works out of the box. **Site settings →
Auth** adds external identity providers alongside it — each appears as a
button on the sign-in page.

## What you can connect

| Kind | Typical use |
|---|---|
| **Google / Microsoft** | one-click presets — paste client credentials and go |
| **GitHub / Discord** | community sign-in presets |
| **OpenID Connect** | any standards-compliant IdP (Okta, Keycloak, Auth0, Entra…) |
| **SAML** | enterprise IdPs that predate OIDC |
| **LDAP / Active Directory** | direct directory sign-in — no redirect; the login form itself checks the directory when local verification fails |

All of them feed one account model: on first sign-in the account is
**provisioned automatically as a Participant** (never anything higher), and
subsequent sign-ins link by the provider's stable subject — so a changed
email at the IdP doesn't fork the account.

## Posture: open or closed

Each provider is configured **open** (anyone at the IdP may sign in — right
for public events using Google/GitHub) or **closed** (only users who
already exist here — right for an internal event where the roster is
provisioned up front).

## Practical notes

- **Local login stays available** as the break-glass path — a provisioned
  SSO user has no usable local password until they set one, and
  administrators should keep at least one local account they control.
- Provider secrets are stored encrypted; what you paste is never shown
  back.
- Redirect-based providers need the IdP to know your site's public URL —
  if a provider rejects the callback, the URL registered at the IdP and the
  one the site runs behind disagree. The deployment side of that lives at
  docs.flagpost.io.
