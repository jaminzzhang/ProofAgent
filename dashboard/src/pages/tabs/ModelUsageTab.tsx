import type { ModelUsage } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'

interface ModelUsageTabProps {
  usage: ModelUsage
}

export function ModelUsageTab({ usage }: ModelUsageTabProps) {
  if (!usage || Object.keys(usage).length === 0) return <EmptyState message="No model usage data." />

  const rows: { label: string; value: string }[] = [
    { label: 'Provider', value: usage.provider ?? 'n/a' },
    { label: 'Model', value: usage.model ?? 'n/a' },
    { label: 'Status', value: usage.status ?? 'n/a' },
    { label: 'Message Count', value: String(usage.message_count ?? 'n/a') },
    { label: 'Estimated Tokens', value: String(usage.estimated_tokens ?? 'n/a') },
    { label: 'Stream', value: usage.stream ? 'true' : 'false' },
    { label: 'Cost Class', value: usage.cost_class ?? 'n/a' },
    { label: 'Finish Reason', value: usage.finish_reason ?? 'n/a' },
    { label: 'Content Length', value: usage.content_length ? `${usage.content_length} chars` : 'n/a' },
    { label: 'Input Tokens', value: String(usage.input_tokens ?? 'n/a') },
    { label: 'Output Tokens', value: String(usage.output_tokens ?? 'n/a') },
    { label: 'Total Tokens', value: String(usage.total_tokens ?? 'n/a') },
  ]

  if (usage.error_code) {
    rows.push({ label: 'Error Code', value: usage.error_code })
  }

  return (
    <div className="border border-[var(--border)] rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-[var(--border)] last:border-0">
              <td className="px-4 py-2 text-[var(--text-muted)] font-medium w-40">{row.label}</td>
              <td className="px-4 py-2 text-[var(--text-secondary)] font-mono">{row.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
