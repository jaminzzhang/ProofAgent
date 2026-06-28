import { useId, useState } from 'react'
import { X } from 'lucide-react'
import { cn } from '../lib/cn'

/**
 * ReferenceChips — add/remove chip input for repeatable string lists
 * (knowledge bindings, tool contracts, policy rules, validator refs).
 * Replaces the "one ref per line" `<textarea>` pattern with a quick,
 * keyboard-friendly control: type + Enter to add, click × / Backspace on
 * empty input to remove.
 *
 * When `suggestions` are provided, the input becomes a datalist-backed
 * combobox: the user can pick a known ref or type a custom one. Free-form
 * entry is always preserved.
 */
export interface ReferenceChipsProps {
  values: string[]
  onChange: (next: string[]) => void
  /** Known refs offered as autocomplete suggestions. */
  suggestions?: string[]
  /** Placeholder for the input. */
  placeholder?: string
  /** Aria label for the whole control. */
  ariaLabel?: string
  disabled?: boolean
  className?: string
}

export function ReferenceChips({
  values,
  onChange,
  suggestions = [],
  placeholder = 'Add a reference and press Enter',
  ariaLabel = 'References',
  disabled = false,
  className,
}: ReferenceChipsProps) {
  const listId = useId()
  const [draft, setDraft] = useState('')

  const commit = (raw: string) => {
    const next = raw.trim()
    if (!next) return
    if (values.includes(next)) {
      setDraft('')
      return
    }
    onChange([...values, next])
    setDraft('')
  }

  const remove = (idx: number) => {
    onChange(values.filter((_, i) => i !== idx))
  }

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        'flex min-w-0 flex-wrap items-center gap-1.5 rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] p-1.5 focus-within:border-[var(--accent)] focus-within:outline-none focus-within:ring-2 focus-within:ring-[var(--ring)]',
        disabled && 'pointer-events-none opacity-50',
        className,
      )}
    >
      {values.map((ref, idx) => (
        <span
          key={`${ref}-${idx}`}
          translate="no"
          className="inline-flex min-w-0 max-w-full items-center gap-1 rounded border border-[var(--border)] bg-[var(--bg-hover)] py-0.5 pl-2 pr-1 font-mono text-xs text-[var(--text-primary)]"
        >
          <span className="min-w-0 break-all">{ref}</span>
          <button
            type="button"
            onClick={() => remove(idx)}
            aria-label={`Remove ${ref}`}
            className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[var(--text-muted)] hover:bg-[var(--bg-active)] hover:text-[var(--danger-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </button>
        </span>
      ))}

      <input
        list={suggestions.length ? listId : undefined}
        value={draft}
        placeholder={values.length ? '' : placeholder}
        aria-label={`Add to ${ariaLabel}`}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            commit(draft)
          } else if (e.key === 'Backspace' && draft === '' && values.length) {
            e.preventDefault()
            remove(values.length - 1)
          }
        }}
        className="min-w-[8rem] flex-1 bg-transparent px-1.5 py-1 font-mono text-xs text-[var(--text-primary)] placeholder:font-sans placeholder:text-[var(--text-muted)] focus:outline-none"
      />

      {suggestions.length > 0 && (
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </div>
  )
}
