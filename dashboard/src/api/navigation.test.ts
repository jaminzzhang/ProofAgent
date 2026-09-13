import { afterEach, expect, it, vi } from 'vitest'
import { chatUrl } from './client'
afterEach(() => vi.unstubAllEnvs())
it('keeps built Dashboard links on the gateway without an override', () => {
  vi.stubEnv('DEV', false); vi.stubEnv('VITE_CHAT_URL', undefined)
  expect(chatUrl('/operator/agents/example/new')).toBe('/operator/agents/example/new')
})
it('preserves an explicit deployment origin without double slashes', () => {
  vi.stubEnv('VITE_CHAT_URL', 'https://chat.example/')
  expect(chatUrl('/operator')).toBe('https://chat.example/operator')
})
