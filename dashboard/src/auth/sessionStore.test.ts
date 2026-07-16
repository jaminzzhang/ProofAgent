// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchRuns, validateSecretHandle } from '../api/client'
import {
  onSessionExpired,
  setCurrentCsrfToken,
} from './sessionStore'

describe('session-aware API client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setCurrentCsrfToken(null)
  })

  it('notifies the session UX on a 401 response', async () => {
    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('{"detail":"authentication_required"}', { status: 401 }),
    ))

    await expect(fetchRuns()).rejects.toThrow('401')
    expect(expired).toHaveBeenCalledOnce()
    unsubscribe()
  })

  it('adds the session-bound CSRF token to mutations', async () => {
    setCurrentCsrfToken('csrf-session-token')
    const mockedFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      handle: { protocol_id: 'vault', handle_id: 'model', purpose: 'model_credential' },
      resolvable: true,
      checked_at: '2026-07-15T00:00:00Z',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', mockedFetch)

    await validateSecretHandle({
      protocol_id: 'vault', handle_id: 'model', purpose: 'model_credential',
    })

    const options = mockedFetch.mock.calls[0][1] as RequestInit
    expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('csrf-session-token')
    expect(options.credentials).toBe('same-origin')
  })
})
