import { forwardRef } from 'react'
import type { InputHTMLAttributes } from 'react'
import { cn } from '../lib/cn'

export type InputProps = InputHTMLAttributes<HTMLInputElement>

/**
 * Text input primitive. Consistent border, radius, and focus ring across
 * every search field and form input in both apps.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = 'text', ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          'flex h-9 w-full rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-1 text-sm text-[var(--text-primary)] transition-colors placeholder:text-[var(--text-muted)] focus-visible:border-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        ref={ref}
        {...props}
      />
    )
  },
)
Input.displayName = 'Input'
