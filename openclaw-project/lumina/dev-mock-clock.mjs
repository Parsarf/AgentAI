// MOCK_NOW=<epoch seconds> freezes the mock's clock, so every time it reports ("4m ago", today's events, the greeting's date) is the same on every run: the
// visual regression baselines (tests/visual-browser.mjs) depend on it. Imported first by dev-mock.mjs, before anything reads the time.
if (process.env.MOCK_NOW) {
  const fixed = Number(process.env.MOCK_NOW) * 1000;
  const Real = Date;
  globalThis.Date = class extends Real {
    constructor(...args) { super(...(args.length ? args : [fixed])); }
    static now() { return fixed; }
  };
}
