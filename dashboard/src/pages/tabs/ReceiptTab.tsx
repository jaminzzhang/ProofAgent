import { useState } from 'react'
import { Markdown } from '@proofagent/ui'
import { CodeBlock } from '../../components/CodeBlock'
import { EmptyState } from '../../components/EmptyState'

interface ReceiptTabProps {
  markdown: string
}

/**
 * Renders the governance receipt as GitHub-flavored Markdown by default.
 *
 * A "View raw" toggle reveals the verbatim source (in a CodeBlock) for
 * audit cases where the exact stored bytes matter (e.g. comparing against
 * a signed hash). Default is the rendered, human-readable form.
 */
export function ReceiptTab({ markdown }: ReceiptTabProps) {
  const [raw, setRaw] = useState(false)

  if (!markdown) return <EmptyState message="No receipt available." />

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setRaw((value) => !value)}
          className="text-xs font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
        >
          {raw ? 'Rendered' : 'View raw'}
        </button>
      </div>
      {raw ? (
        <CodeBlock>{markdown}</CodeBlock>
      ) : (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <Markdown>{markdown}</Markdown>
        </div>
      )}
    </div>
  )
}
