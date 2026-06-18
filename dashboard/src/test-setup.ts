import '@testing-library/jest-dom/vitest'

/**
 * jsdom does not implement ResizeObserver, which recharts' ResponsiveContainer
 * (and other libs) depend on. Provide a minimal stub for the test environment.
 */
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  ;(globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver
}
