import type { CustomerSafeSource } from '../../api/types'
import { SourceList } from './SourceList'

export type CustomerMode = 'anonymous' | 'CUST-001' | 'CUST-002'

export const CUSTOMER_MODES: Array<{ id: CustomerMode; label: string; customerId: string | null }> = [
  { id: 'anonymous', label: 'Guest', customerId: null },
  { id: 'CUST-001', label: 'Demo 1', customerId: 'CUST-001' },
  { id: 'CUST-002', label: 'Demo 2', customerId: 'CUST-002' },
]

export function CustomerSidebar({
  mode,
  onModeChange,
  turnCount,
  latestSources,
}: {
  mode: CustomerMode
  onModeChange: (mode: CustomerMode) => void
  turnCount: number
  latestSources: Array<string | CustomerSafeSource>
}) {
  const activeMode = CUSTOMER_MODES.find((item) => item.id === mode) ?? CUSTOMER_MODES[0]

  return (
    <>
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Session</h2>
        <div className="mt-3 grid grid-cols-1 rounded-lg border border-[var(--border)] bg-[var(--bg-hover)] p-1">
          {CUSTOMER_MODES.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onModeChange(item.id)}
              className={`min-w-0 rounded-md px-2 py-2 text-xs font-semibold transition ${
                mode === item.id
                  ? 'bg-[var(--bg-surface)] text-[var(--accent)] shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-[var(--text-secondary)]">Customer</dt>
            <dd className="min-w-0 break-all text-right font-medium text-[var(--text-primary)]">
              {activeMode.customerId ?? 'Anonymous'}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-[var(--text-secondary)]">Agent</dt>
            <dd className="min-w-0 break-all text-right font-medium text-[var(--text-primary)]">
              insurance_customer_service
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-[var(--text-secondary)]">Turns</dt>
            <dd className="min-w-0 break-all text-right font-medium text-[var(--text-primary)]">{turnCount}</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Recent Sources</h2>
        <div className="mt-3">
          <SourceList sources={latestSources} />
          {latestSources.length === 0 && (
            <p className="text-sm text-[var(--text-secondary)]">No sources yet</p>
          )}
        </div>
      </div>
    </>
  )
}
