import { afterEach, expect, it, vi } from 'vitest'
import { dashboardUrl } from './navigation'
afterEach(() => vi.unstubAllEnvs())
it('returns to the current gateway in a built app', () => {
  vi.stubEnv('DEV', false); vi.stubEnv('VITE_DASHBOARD_URL', undefined)
  expect(dashboardUrl('/runs/run_1')).toBe('/runs/run_1')
})
it('supports explicit origins and explicit same-origin configuration', () => {
  vi.stubEnv('VITE_DASHBOARD_URL', 'https://dashboard.example/')
  expect(dashboardUrl('/runs/run_1')).toBe('https://dashboard.example/runs/run_1')
  vi.stubEnv('VITE_DASHBOARD_URL', '')
  expect(dashboardUrl('/runs/run_1')).toBe('/runs/run_1')
})
