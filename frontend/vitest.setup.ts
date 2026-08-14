import "@testing-library/jest-dom/vitest";

// jsdom normally provides window.localStorage, but under some Node/jsdom
// combinations (observed intermittently on the CI Node 26 image) a worker's
// `window.localStorage` comes up `undefined`, which crashes any test that touches
// it directly (e.g. `window.localStorage.clear()` in a beforeEach). Guarantee a
// working in-memory Storage everywhere so the suite doesn't depend on that quirk.
function hasWorkingLocalStorage(): boolean {
  try {
    return typeof window !== "undefined" && !!window.localStorage;
  } catch {
    return false;
  }
}

if (typeof window !== "undefined" && !hasWorkingLocalStorage()) {
  const store = new Map<string, string>();
  const memoryStorage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    key: (index: number) => [...store.keys()][index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(window, "localStorage", {
    value: memoryStorage,
    configurable: true,
  });
}
