import { useState, type ReactNode } from 'react'
import { fetchValidationCapture } from '../../api/client'
import type {
  ValidationCaptureResponse,
  ValidationCaptureV2Payload,
  WorkflowStageContextApplicationProjection,
  WorkflowStageContextConfigurationCapture,
  WorkflowStagePromptValueCapture,
  WorkflowStageResultVerificationProjection,
} from '../../api/types'

interface ValidationCapturePanelProps {
  runId: string
  available: boolean
}

export function ValidationCapturePanel({ runId, available }: ValidationCapturePanelProps) {
  const [capture, setCapture] = useState<ValidationCaptureResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function loadCapture() {
    setLoading(true)
    setError(null)
    try {
      setCapture(await fetchValidationCapture(runId))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  if (!available) {
    return null
  }

  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Validation Capture
          </h4>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            validation_capture.v2 safe projection
          </p>
        </div>
        <button
          type="button"
          onClick={loadCapture}
          disabled={loading}
          className="w-fit rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
        >
          {loading ? 'Loading Capture...' : 'Load Validation Capture'}
        </button>
      </div>

      {error && <div className="mt-3 text-xs text-[var(--danger)]">{error}</div>}

      {capture && <ValidationCaptureSections payload={capture.payload} />}
    </div>
  )
}

function ValidationCaptureSections({ payload }: { payload: ValidationCaptureV2Payload }) {
  return (
    <div className="mt-4 grid gap-3">
      <CaptureSection title="Source">
        <dl className="grid gap-2 sm:grid-cols-2">
          <CaptureFact label="Run" value={payload.source.run_id} />
          <CaptureFact label="Draft" value={payload.source.draft_id ?? 'None'} />
          <CaptureFact label="Template" value={payload.source.template_name} />
          <CaptureFact
            label="Descriptor"
            value={payload.source.template_descriptor_version}
          />
          <CaptureFact label="Source Type" value={payload.source.stage_configuration_source_type} />
          <CaptureFact
            label="Effective Ref"
            value={payload.source.effective_stage_configuration_ref ?? 'None'}
          />
        </dl>
      </CaptureSection>

      <CaptureSection title="Stage Prompt Values">
        <StagePromptValues values={payload.stage_prompt_values} />
      </CaptureSection>

      <CaptureSection title="Context Configuration">
        <ContextConfiguration values={payload.context_configuration} />
      </CaptureSection>

      <CaptureSection title="Context Applications">
        <ContextApplications values={payload.context_applications} />
      </CaptureSection>

      <CaptureSection title="Stage Results">
        <StageResults values={payload.stage_results} />
      </CaptureSection>

      <CaptureSection title="Result Summary">
        <dl className="grid gap-2 sm:grid-cols-3">
          <CaptureFact label="Outcome" value={payload.result_summary.outcome} />
          <CaptureFact
            label="Output Length"
            value={String(payload.result_summary.final_output_length)}
          />
          <CaptureFact label="Fact Refs" value={String(payload.result_summary.fact_refs.length)} />
        </dl>
      </CaptureSection>

      <CaptureSection title="Exclusions">
        <dl className="grid gap-2 sm:grid-cols-2">
          <CaptureFact
            label="Categories"
            value={
              payload.exclusions.excluded_categories.length > 0
                ? payload.exclusions.excluded_categories.join(', ')
                : 'None'
            }
          />
          <CaptureFact label="Sanitizer" value={payload.exclusions.sanitizer_version} />
          <CaptureFact
            label="Redacted Secrets"
            value={String(payload.exclusions.redacted_secret_count)}
          />
          <CaptureFact
            label="Dropped Unsafe Keys"
            value={String(payload.exclusions.dropped_unsafe_key_count)}
          />
        </dl>
      </CaptureSection>
    </div>
  )
}

function CaptureSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-3">
      <h5 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">
        {title}
      </h5>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function CaptureFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </dt>
      <dd className="mt-1 truncate font-mono text-xs text-[var(--text-primary)]" title={value}>
        {value}
      </dd>
    </div>
  )
}

function StagePromptValues({ values }: { values: WorkflowStagePromptValueCapture[] }) {
  if (values.length === 0) return <EmptySection />
  return (
    <div className="space-y-2">
      {values.map((item) => (
        <div key={item.stage_id} className="grid gap-2 text-xs sm:grid-cols-[120px_minmax(0,1fr)]">
          <span className="font-mono text-[var(--text-primary)]">{item.stage_id}</span>
          <span className="text-[var(--text-muted)]">
            {item.prompt_field_names.length} fields, {item.prompt_character_count} chars
          </span>
        </div>
      ))}
    </div>
  )
}

function ContextConfiguration({
  values,
}: {
  values: WorkflowStageContextConfigurationCapture[]
}) {
  if (values.length === 0) return <EmptySection />
  return (
    <div className="space-y-2">
      {values.map((item) => (
        <div key={item.stage_id} className="grid gap-2 text-xs sm:grid-cols-[120px_minmax(0,1fr)]">
          <span className="font-mono text-[var(--text-primary)]">{item.stage_id}</span>
          <span className="text-[var(--text-muted)]">
            {item.selected_context_options.length} selected of {item.available_context_options.length}
          </span>
        </div>
      ))}
    </div>
  )
}

function ContextApplications({
  values,
}: {
  values: WorkflowStageContextApplicationProjection[]
}) {
  if (values.length === 0) return <EmptySection />
  return (
    <div className="space-y-2">
      {values.map((item) => (
        <div key={item.stage_id} className="grid gap-2 text-xs sm:grid-cols-[120px_minmax(0,1fr)]">
          <span className="font-mono text-[var(--text-primary)]">{item.stage_id}</span>
          <span className="text-[var(--text-muted)]">
            {Object.keys(item.summary).length} safe summary fields
          </span>
        </div>
      ))}
    </div>
  )
}

function StageResults({ values }: { values: WorkflowStageResultVerificationProjection[] }) {
  if (values.length === 0) return <EmptySection />
  return (
    <div className="space-y-2">
      {values.map((item) => (
        <div key={item.stage_id} className="grid gap-2 text-xs sm:grid-cols-[120px_minmax(0,1fr)]">
          <span className="font-mono text-[var(--text-primary)]">{item.stage_id}</span>
          <span className="text-[var(--text-muted)]">
            {item.status}
            {item.outcome ? ` / ${item.outcome}` : ''}, {item.produced_fact_refs.length} facts
          </span>
        </div>
      ))}
    </div>
  )
}

function EmptySection() {
  return <p className="text-xs text-[var(--text-muted)]">None</p>
}
