import "@testing-library/jest-dom/vitest";

// jsdom has no clipboard and no URL.createObjectURL; both are used by the
// copy chips and the export path. Stubbing them here keeps the components
// under test rather than the browser.
// `configurable: true` matters: @testing-library/user-event installs its own
// clipboard stub per test, and a non-configurable property makes every
// userEvent.setup() throw "Cannot redefine property".
Object.defineProperty(navigator, "clipboard", {
  value: { writeText: async () => undefined },
  writable: true,
  configurable: true,
});
if (!("createObjectURL" in URL)) {
  Object.defineProperty(URL, "createObjectURL", { value: () => "blob:test", writable: true, configurable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: () => undefined, writable: true, configurable: true });
}
