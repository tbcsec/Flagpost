// Built-in SSO provider presets (Google, Microsoft Entra) — the pure logic
// behind the admin panel's quick-setup cards. No React here, mirroring the
// lib/live.ts split, so param validation, issuer-template substitution and the
// form prefill are unit-testable without rendering the panel.
//
// A preset is form-prefill data, not a write path: creation still flows through
// the ordinary POST /api/admin/auth-providers, and the admin can edit anything
// (including everything prefilled here) before saving.

import type { PresetParam, ProviderPreset } from "@/lib/types";

/** Validate one preset parameter against its catalog pattern. Returns a
 *  human-readable error, or null when the value is acceptable. Defensive: the
 *  pattern comes from our own backend catalog, but a malformed regex must
 *  degrade to "no client-side check" rather than crash the panel — the backend
 *  still validates the resulting issuer on save. */
export function validatePresetParam(
  param: PresetParam,
  value: string,
): string | null {
  const trimmed = value.trim();
  if (!trimmed) return `Enter the ${param.label}.`;
  let re: RegExp;
  try {
    re = new RegExp(param.pattern);
  } catch {
    return null;
  }
  if (!re.test(trimmed)) {
    return `That doesn't look like a valid ${param.label} — expected something like ${param.placeholder}.`;
  }
  return null;
}

/** Resolve the preset's issuer. A fixed issuer passes straight through; a
 *  templated one has each `{key}` placeholder substituted from `values`.
 *  Returns null when any required param is missing or invalid — callers gate
 *  opening the prefilled form on a non-null result. */
export function resolvePresetIssuer(
  preset: ProviderPreset,
  values: Record<string, string>,
): string | null {
  if (!preset.issuer_template) return preset.issuer;
  let issuer = preset.issuer_template;
  for (const param of preset.params) {
    const raw = (values[param.key] ?? "").trim();
    if (validatePresetParam(param, raw) !== null) return null;
    // Canonicalize before substitution: an uppercase tenant GUID validates
    // fine but would then mismatch Entra's lowercase issuer at sign-in.
    const value = param.normalize === "lowercase" ? raw.toLowerCase() : raw;
    issuer = issuer.split(`{${param.key}}`).join(value);
  }
  return issuer;
}

/** The create-form fields a preset seeds. Kind-specific keys are optional
 *  because an OIDC preset fills an issuer while an `oauth2` one fills an
 *  endpoint set and claim map (#193); the panel spreads this over its EMPTY
 *  FormState, so absent keys simply keep their defaults. */
export interface PresetFormPrefill {
  kind: "oidc" | "oauth2" | "saml" | "ldap";
  name: string;
  slug: string;
  posture: "open" | "closed";
  scopes: string;
  // OIDC
  issuer?: string;
  issuer_template?: string;
  // OAuth2
  authorize_url?: string;
  token_url?: string;
  userinfo_url?: string;
  emails_url?: string;
  subject_field?: string;
  email_field?: string;
  name_field?: string;
  email_verified_field?: string;
  use_pkce?: boolean;
}

/** What a preset seeds into the panel's existing create form — the same
 *  FormState fields the admin would otherwise type by hand. `kind` is narrowed
 *  to the form's protocol union (an unknown kind falls back to "oidc" rather
 *  than widening the form's type). Returns null when the preset can't be turned
 *  into a usable form yet: an OIDC issuer still missing its params, or a
 *  malformed catalog entry — either way the caller keeps the card inert rather
 *  than opening a form that would fail on save. */
export function presetToFormPrefill(
  preset: ProviderPreset,
  values: Record<string, string> = {},
): PresetFormPrefill | null {
  const kind: PresetFormPrefill["kind"] =
    preset.kind === "saml" || preset.kind === "ldap" || preset.kind === "oauth2"
      ? preset.kind
      : "oidc";
  const base = {
    kind,
    name: preset.name,
    slug: preset.default_slug,
    posture: (preset.posture === "closed" ? "closed" : "open") as
      | "open"
      | "closed",
  };

  if (preset.kind === "oauth2") {
    // No issuer to resolve — a plain-OAuth2 provider is described entirely by
    // its endpoints and claim map (ADR-0033). Nullable claim fields become ""
    // so they round-trip through the form's string inputs.
    const config = preset.oauth2;
    if (!config) return null;
    return {
      ...base,
      scopes: config.scopes || preset.scopes,
      authorize_url: config.authorize_url,
      token_url: config.token_url,
      userinfo_url: config.userinfo_url,
      emails_url: config.emails_url ?? "",
      subject_field: config.subject_field,
      email_field: config.email_field ?? "",
      name_field: config.name_field ?? "",
      email_verified_field: config.email_verified_field ?? "",
      use_pkce: config.use_pkce,
    };
  }

  const issuer = resolvePresetIssuer(preset, values);
  if (issuer === null) return null;
  return {
    ...base,
    issuer,
    scopes: preset.scopes,
    // Multi-tenant Entra (ADR-0032): the per-tenant iss-validation template. Blank
    // for every single-tenant preset, so it round-trips as an empty config field.
    issuer_template: preset.config_issuer_template ?? "",
  };
}

/** Label for the card's external setup link. The console names are a frontend
 *  nicety keyed off the preset id; an unknown preset gets a generic label
 *  rather than nothing. */
const SETUP_LINK_LABELS: Record<string, string> = {
  google: "Open Google Cloud Console",
  microsoft: "Open Microsoft Entra",
  "microsoft-multi-tenant": "Open Microsoft Entra",
  github: "Open GitHub developer settings",
  discord: "Open the Discord developer portal",
};

export function setupLinkLabel(preset: ProviderPreset): string {
  return SETUP_LINK_LABELS[preset.id] ?? `Open the ${preset.name} setup page`;
}
