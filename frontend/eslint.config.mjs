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
      // Allow deliberately-unused args/vars prefixed with `_`.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },

  // --- CLAUDE.md architectural conventions, enforced as lint rules -----------
  // These move rules previously "enforced by convention and code review" into
  // automated guardrails. Kept scoped so they only fire where the convention
  // actually applies, and so their legitimate homes are exempt.

  // §8 — components/pages reach server state through a domain hook in
  // src/lib/hooks/, never the API client directly.
  {
    files: ["src/app/**/*.{ts,tsx}", "src/components/**/*.{ts,tsx}"],
    // providers.tsx's SessionRestorer is the auth-bootstrap boot call (restore
    // the session from the refresh cookie), not a component fetching domain
    // data — the one sanctioned direct use.
    ignores: ["src/app/providers.tsx"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/lib/api", "**/lib/api"],
              message:
                "Components go through a domain hook in src/lib/hooks/ (ARCHITECTURE.md §8), not the API client (@/lib/api) directly.",
            },
          ],
        },
      ],
    },
  },

  // §9 — colours come from design tokens (bg-primary, text-muted-foreground, …),
  // never a raw hex in a component. The brand mark is exempt: it carries the
  // fixed LOGO-SPEC colours by design. The theme registry (src/lib/theme.ts) is
  // already outside this scope — it *is* the palette/accent source of truth.
  {
    files: ["src/app/**/*.{ts,tsx}", "src/components/**/*.{ts,tsx}"],
    ignores: ["src/components/brand/**"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "Literal[value=/^#[0-9a-fA-F]{3,8}$/]",
          message:
            "Use a design token (ARCHITECTURE.md §9), not a raw hex value — add a token if one is missing.",
        },
      ],
    },
  },
];

export default eslintConfig;
