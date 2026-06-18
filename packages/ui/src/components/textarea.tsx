import { forwardRef, useEffect, useRef } from 'react'
import type { TextareaHTMLAttributes } from 'react'
import { cn } from '../lib/cn'

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  /** Auto-grow the textarea to fit content up to maxHeight (px). */
  autoGrow?: boolean
  maxHeight?: number
}

/**
 * Textarea primitive. With `autoGrow`, expands to fit content up to
 * `maxHeight` (default 200px) — used by the chat composer.
 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, autoGrow = false, maxHeight = 200, onChange, ...props }, ref) => {
    const innerRef = useRef<HTMLTextAreaElement | null>(null)

    const resize = (el: HTMLTextAreaElement | null) => {
      if (!el || !autoGrow) return
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
    }

    useEffect(() => {
      resize(innerRef.current)
    }, [autoGrow, maxHeight, props.value])

    return (
      <textarea
        className={cn(
          'flex min-h-[2.5rem] w-full rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-2 text-sm leading-6 text-[var(--text-primary)] transition-colors placeholder:text-[var(--text-muted)] focus-visible:border-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50',
          autoGrow && 'resize-none overflow-y-auto',
          className,
        )}
        ref={(node) => {
          innerRef.current = node
          if (typeof ref === 'function') ref(node)
          else if (ref) ref.current = node
        }}
        onChange={(e) => {
          resize(e.currentTarget)
          onChange?.(e)
        }}
        {...props}
      />
    )
  },
)
Textarea.displayName = 'Textarea'
