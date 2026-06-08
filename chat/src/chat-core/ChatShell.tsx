import { useEffect, useRef } from 'react'
import type { FormEvent, ReactNode } from 'react'

import type { ChatTurnView } from './types'

interface StarterAction {
  label: string
  onSelect: () => void
}

interface ChatShellProps {
  title: string
  subtitle: string
  turns: ChatTurnView[]
  inputValue: string
  onInputChange: (value: string) => void
  onSubmit: () => void
  sending: boolean
  placeholder: string
  submitLabel: string
  emptyTitle: string
  emptyDescription: string
  error?: string | null
  footer?: ReactNode
  sidePanel?: ReactNode
  starters?: StarterAction[]
  renderAssistantMeta?: (turn: ChatTurnView) => ReactNode
  renderAssistantActions?: (turn: ChatTurnView) => ReactNode
  sendingLabel?: ReactNode
  untrustedWebSupplementToggle?: {
    checked: boolean
    onChange: (enabled: boolean) => void
  }
}

export function ChatShell({
  title,
  subtitle,
  turns,
  inputValue,
  onInputChange,
  onSubmit,
  sending,
  placeholder,
  submitLabel,
  emptyTitle,
  emptyDescription,
  error,
  footer,
  sidePanel,
  starters = [],
  renderAssistantMeta,
  renderAssistantActions,
  sendingLabel,
  untrustedWebSupplementToggle,
}: ChatShellProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    if (typeof container.scrollTo === 'function') {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
      return
    }
    container.scrollTop = container.scrollHeight
  }, [turns.length, sending])

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit()
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] w-full max-w-6xl flex-col px-4">
      <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal text-[var(--text-primary)]">{title}</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">{subtitle}</p>
        </div>
        {footer}
      </div>

      <div className={sidePanel ? 'grid min-h-0 flex-1 gap-5 lg:grid-cols-[minmax(0,1fr)_280px]' : 'min-h-0 flex-1'}>
        <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] shadow-sm">
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 sm:p-6">
            {turns.length === 0 && !sending ? (
              <div className="flex h-full min-h-[360px] flex-col justify-end gap-3">
                {starters.length > 0 ? (
                  starters.map((starter) => (
                    <button
                      key={starter.label}
                      type="button"
                      onClick={starter.onSelect}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-hover)] px-4 py-3 text-left text-sm font-medium text-[var(--text-primary)] transition hover:border-[var(--accent)]"
                    >
                      {starter.label}
                    </button>
                  ))
                ) : (
                  <div className="flex flex-col items-center justify-center text-center">
                    <h2 className="text-sm font-semibold text-[var(--text-primary)]">{emptyTitle}</h2>
                    <p className="mt-1 max-w-[260px] text-xs leading-5 text-[var(--text-muted)]">
                      {emptyDescription}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-5">
                {turns.map((turn) => (
                  <article key={turn.id} className="space-y-3">
                    <div className="flex justify-end">
                      <div className="max-w-[82%] rounded-lg bg-[var(--accent)] px-4 py-3 text-sm font-medium text-white">
                        {turn.question}
                      </div>
                    </div>
                    <div className="max-w-[88%] space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-4 shadow-sm">
                      {renderAssistantMeta?.(turn)}
                      <p className="whitespace-pre-wrap text-sm leading-6 text-[var(--text-primary)]">
                        {turn.assistant.content || (
                          <span className="italic text-[var(--text-muted)]">No output generated.</span>
                        )}
                      </p>
                      {renderAssistantActions?.(turn)}
                    </div>
                  </article>
                ))}
                {sending && (
                  <div className="max-w-[88%] rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-4">
                    {sendingLabel ?? (
                      <span className="text-xs font-medium text-[var(--text-muted)]">Working...</span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          <form onSubmit={handleSubmit} className="border-t border-[var(--border)] p-3 sm:p-4">
            {error && (
              <div className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
            )}
            {untrustedWebSupplementToggle && (
              <label className="mb-3 flex w-fit items-center gap-2 text-xs font-medium text-[var(--text-muted)]">
                <input
                  type="checkbox"
                  checked={untrustedWebSupplementToggle.checked}
                  onChange={(event) => untrustedWebSupplementToggle.onChange(event.target.checked)}
                  disabled={sending}
                  className="h-4 w-4 rounded border-[var(--border)] text-[var(--accent)]"
                />
                <span>Network supplement</span>
              </label>
            )}
            <div className="flex gap-3">
              <input
                value={inputValue}
                onChange={(event) => onInputChange(event.target.value)}
                disabled={sending}
                placeholder={placeholder}
                className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 disabled:opacity-60"
              />
              <button
                type="submit"
                disabled={sending || !inputValue.trim()}
                className="rounded-lg bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitLabel}
              </button>
            </div>
          </form>
        </section>

        {sidePanel && <aside className="min-w-0 space-y-4">{sidePanel}</aside>}
      </div>
    </div>
  )
}
