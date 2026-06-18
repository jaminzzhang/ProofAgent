import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'
import { cn } from '../lib/cn'

type ToastVariant = 'success' | 'error' | 'info'

interface Toast {
  id: number
  title: string
  description?: string
  variant: ToastVariant
  duration: number
}

interface ToastInput {
  title: string
  description?: string
  duration?: number
}

interface ToastContextValue {
  toast: (input: ToastInput & { variant?: ToastVariant }) => void
  success: (input: ToastInput) => void
  error: (input: ToastInput) => void
  info: (input: ToastInput) => void
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined)

const VARIANT_STYLES: Record<
  ToastVariant,
  { icon: typeof CheckCircle2; ring: string; iconClass: string }
> = {
  success: {
    icon: CheckCircle2,
    ring: 'border-[var(--success-border)]',
    iconClass: 'text-[var(--success-fg)]',
  },
  error: {
    icon: AlertTriangle,
    ring: 'border-[var(--danger-border)]',
    iconClass: 'text-[var(--danger-fg)]',
  },
  info: {
    icon: Info,
    ring: 'border-[var(--neutral-border)]',
    iconClass: 'text-[var(--neutral-fg)]',
  },
}

let toastSeq = 0

export function ToasterProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const toast = useCallback(
    (input: ToastInput & { variant?: ToastVariant }) => {
      const id = ++toastSeq
      const next: Toast = {
        id,
        title: input.title,
        description: input.description,
        variant: input.variant ?? 'info',
        duration: input.duration ?? 4500,
      }
      setToasts((prev) => [...prev, next])
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), next.duration),
      )
    },
    [dismiss],
  )

  const value = useMemo<ToastContextValue>(
    () => ({
      toast,
      success: (i) => toast({ ...i, variant: 'success' }),
      error: (i) => toast({ ...i, variant: 'error' }),
      info: (i) => toast({ ...i, variant: 'info' }),
      dismiss,
    }),
    [toast, dismiss],
  )

  useEffect(() => {
    const map = timers.current
    return () => {
      map.forEach((t) => clearTimeout(t))
      map.clear()
    }
  }, [])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts.map((t) => {
          const v = VARIANT_STYLES[t.variant]
          const Icon = v.icon
          return (
            <div
              key={t.id}
              role="status"
              className={cn(
                'pointer-events-auto flex items-start gap-3 rounded-lg border bg-[var(--bg-elevated)] p-3 pr-9 shadow-[var(--shadow-lg)] animate-in fade-in-0',
                v.ring,
              )}
            >
              <Icon size={18} className={cn('mt-0.5 shrink-0', v.iconClass)} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-[var(--text-primary)]">
                  {t.title}
                </p>
                {t.description && (
                  <p className="mt-0.5 text-xs leading-5 text-[var(--text-muted)]">
                    {t.description}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
                className="absolute right-2 top-2 rounded p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
              >
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    throw new Error('useToast must be used within a ToasterProvider')
  }
  return ctx
}
