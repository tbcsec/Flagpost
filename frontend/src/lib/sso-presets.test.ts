import { describe, expect, it } from "vitest";

import {
  presetToFormPrefill,
  resolvePresetIssuer,
  setupLinkLabel,
  validatePresetParam,
} from "@/lib/sso-presets";
import type { PresetParam, ProviderPreset } from "@/lib/types";

// Fixtures mirror the backend catalog (GET /api/admin/auth-providers/presets):
// Google is a fixed-issuer preset with no params; Microsoft Entra is
// single-tenant, so its issuer is a template resolved from the tenant GUID.

const TENANT_PARAM: PresetParam = {
  key: "tenant_id",
  label: "Directory (tenant) ID",
  placeholder: "00000000-0000-0000-0000-000000000000",
  pattern:
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
  normalize: "lowercase",
  help: "The GUID from your app registration's overview page in Microsoft Entra.",
};

const MICROSOFT: ProviderPreset = {
  id: "microsoft",
  name: "Microsoft",
  kind: "oidc",
  issuer: null,
  issuer_template: "https://login.microsoftonline.com/{tenant_id}/v2.0",
  config_issuer_template: null,
  oauth2: null,
  params: [TENANT_PARAM],
  scopes: "openid profile email",
  default_slug: "microsoft",
  posture: "closed",
  setup_url: "https://entra.microsoft.com/",
  notes: "Register a single-tenant app in Microsoft Entra.",
};

const GOOGLE: ProviderPreset = {
  id: "google",
  name: "Google",
  kind: "oidc",
  issuer: "https://accounts.google.com",
  issuer_template: null,
  config_issuer_template: null,
  oauth2: null,
  params: [],
  scopes: "openid email profile",
  default_slug: "google",
  posture: "open",
  setup_url: "https://console.cloud.google.com/apis/credentials",
  notes: "Create an OAuth client in Google Cloud Console.",
};

// Multi-tenant Entra (ADR-0032): a fixed `common` authority plus the per-tenant
// iss-validation template carried in config_issuer_template — no params.
const MICROSOFT_MULTI_TENANT: ProviderPreset = {
  id: "microsoft-multi-tenant",
  name: "Microsoft (multi-tenant)",
  kind: "oidc",
  issuer: "https://login.microsoftonline.com/common/v2.0",
  issuer_template: null,
  config_issuer_template: "https://login.microsoftonline.com/{tenantid}/v2.0",
  oauth2: null,
  params: [],
  scopes: "openid profile email",
  default_slug: "microsoft",
  posture: "open",
  setup_url: "https://entra.microsoft.com/",
  notes: "Register a multi-tenant app in Microsoft Entra.",
};

// Plain OAuth2 (#193, ADR-0033): no issuer at all — the endpoint set and claim
// map arrive in `oauth2`. GitHub reads verified addresses from a second
// endpoint; Discord carries its own verified flag.
const GITHUB: ProviderPreset = {
  id: "github",
  name: "GitHub",
  kind: "oauth2",
  issuer: null,
  issuer_template: null,
  config_issuer_template: null,
  oauth2: {
    authorize_url: "https://github.com/login/oauth/authorize",
    token_url: "https://github.com/login/oauth/access_token",
    userinfo_url: "https://api.github.com/user",
    scopes: "read:user user:email",
    subject_field: "id",
    email_field: "email",
    name_field: "login",
    email_verified_field: null,
    emails_url: "https://api.github.com/user/emails",
    use_pkce: false,
  },
  params: [],
  scopes: "read:user user:email",
  default_slug: "github",
  posture: "open",
  setup_url: "https://github.com/settings/developers",
  notes: "Register an OAuth App in GitHub's developer settings.",
};

const GUID = "d1c9061b-5e24-4a86-9db3-6a45f6f5f0d3";

describe("validatePresetParam", () => {
  it("accepts a well-formed GUID, either case, ignoring padding", () => {
    expect(validatePresetParam(TENANT_PARAM, GUID)).toBeNull();
    expect(validatePresetParam(TENANT_PARAM, GUID.toUpperCase())).toBeNull();
    expect(validatePresetParam(TENANT_PARAM, `  ${GUID}  `)).toBeNull();
  });

  it("rejects a domain name — Entra's issuer must use the GUID form", () => {
    const error = validatePresetParam(TENANT_PARAM, "contoso.onmicrosoft.com");
    expect(error).toContain("Directory (tenant) ID");
  });

  it("rejects a truncated GUID", () => {
    expect(validatePresetParam(TENANT_PARAM, "d1c9061b-5e24")).not.toBeNull();
  });

  it("rejects an empty value", () => {
    expect(validatePresetParam(TENANT_PARAM, "")).toBe(
      "Enter the Directory (tenant) ID.",
    );
    expect(validatePresetParam(TENANT_PARAM, "   ")).not.toBeNull();
  });
});

