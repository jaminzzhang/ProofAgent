import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cn } from '../lib/cn'

interface CopyButtonProps {
  /** Text to copy to the clipboard. */
  value: string
  /** Accessible label / tooltip. */
  label?: string
  className?: string
  size?: number
}

/**
 * Copy-to-clipboard icon button with a transient "copied" check state.
 * Used for run IDs, trace IDs, and other mono identifiers.
 */
export function CopyButton({
  value,
  label = 'Copy',
  className,
  size = 14,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard may be unavailable; fail silently
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex h-6 w-6 items-center justify-center rounded text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
        copied && 'text-[var(--success-fg)]',
        className,
      )}
    >
      {copied ? <Check size={size} strokeWidth={2.25} /> : <Copy size={size} strokeWidth={2} />}
    </button>
  )
}
