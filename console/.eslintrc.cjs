module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  rules: {
    "@typescript-eslint/no-unused-vars": [
      "error",
      {
        argsIgnorePattern: "^_",
        // Underscore-prefixed destructuring is how fields are deliberately
        // dropped when projecting a detail record down to a summary.
        varsIgnorePattern: "^_",
        ignoreRestSiblings: true,
      },
    ],
    "react-hooks/rules-of-hooks": "error",
    // Only reading the wall clock is restricted. `Date.parse(iso)` and
    // `new Date(iso)` are how every timestamp in the contract is interpreted
    // and must stay available; it is `new Date()` and `Date.now()` that make
    // cutoff logic untestable and time-dependent.
    "no-restricted-syntax": [
      "error",
      {
        selector: "NewExpression[callee.name='Date'][arguments.length=0]",
        message: "Use nowUtc() from @/lib/format so cutoff logic stays testable.",
      },
      {
        selector: "CallExpression[callee.object.name='Date'][callee.property.name='now']",
        message: "Use nowUtc() from @/lib/format so cutoff logic stays testable.",
      },
    ],
  },
  overrides: [
    {
      // nowUtc() is the one place allowed to read the clock; it exists so
      // every other module can be tested against a fixed time.
      files: ["src/lib/format.ts"],
      rules: { "no-restricted-syntax": "off" },
    },
  ],
  ignorePatterns: ["dist", "node_modules"],
};
