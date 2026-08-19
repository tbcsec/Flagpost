#!/usr/bin/env node
// Fail the build if more than one copy of Y.js ends up in the client bundle
// (§4.2, #159).
//
// Why a build check and not a resolve alias: the `webpack:` alias that used to
// pin this became a silent no-op when Next 16 made Turbopack the default, and
// Turbopack's `resolveAlias` was measured not to apply here at all (see
// next.config.mjs). The invariant currently holds because the client graph is
// ESM end to end — an emergent property no config declares, and one a single
// future dependency resolving `yjs` through its `require` condition would
// break. This checks the thing we actually care about (what shipped), so it
// stays correct across bundler and dependency changes.
//
// Detection: a string literal that appears exactly once per copy of Y.js.
// String literals survive minification, unlike identifiers.

import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";
import { fileURLToPath } from "url";

const MARKER = "Unexpected content type in insert operation";
const ROOT = fileURLToPath(new URL(".", import.meta.url));

/** Every .js file under `dir`, recursively. Exported for the unit test. */
export function jsFiles(dir) {
  let out = [];
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return out; // missing dir — the caller decides whether that's fatal
  }
  for (const entry of entries) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out = out.concat(jsFiles(full));
    else if (entry.endsWith(".js")) out.push(full);
  }
  return out;
}

/** How many copies of Y.js the emitted chunks contain. Exported for the test. */
export function countYjsCopies(chunkDir) {
  let copies = 0;
  for (const file of jsFiles(chunkDir)) {
    const text = readFileSync(file, "utf8");
    let from = 0;
    for (;;) {
      const at = text.indexOf(MARKER, from);
      if (at === -1) break;
      copies += 1;
      from = at + MARKER.length;
    }
  }
  return copies;
}

// Only run the check when executed directly, so the test can import the helpers.
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const chunkDir = process.argv[2] ?? join(ROOT, "..", ".next", "static", "chunks");
  const files = jsFiles(chunkDir);
  if (files.length === 0) {
    console.error(`check-yjs-singleton: no client chunks found in ${chunkDir}`);
    process.exit(1);
  }
  const copies = countYjsCopies(chunkDir);
  if (copies === 1) {
    console.log("check-yjs-singleton: ok (1 copy of Y.js in the client bundle)");
  } else if (copies === 0) {
    // Not "safe": it means the marker went stale (a Y.js upgrade changed the
    // string), so the check is no longer testing anything.
    console.error(
      "check-yjs-singleton: FAILED — found 0 copies of Y.js.\n" +
        `The detection marker (${JSON.stringify(MARKER)}) no longer appears in the\n` +
        "bundle. Either Y.js was removed, or an upgrade changed that string and\n" +
        "this check needs a new marker — do not just delete it.",
    );
    process.exit(1);
  } else {
    console.error(
      `check-yjs-singleton: FAILED — found ${copies} copies of Y.js in the client bundle.\n` +
        "Y.js must be a singleton: a second instance breaks its internal\n" +
        "`instanceof` checks and corrupts collaborative editing (§4.2).\n" +
        "Likely causes: a dependency pulling `yjs` through its `require`\n" +
        "condition (dual-package hazard), or a second `yjs` version in the\n" +
        "lockfile — check `npm ls yjs`.",
    );
    process.exit(1);
  }
}
