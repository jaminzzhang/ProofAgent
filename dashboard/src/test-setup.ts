import '@testing-library/jest-dom/vitest'

const TEST_ELEMENT_WIDTH = 800
const TEST_ELEMENT_HEIGHT = 400

Object.defineProperties(HTMLElement.prototype, {
  clientWidth: {
    configurable: true,
    get() {
      return TEST_ELEMENT_WIDTH
    },
  },
  clientHeight: {
    configurable: true,
    get() {
      return TEST_ELEMENT_HEIGHT
    },
  },
  offsetWidth: {
    configurable: true,
    get() {
      return TEST_ELEMENT_WIDTH
    },
  },
  offsetHeight: {
    configurable: true,
    get() {
      return TEST_ELEMENT_HEIGHT
    },
  },
})

HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
  return {
    width: TEST_ELEMENT_WIDTH,
    height: TEST_ELEMENT_HEIGHT,
    top: 0,
    right: TEST_ELEMENT_WIDTH,
    bottom: TEST_ELEMENT_HEIGHT,
    left: 0,
    x: 0,
    y: 0,
    toJSON: () => undefined,
  }
}

/**
 * jsdom does not implement ResizeObserver, which some libs (e.g. Radix
 * overflow detection, virtualized lists) depend on. Return a stable non-zero
 * size so layout-dependent tests do not emit warnings.
 */
class ResizeObserverStub {
  private readonly callback: ResizeObserverCallback

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }

  observe(target: Element) {
    const rect = target.getBoundingClientRect()
    this.callback(
      [
        {
          target,
          contentRect: rect,
        } as ResizeObserverEntry,
      ],
      this as unknown as ResizeObserver,
    )
  }

  unobserve() {}
  disconnect() {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  ;(globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver
}

/**
 * Minimal in-memory localStorage stub for tests whose components persist theme
 * or locale (ThemeProvider / LocaleProvider read+write localStorage). jsdom
 * usually provides this, but some configurations expose it on `window` only.
 */
const globalLocalStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')

if (!globalLocalStorageDescriptor || typeof globalLocalStorageDescriptor.get === 'function') {
  const store = new Map<string, string>()
  const localStorageStub = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, String(value))
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size
    },
  }
  Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageStub,
    configurable: true,
    writable: true,
  })
}
