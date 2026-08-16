import { createRequire } from "module";
import createNextIntlPlugin from "next-intl/plugin";

const require = createRequire(import.meta.url);

// i18n (ADR-0029): links the build to the per-request locale resolution in
// src/i18n/request.ts (the plugin's default lookup path).
const withNextIntl = createNextIntlPlugin();

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (server.js + minimal node_modules) so the
  // production Docker image is small and doesn't ship dev dependencies.
  output: "standalone",
  webpack: (config) => {
    // Force every `yjs` import/require to resolve to one module instance. Y.js
    // must be a singleton — a second copy (our ESM import vs a transitive CJS
    // require in y-prosemirror) breaks its internal `instanceof` checks (§4.2).
    config.resolve.alias = {
      ...config.resolve.alias,
      yjs: require.resolve("yjs"),
    };
    return config;
  },
};

export default withNextIntl(nextConfig);
