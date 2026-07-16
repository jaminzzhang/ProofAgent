import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { fetchOperatorSession } from '../api/client'
import type { OperatorSession } from '../api/types'
import {
  onSessionExpired,
  setCurrentCsrfToken,
} from './sessionStore'

type SessionStatus = 'loading' | 'authenticated' | 'expired' | 'unavailable'

interface SessionContextValue {
  readonly session: OperatorSession | null
  readonly status: SessionStatus
  readonly hasPermission: (permission: string) => boolean
}

const SessionContext = createContext<SessionContextValue>({
  session: null,
  status: 'loading',
  hasPermission: () => false,
})

export function SessionProvider({ children }: { readonly children: React.ReactNode }) {
  const [session, setSession] = useState<OperatorSession | null>(null)
  const [status, setStatus] = useState<SessionStatus>('loading')

  useEffect(() => {
    let cancelled = false
    const unsubscribe = onSessionExpired(() => {
      if (!cancelled) {
        setSession(null)
        setStatus('expired')
      }
    })
    fetchOperatorSession()
      .then((loaded) => {
        if (!cancelled) {
          setSession(loaded)
          setCurrentCsrfToken(loaded.csrf_token)
          setStatus('authenticated')
        }
      })
      .catch((error: unknown) => {
        if (!cancelled && status !== 'expired') {
          setStatus(error instanceof Error && error.message.includes('401') ? 'expired' : 'unavailable')
        }
      })
    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [])

  const value = useMemo<SessionContextValue>(() => ({
    session,
    status,
    hasPermission: (permission) => session?.effective_permissions.includes(permission) ?? false,
  }), [session, status])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionContextValue {
  return useContext(SessionContext)
}

export function SessionExpiredBanner() {
  const { status } = useSession()
  if (status !== 'expired') return null
  return (
    <div role="alert" className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-center text-sm">
      Your operator session expired or requires refreshed claims.{' '}
      <a className="font-medium underline" href="/api/auth/login">Sign in again</a>
    </div>
  )
}
