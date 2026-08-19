import createNextIntlPlugin from "next-intl/plugin";

// i18n (ADR-0029): links the build to the per-request locale resolution in
// src/i18n/request.ts (the plugin's default lookup path).
const withNextIntl = createNextIntlPlugin();

// --- Y.js single-instance guarantee (§4.2, #159) -----------------------------
//
// Y.js must resolve to ONE module instance: a second copy breaks its internal
// `instanceof` checks, and the damage shows up as apparent data corruption in
// the CRDT editor rather than as an error. The hazard is real — `yjs` ships a
// conditional exports map (`import` → yjs.mjs, `require` → yjs.cjs), and both
// `@tiptap/y-tiptap` and `y-protocols` ship CJS builds that `require("yjs")`.
//
// This used to be pinned by a `webpack:` resolve alias. That alias is gone, for
// two measured reasons:
//
//   1. Next 16 runs **Turbopack** by default and ignores the `webpack` hook
//      *without warning* — so the alias had silently stopped doing anything.
//   2. Turbopack's own `turbopack.resolveAlias` does not apply here either:
//      pointing `yjs` at a nonexistent path, and then at a different module
//      entirely, both left the build green and the bundle unchanged. It is not
//      an available mechanism, so configuring it would only look protective.
//
// What actually holds the invariant is that the client graph is ESM end to end
// (our `import * as Y from "yjs"` and @tiptap/y-tiptap's ESM build both land on
// yjs.mjs; nothing reaches the `require` condition), plus a single `yjs` in the
// lockfile. Both were verified to produce exactly one bundled copy under
// webpack AND Turbopack.
//
// Because that is an *emergent* property rather than a declared one, it is
// enforced instead of asserted: `npm run build` runs
// `scripts/check-yjs-singleton.mjs`, which counts Y.js copies in the emitted
// client chunks and fails the build if there is ever more than one. That guard
// is bundler-agnostic, so it survives the next default-bundler change too.

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (server.js + minimal node_modules) so the
  // production Docker image is small and doesn't ship dev dependencies.
  output: "standalone",
};

export default withNextIntl(nextConfig);
