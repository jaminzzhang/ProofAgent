import { cn } from '../lib/cn'

interface CodeBlockProps {
  children: string
  className?: string
}

/**
 * Monospace block for YAML/JSON/code-like content.
 */
export function CodeBlock({ children, className }: CodeBlockProps) {
  return (
    <pre
      className={cn(
        'overflow-x-auto whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 font-mono text-xs text-[var(--text-secondary)]',
        className,
      )}
    >
      {children}
    </pre>
  )
}
