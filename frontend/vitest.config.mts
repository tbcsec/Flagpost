import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // No @vitejs/plugin-react: Vite is only vitest's bundler here (the app builds
  // with `next build`, not Vite), and the tests need only JSX transform, which
  // Vite 8's built-in oxc transformer does for React 19's automatic runtime.
  // Dropping the plugin also drops its Vite-8 / rolldown-oxc peer chain (#416).
  // (runtime:'automatic' + importSource:'react' are oxc's defaults; set here so
  // the intent is explicit rather than relying on them.)
  oxc: { jsx: { runtime: "automatic", importSource: "react" } },
  // Tests don't import the token stylesheet, so skip PostCSS/Tailwind entirely.
  // This also avoids loading Tailwind v4's native engine (Node 20+) during unit
  // tests, which may run under an older local Node than the Docker build uses.
  css: { postcss: { plugins: [] } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
