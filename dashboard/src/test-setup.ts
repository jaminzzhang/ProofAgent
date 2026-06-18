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
 * jsdom does not implement ResizeObserver, which recharts' ResponsiveContainer
 * (and other libs) depend on. Return a stable non-zero size so chart tests do
 * not emit layout warnings.
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
