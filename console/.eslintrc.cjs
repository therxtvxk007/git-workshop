module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  rules: {
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    "react-hooks/rules-of-hooks": "error",
    "no-restricted-globals": ["error", { name: "Date", message: "Use nowUtc() from @/lib/format so cutoff logic stays testable." }],
  },
  ignorePatterns: ["dist", "node_modules"],
};
