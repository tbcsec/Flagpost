import { dirname } from "path";
import { fileURLToPath } from "url";

import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Next 15's ESLint configs (next/core-web-vitals, next/typescript) still ship as
// eslintrc-style presets; FlatCompat adapts them into this flat config. They
// bundle the plugins that matter for this app: @next/next (Next correctness),
// react + react-hooks (exhaustive-deps / rules-of-hooks — the load-bearing one
// for our effect-heavy hooks), jsx-a11y, and typescript-eslint.
const compat = new FlatCompat({ baseDirectory: __dirname });

const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "next-env.d.ts",
      "coverage/**",
      "public/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // Design system is tokens, not raw values (§9), but the theme registry is
      // *where* the palette/accent hexes legitimately live, and tests assert on
      // literals — so unused-vars/etc. are the useful signal, not style nits.
      // Allow deliberately-unused args/vars prefixed with `_`.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
];

export default eslintConfig;
