import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { LOCALES } from "./config";

// The CI gate for the Crowdin pipeline (ADR-0029, docs/TRANSLATIONS.md):
// translation PRs arrive machine-generated, so every catalog in
// frontend/messages/ is validated against the English source — structure,
// completeness, and (critically) that ICU placeholders and rich-text tags
// survived translation. A dropped {password} or <link> tag renders as a
// runtime crash or corrupted sentence, not a type error, so it's pinned here.

const MESSAGES_DIR = path.join(__dirname, "../../messages");

type Catalog = { [key: string]: string | Catalog };

/** Flatten {a: {b: "x"}} to Map("a.b" → "x"). */
function flatten(node: Catalog, prefix = "", out = new Map<string, string>()) {
  for (const [key, value] of Object.entries(node)) {
    const dotted = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(dotted, value);
    else flatten(value, dotted, out);
  }
  return out;
}

/** ICU argument names: {name} and {name, plural, ...} both yield "name". */
function icuArgs(message: string): string[] {
  return [...message.matchAll(/\{\s*([a-zA-Z0-9_]+)/g)].map((m) => m[1]).sort();
}

/** Rich-text tag names: <pw>…</pw> yields "pw" (open and close counted). */
function icuTags(message: string): string[] {
  return [...message.matchAll(/<\/?([a-zA-Z0-9_]+)>/g)].map((m) => m[1]).sort();
}

const files = fs.readdirSync(MESSAGES_DIR).filter((f) => f.endsWith(".json"));
const source = flatten(
  JSON.parse(fs.readFileSync(path.join(MESSAGES_DIR, "en.json"), "utf8")),
);

describe("message catalogs", () => {
  it("ships a catalog for every configured locale, and en is non-trivial", () => {
    for (const locale of LOCALES) {
      expect(files).toContain(`${locale}.json`);
    }
    expect(source.size).toBeGreaterThan(0);
  });

  describe.each(files)("%s", (file) => {
    const catalog = flatten(
      JSON.parse(fs.readFileSync(path.join(MESSAGES_DIR, file), "utf8")),
    );

    it("has exactly the source keys — no missing, no extras", () => {
      // Runtime loads one catalog with no English merge (src/i18n/request.ts),
      // so a missing key renders as its raw key path. Crowdin exports complete
      // files (untranslated strings carry the English source text) — hold
      // every catalog to that.
      expect([...catalog.keys()].sort()).toEqual([...source.keys()].sort());
    });

    it("has no empty messages", () => {
      for (const [key, message] of catalog) {
        expect(message.trim(), key).not.toBe("");
      }
    });

    it("preserves every ICU placeholder and rich-text tag from the source", () => {
      for (const [key, message] of catalog) {
        const original = source.get(key);
        if (original === undefined) continue; // key-set mismatch already failed above
        expect(icuArgs(message), `${key}: interpolation arguments`).toEqual(
          icuArgs(original),
        );
        expect(icuTags(message), `${key}: rich-text tags`).toEqual(
          icuTags(original),
        );
      }
    });
  });
});
