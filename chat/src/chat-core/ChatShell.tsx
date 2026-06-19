import { useEffect, useRef } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { ArrowUp } from 'lucide-react'
import {
  Avatar,
  AvatarFallback,
  BrandMark,
  Button,
  Markdown,
  Textarea,
  cn,
} from '@proofagent/ui'
import type { ChatTurnView } from './types'
import { useLocale } from '../i18n/locale'

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
  const { t } = useLocale()

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

  // Enter to send, Shift+Enter for newline
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      if (!sending && inputValue.trim()) onSubmit()
    }
  }

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-6xl flex-col px-4">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
            {title}
          </h1>
          <p className="mt-1 truncate text-sm text-[var(--text-muted)]">{subtitle}</p>
        </div>
        {footer}
      </div>

      <div className={sidePanel ? 'grid min-h-0 flex-1 gap-5 lg:grid-cols-[minmax(0,1fr)_280px]' : 'grid min-h-0 flex-1'}>
        <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 sm:p-6">
            {turns.length === 0 && !sending ? (
              <div className="flex h-full min-h-[320px] flex-col justify-end gap-3">
                {starters.length > 0 ? (
                  starters.map((starter) => (
                    <button
                      key={starter.label}
                      type="button"
                      onClick={starter.onSelect}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3 text-left text-sm font-medium text-[var(--text-primary)] transition hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
                    >
                      {starter.label}
                    </button>
                  ))
                ) : (
                  <div className="flex flex-col items-center justify-center text-center">
                    <h2 className="text-sm font-semibold text-[var(--text-primary)]">{emptyTitle}</h2>
                    <p className="mt-1 max-w-[280px] text-xs leading-5 text-[var(--text-muted)]">
                      {emptyDescription}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-6">
                {turns.map((turn) => (
                  <article key={turn.id} className="space-y-3">
                    {/* User message: right-aligned accent bubble */}
                    <div className="flex justify-end gap-3">
                      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-[var(--accent-fg)]">
                        {turn.question}
                      </div>
                      <Avatar className="mt-0.5 h-7 w-7 rounded-md">
                        <AvatarFallback className="rounded-md bg-[var(--bg-hover)] text-[10px] text-[var(--text-secondary)]">
                          You
                        </AvatarFallback>
                      </Avatar>
                    </div>

                    {/* Assistant message: bordered card with header + markdown + actions */}
                    <div className="flex gap-3">
                      <BrandMark size="sm" className="mt-0.5 h-7 w-7 rounded-md" />
                      <div className="max-w-[85%] flex-1 space-y-3 rounded-2xl rounded-tl-md border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-3 shadow-[var(--shadow-xs)]">
                        {renderAssistantMeta?.(turn)}
                        <Markdown>{turn.assistant.content}</Markdown>
                        {renderAssistantActions?.(turn)}
                      </div>
                    </div>
                  </article>
                ))}
                {sending && (
                  <div className="flex gap-3">
                    <BrandMark size="sm" className="mt-0.5 h-7 w-7 rounded-md" />
                    <div className="flex max-w-[85%] items-center rounded-2xl rounded-tl-md border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-4">
                      {sendingLabel ?? (
                        <span className="text-xs font-medium text-[var(--text-muted)]">
                          {t('chatShell.working')}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Composer: auto-grow textarea + Enter-to-send */}
          <form onSubmit={handleSubmit} className="border-t border-[var(--border)] p-3 sm:p-4">
            {error && (
              <div className="mb-3 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-3 py-2 text-sm text-[var(--danger-fg)]">
                {error}
              </div>
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
                <span>{t('chatShell.networkSupplement')}</span>
              </label>
            )}
            <div
              className={cn(
                'flex items-end gap-2 rounded-xl border bg-[var(--bg-base)] px-2 py-1.5 transition-colors',
                'border-[var(--border-strong)] focus-within:border-[var(--accent)]',
              )}
            >
              <Textarea
                value={inputValue}
                onChange={(event) => onInputChange(event.target.value)}
                onKeyDown={handleKeyDown}
                disabled={sending}
                placeholder={placeholder}
                autoGrow
                maxHeight={160}
                rows={1}
                className="flex-1 resize-none border-0 bg-transparent px-2 py-1.5 focus-visible:ring-0"
              />
              <Button
                type="submit"
                size="icon"
                disabled={sending || !inputValue.trim()}
                aria-label={submitLabel}
                className="mb-0.5 shrink-0"
              >
                <ArrowUp size={16} strokeWidth={2.5} />
              </Button>
            </div>
          </form>
        </section>

        {sidePanel && <aside className="min-w-0 space-y-4">{sidePanel}</aside>}
      </div>
    </div>
  )
}
