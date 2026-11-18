import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  {
    // Generated, not authored: api.d.ts comes from the OpenAPI document and
    // next-env.d.ts is written by Next on every build.
    ignores: [
      ".next/**",
      "node_modules/**",
      "types/api.d.ts",
      "next-env.d.ts",
      "coverage/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      /*
       * Money must never become a JavaScript number.
       *
       * These three are the ways it happens by accident, so they are errors rather
       * than warnings: a float loses cents on a large balance, and a statement that
       * is out by a cent is a statement that cannot be issued.
       */
      "no-restricted-globals": [
        "error",
        { name: "parseFloat", message: "Money is a string. Format it; never parse it." },
        { name: "parseInt", message: "Use a string comparison, or Number() for a non-money value." },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "BinaryExpression[operator=/^[*/]$/] > Identifier[name=/[Aa]mount$/]",
          message: "Do not do arithmetic on an amount in the browser; ask the API.",
        },
      ],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "separate-type-imports" },
      ],
    },
  },
];

export default config;
