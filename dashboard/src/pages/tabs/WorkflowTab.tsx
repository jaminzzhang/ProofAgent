import type { WorkflowRunProjection, WorkflowRunStageProjection } from '../../api/types'

interface WorkflowTabProps {
  projection: WorkflowRunProjection
}

export function WorkflowTab({ projection }: WorkflowTabProps) {
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <WorkflowFact label="Workflow Template" value={projection.template_name ?? 'Unknown'} />
          <WorkflowFact
            label="Descriptor"
            value={projection.template_descriptor_version ?? 'Unknown'}
          />
          <WorkflowFact
            label="Source"
            value={formatSource(projection.stage_configuration_source)}
          />
        </div>
      </section>

      {projection.stages.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 text-sm text-[var(--text-muted)]">
          No Workflow stage facts were captured for this run.
        </div>
      ) : (
        <div className="space-y-3">
          {projection.stages.map((stage) => (
            <WorkflowStageCard key={stage.stage_id} stage={stage} />
          ))}
        </div>
      )}
    </div>
  )
}

function WorkflowStageCard({ stage }: { stage: WorkflowRunStageProjection }) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
      <div className="flex flex-col gap-3 border-b border-[var(--border)] pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {stage.label ?? stage.stage_id}
          </h3>
          <div className="mt-1 font-mono text-xs text-[var(--text-muted)]">{stage.stage_id}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {stage.status && <Pill>{stage.status}</Pill>}
          {stage.outcome && <Pill>{stage.outcome}</Pill>}
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <WorkflowMap title="Stage Summary" values={stage.safe_summary} />
        <WorkflowMap title="Context Application" values={stage.context_application_summary} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <TokenList title="Produced Fact Refs" values={stage.produced_fact_refs} />
        <TokenList title="Related Trace Events" values={stage.related_event_ids} />
      </div>

      {(stage.approval_pause_summary || stage.clarification_need_summary) && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {stage.approval_pause_summary && (
            <WorkflowMap title="Approval Pause" values={stage.approval_pause_summary} />
          )}
          {stage.clarification_need_summary && (
            <WorkflowMap title="Clarification Need" values={stage.clarification_need_summary} />
          )}
        </div>
      )}
    </section>
  )
}

function WorkflowFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </div>
      <div className="mt-1 truncate font-mono text-xs text-[var(--text-primary)]" title={value}>
        {value}
      </div>
    </div>
  )
}

function WorkflowMap({ title, values }: { title: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values)
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h4>
      {entries.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">None</p>
      ) : (
        <dl className="mt-2 space-y-2">
          {entries.map(([key, value]) => (
            <div key={key} className="grid gap-1 text-xs sm:grid-cols-[140px_minmax(0,1fr)]">
              <dt className="font-mono text-[var(--text-muted)]">{key}</dt>
              <dd className="break-words text-[var(--text-primary)]">{formatValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

function TokenList({ title, values }: { title: string; values: string[] }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h4>
      {values.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">None</p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {values.map((value) => (
            <span
              key={value}
              className="rounded bg-[var(--bg-hover)] px-2 py-0.5 font-mono text-xs text-[var(--text-primary)]"
            >
              {value}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Pill({ children }: { children: string }) {
  return (
    <span className="rounded-full bg-[var(--bg-hover)] px-2 py-1 font-mono text-xs text-[var(--text-secondary)]">
      {children}
    </span>
  )
}

function formatSource(source: Record<string, unknown>) {
  const sourceType = source.source_type
  const reference = source.reference
  if (typeof sourceType === 'string' && typeof reference === 'string') {
    return `${sourceType} / ${reference}`
  }
  if (typeof sourceType === 'string') return sourceType
  if (typeof reference === 'string') return reference
  return 'Unknown'
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatValue).join(', ')
  if (value === null || value === undefined) return 'None'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