describe("resolvePresetIssuer", () => {
  it("substitutes template placeholders from the supplied values", () => {
    expect(resolvePresetIssuer(MICROSOFT, { tenant_id: GUID })).toBe(
      `https://login.microsoftonline.com/${GUID}/v2.0`,
    );
  });

  it("trims the value before substituting", () => {
    expect(resolvePresetIssuer(MICROSOFT, { tenant_id: ` ${GUID} ` })).toBe(
      `https://login.microsoftonline.com/${GUID}/v2.0`,
    );
  });

  it("lowercases a GUID that passes the case-insensitive pattern", () => {
    // Entra's issuer is lowercase and the backend check is case-sensitive, so
    // an uppercase paste (validated as fine) must be canonicalized here or it
    // would fail at first sign-in.
    expect(resolvePresetIssuer(MICROSOFT, { tenant_id: GUID.toUpperCase() })).toBe(
      `https://login.microsoftonline.com/${GUID}/v2.0`,
    );
  });

  it("returns null when a param is missing or invalid", () => {
    expect(resolvePresetIssuer(MICROSOFT, {})).toBeNull();
    expect(
      resolvePresetIssuer(MICROSOFT, { tenant_id: "contoso.onmicrosoft.com" }),
    ).toBeNull();
  });

  it("passes a fixed issuer straight through", () => {
    expect(resolvePresetIssuer(GOOGLE, {})).toBe("https://accounts.google.com");
  });
});

describe("presetToFormPrefill", () => {
  it("produces the create-form seed for a fixed-issuer preset", () => {
    expect(presetToFormPrefill(GOOGLE)).toEqual({
      kind: "oidc",
      name: "Google",
      slug: "google",
      posture: "open",
      issuer: "https://accounts.google.com",
      scopes: "openid email profile",
      issuer_template: "",
    });
  });

  it("produces the seed with the resolved issuer for a templated preset", () => {
    expect(presetToFormPrefill(MICROSOFT, { tenant_id: GUID })).toEqual({
      kind: "oidc",
      name: "Microsoft",
      slug: "microsoft",
      posture: "closed",
      issuer: `https://login.microsoftonline.com/${GUID}/v2.0`,
      scopes: "openid profile email",
      issuer_template: "",
    });
  });

  it("carries the tenant validation template for a multi-tenant preset", () => {
    // ADR-0032: the fixed `common` authority becomes `issuer`, and the per-tenant
    // template rides through as `issuer_template` so the created provider validates
    // the token issuer against the signing-in tenant, not `common`.
    expect(presetToFormPrefill(MICROSOFT_MULTI_TENANT)).toEqual({
      kind: "oidc",
      name: "Microsoft (multi-tenant)",
      slug: "microsoft",
      posture: "open",
      issuer: "https://login.microsoftonline.com/common/v2.0",
      scopes: "openid profile email",
      issuer_template: "https://login.microsoftonline.com/{tenantid}/v2.0",
    });
  });

  it("returns null while the issuer is unresolvable", () => {
    expect(presetToFormPrefill(MICROSOFT, {})).toBeNull();
    expect(presetToFormPrefill(MICROSOFT, { tenant_id: "nope" })).toBeNull();
  });

  it("seeds the endpoint set and claim map for an oauth2 preset", () => {
    // No issuer to resolve, so this must not go down the OIDC path — before
    // #193 a null issuer meant "unresolvable" and the card would be dead.
    expect(presetToFormPrefill(GITHUB)).toEqual({
      kind: "oauth2",
      name: "GitHub",
      slug: "github",
      posture: "open",
      scopes: "read:user user:email",
      authorize_url: "https://github.com/login/oauth/authorize",
      token_url: "https://github.com/login/oauth/access_token",
      userinfo_url: "https://api.github.com/user",
      emails_url: "https://api.github.com/user/emails",
      subject_field: "id",
      email_field: "email",
      name_field: "login",
      // Nullable claim fields become "" so they round-trip through the form's
      // string inputs and submit back as null.
      email_verified_field: "",
      use_pkce: false,
    });
  });

  it("returns null for an oauth2 preset with no config block", () => {
    // A malformed catalog entry must leave the card inert rather than opening
    // a form that would fail on save.
    expect(presetToFormPrefill({ ...GITHUB, oauth2: null })).toBeNull();
  });
});

describe("setupLinkLabel", () => {
  it("names the known consoles and degrades for unknown presets", () => {
    expect(setupLinkLabel(GOOGLE)).toBe("Open Google Cloud Console");
    expect(setupLinkLabel(MICROSOFT)).toBe("Open Microsoft Entra");
    expect(setupLinkLabel(GITHUB)).toBe("Open GitHub developer settings");
    expect(setupLinkLabel({ ...GOOGLE, id: "acme", name: "Acme" })).toBe(
      "Open the Acme setup page",
    );
  });
});
