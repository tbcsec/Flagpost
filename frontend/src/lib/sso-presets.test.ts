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
  params: [],
  scopes: "openid email profile",
  default_slug: "google",
  posture: "open",
  setup_url: "https://console.cloud.google.com/apis/credentials",
  notes: "Create an OAuth client in Google Cloud Console.",
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
    });
  });

  it("returns null while the issuer is unresolvable", () => {
    expect(presetToFormPrefill(MICROSOFT, {})).toBeNull();
    expect(presetToFormPrefill(MICROSOFT, { tenant_id: "nope" })).toBeNull();
  });
});

describe("setupLinkLabel", () => {
  it("names the known consoles and degrades for unknown presets", () => {
    expect(setupLinkLabel(GOOGLE)).toBe("Open Google Cloud Console");
    expect(setupLinkLabel(MICROSOFT)).toBe("Open Microsoft Entra");
    expect(setupLinkLabel({ ...GOOGLE, id: "acme", name: "Acme" })).toBe(
      "Open the Acme setup page",
    );
  });
});
