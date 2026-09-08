import { ConfigPanel } from '@proofagent/ui'

/** Advanced document authoring; the Workspace validates the complete bundle on save. */
export function ContractDocumentEditor({ title, description, value, busy, onChange }: {
  title: string
  description: string
  value: string
  busy: boolean
  onChange: (value: string) => void
}) {
  return <ConfigPanel title={title} description={description} headingLevel={3}>
    <textarea aria-label={title} value={value} disabled={busy} spellCheck={false} rows={20}
      className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 font-mono text-sm text-[var(--text-primary)]"
      onChange={event => onChange(event.target.value)} />
  </ConfigPanel>
}
