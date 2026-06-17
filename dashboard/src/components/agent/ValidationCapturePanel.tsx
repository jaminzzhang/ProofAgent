import { useState, type ReactNode } from 'react'
import { fetchValidationCapture } from '../../api/client'
import type {
  ValidationCaptureResponse,
  ValidationCaptureV2Payload,
  WorkflowStageContextApplicationProjection,
  WorkflowStageContextConfigurationCapture,
  WorkflowStageFailureDiagnosticProjection,
  WorkflowStageLlmInteractionCapture,
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
  const stages = stageReviewItems(payload)
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

      <CaptureSection title="Stage Review">
        <div className="grid gap-3">
          {stages.map((stage) => (
            <StageReviewCard
              key={stage.stageId}
              stage={stage}
              legacyDiagnostics={payload.failure_diagnostics === undefined}
            />
          ))}
        </div>
      </CaptureSection>

      <CaptureSection title="Result Summary">
        <dl className="grid gap-2 sm:grid-cols-4">
          <CaptureFact label="Outcome" value={payload.result_summary.outcome} />
          <CaptureFact
            label="Output Length"
            value={String(payload.result_summary.final_output_length)}
          />
          <CaptureFact label="Fact Refs" value={String(payload.result_summary.fact_refs.length)} />
          <CaptureFact
            label="Approval Pause"
            value={payload.result_summary.approval_pause ? 'Present' : 'None'}
          />
        </dl>
        {payload.result_summary.final_output && (
          <pre className="mt-3 whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 text-xs text-[var(--text-primary)]">
            {payload.result_summary.final_output}
          </pre>
        )}
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

interface StageReview {
  stageId: string
  label: string
  prompt?: WorkflowStagePromptValueCapture
  contextConfig?: WorkflowStageContextConfigurationCapture
  contextApplication?: WorkflowStageContextApplicationProjection
  result?: WorkflowStageResultVerificationProjection
  diagnostics: WorkflowStageFailureDiagnosticProjection[]
  llmInteractions: WorkflowStageLlmInteractionCapture[]
}

function stageReviewItems(payload: ValidationCaptureV2Payload): StageReview[] {
  const order: string[] = []
  const items = new Map<string, StageReview>()
  const ensure = (stageId: string, label?: string | null) => {
    if (!items.has(stageId)) {
      order.push(stageId)
      items.set(stageId, {
        stageId,
        label: label || stageId,
        diagnostics: [],
        llmInteractions: [],
      })
    }
    const item = items.get(stageId)!
    if (label && item.label === item.stageId) item.label = label
    return item
  }

  payload.stage_prompt_values.forEach((prompt) => {
    ensure(prompt.stage_id, prompt.stage_label).prompt = prompt
  })
  payload.context_configuration.forEach((config) => {
    ensure(config.stage_id, config.stage_label).contextConfig = config
  })
  payload.context_applications.forEach((application) => {
    ensure(application.stage_id, application.stage_label).contextApplication = application
  })
  payload.stage_results.forEach((result) => {
    ensure(result.stage_id, result.stage_label).result = result
  })
  ;(payload.failure_diagnostics ?? []).forEach((diagnostic) => {
    ensure(diagnostic.stage_id, diagnostic.stage_label).diagnostics.push(diagnostic)
  })
  ;(payload.llm_interactions ?? []).forEach((interaction) => {
    ensure(interaction.stage_id, interaction.stage_label).llmInteractions.push(interaction)
  })

  return order.map((stageId) => items.get(stageId)!)
}

function StageReviewCard({
  stage,
  legacyDiagnostics,
}: {
  stage: StageReview
  legacyDiagnostics: boolean
}) {
  const status = stage.result?.status ?? 'not reached'
  const isBlocked = stage.result?.status === 'blocked' || stage.diagnostics.length > 0
  return (
    <article
      className={`rounded-md border p-3 ${
        isBlocked
          ? 'border-[var(--danger)] bg-[var(--danger-bg)]'
          : 'border-[var(--border)] bg-[var(--bg-base)]'
      }`}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h6 className="text-sm font-semibold text-[var(--text-primary)]">{stage.label}</h6>
          <p className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">{stage.stageId}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 font-mono text-[var(--text-primary)]">
            {status}
          </span>
          {stage.result?.outcome && (
            <span className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 font-mono text-[var(--text-primary)]">
              {stage.result.outcome}
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <StagePromptReview prompt={stage.prompt} />
        <StageContextReview
          config={stage.contextConfig}
          application={stage.contextApplication}
        />
        <StageResultReview result={stage.result} />
        <StageLlmInteractionReview interactions={stage.llmInteractions} />
        <StageFailureDiagnostics
          diagnostics={stage.diagnostics}
          legacyDiagnostics={legacyDiagnostics}
          blocked={stage.result?.status === 'blocked'}
        />
      </div>
    </article>
  )
}

function ReviewBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-3">
      <h6 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h6>
      <div className="mt-2">{children}</div>
    </div>
  )
}

function StagePromptReview({ prompt }: { prompt?: WorkflowStagePromptValueCapture }) {
  if (!prompt) {
    return (
      <ReviewBlock title="Prompt Values">
        <p className="text-xs text-[var(--text-muted)]">No prompt values configured.</p>
      </ReviewBlock>
    )
  }
  return (
    <ReviewBlock title="Prompt Values">
      <p className="text-xs text-[var(--text-muted)]">
        {prompt.prompt_field_names.length} fields, {prompt.prompt_character_count} chars
      </p>
      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-medium text-[var(--text-primary)]">
          Reveal Prompt Values
        </summary>
        <div className="mt-2 grid gap-2">
          {orderedPromptEntries(prompt).map(([key, value]) => (
            <div key={key}>
              <div className="font-mono text-[11px] text-[var(--text-muted)]">{key}</div>
              <PromptValue value={value} />
            </div>
          ))}
        </div>
      </details>
    </ReviewBlock>
  )
}

function orderedPromptEntries(prompt: WorkflowStagePromptValueCapture) {
  const seen = new Set<string>()
  const entries: Array<[string, unknown]> = []
  prompt.prompt_field_names.forEach((key) => {
    if (key in prompt.prompt_values) {
      seen.add(key)
      entries.push([key, prompt.prompt_values[key]])
    }
  })
  Object.entries(prompt.prompt_values).forEach(([key, value]) => {
    if (!seen.has(key)) entries.push([key, value])
  })
  return entries
}

function PromptValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <p className="text-xs text-[var(--text-muted)]">None</p>
    return (
      <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-[var(--text-primary)]">
        {value.map((item, index) => (
          <li key={index}>{String(item)}</li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object' && value !== null) {
    return <SafeJson value={value} />
  }
  return (
    <p className="mt-1 whitespace-pre-wrap text-xs text-[var(--text-primary)]">
      {String(value ?? '') || 'None'}
    </p>
  )
}

function StageContextReview({
  config,
  application,
}: {
  config?: WorkflowStageContextConfigurationCapture
  application?: WorkflowStageContextApplicationProjection
}) {
  return (
    <ReviewBlock title="Context">
      <div className="grid gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Configured Context
          </div>
          {config ? (
            <p className="mt-1 text-xs text-[var(--text-primary)]">
              {config.selected_context_options.length} selected of{' '}
              {config.available_context_options.length}: {config.selected_context_options.join(', ') || 'None'}
            </p>
          ) : (
            <p className="mt-1 text-xs text-[var(--text-muted)]">No configured context.</p>
          )}
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Applied Context
          </div>
          {application ? (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs font-medium text-[var(--text-primary)]">
                {Object.keys(application.summary).length} safe summary fields
              </summary>
              <SafeJson value={application.summary} />
            </details>
          ) : (
            <p className="mt-1 text-xs text-[var(--text-muted)]">Not executed</p>
          )}
        </div>
      </div>
    </ReviewBlock>
  )
}

function StageResultReview({ result }: { result?: WorkflowStageResultVerificationProjection }) {
  if (!result) {
    return (
      <ReviewBlock title="Stage Result">
        <p className="text-xs text-[var(--text-muted)]">Not reached</p>
      </ReviewBlock>
    )
  }
  return (
    <ReviewBlock title="Stage Result">
      <dl className="grid gap-2 sm:grid-cols-2">
        <CaptureFact label="Status" value={result.status} />
        <CaptureFact label="Outcome" value={result.outcome ?? 'None'} />
        <CaptureFact label="Facts" value={String(result.produced_fact_refs.length)} />
        {Object.entries(result.summary).slice(0, 4).map(([key, value]) => (
          <CaptureFact key={key} label={key} value={compactValue(value)} />
        ))}
      </dl>
      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-medium text-[var(--text-primary)]">
          Show Safe Summary JSON
        </summary>
        <SafeJson value={result.summary} />
      </details>
    </ReviewBlock>
  )
}

function StageLlmInteractionReview({
  interactions,
}: {
  interactions: WorkflowStageLlmInteractionCapture[]
}) {
  return (
    <ReviewBlock title="LLM Input/Output JSON">
      {interactions.length > 0 ? (
        <div className="grid gap-3">
          {interactions.map((interaction, index) => (
            <div key={`${interaction.role}-${index}`} className="grid gap-2">
              <dl className="grid gap-2 sm:grid-cols-2">
                <CaptureFact label="Role" value={interaction.role} />
                <CaptureFact label="Model" value={`${interaction.provider}/${interaction.model}`} />
                <CaptureFact
                  label="Output Length"
                  value={String(interaction.response_content_length)}
                />
                <CaptureFact
                  label="Parse Error"
                  value={interaction.response_json_parse_error_code ?? 'None'}
                />
              </dl>
              <details>
                <summary className="cursor-pointer text-xs font-medium text-[var(--text-primary)]">
                  Reveal LLM Request JSON
                </summary>
                <SafeJson value={interaction.request_json} />
              </details>
              <details>
                <summary className="cursor-pointer text-xs font-medium text-[var(--text-primary)]">
                  Reveal LLM Response JSON
                </summary>
                <SafeJson value={interaction.response_json ?? { unavailable: true }} />
              </details>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-[var(--text-muted)]">Not recorded</p>
      )}
    </ReviewBlock>
  )
}

function StageFailureDiagnostics({
  diagnostics,
  legacyDiagnostics,
  blocked,
}: {
  diagnostics: WorkflowStageFailureDiagnosticProjection[]
  legacyDiagnostics: boolean
  blocked: boolean
}) {
  return (
    <ReviewBlock title="Failure Diagnostic">
      {diagnostics.length > 0 ? (
        <div className="grid gap-3">
          {diagnostics.map((diagnostic, index) => (
            <div key={`${diagnostic.related_event_id ?? diagnostic.error_code}-${index}`}>
              <p className="text-xs font-medium text-[var(--text-primary)]">
                {diagnosticCopy(diagnostic)}
              </p>
              <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                <CaptureFact label="Error Code" value={diagnostic.error_code} />
                <CaptureFact label="Role" value={diagnostic.role ?? 'None'} />
                <CaptureFact label="Event" value={diagnostic.related_event_id ?? 'None'} />
                <CaptureFact
                  label="Raw Length"
                  value={String(diagnostic.raw_content_length ?? 0)}
                />
                {diagnostic.contract_name && (
                  <CaptureFact label="Contract" value={diagnostic.contract_name} />
                )}
                {diagnostic.violation_count !== undefined && (
                  <CaptureFact label="Violations" value={String(diagnostic.violation_count)} />
                )}
              </dl>
              {(diagnostic.field_paths?.length || diagnostic.violation_codes?.length) && (
                <p className="mt-2 text-xs text-[var(--text-muted)]">
                  Fields: {diagnostic.field_paths?.join(', ') || 'None'}; Codes:{' '}
                  {diagnostic.violation_codes?.join(', ') || 'None'}
                </p>
              )}
            </div>
          ))}
        </div>
      ) : legacyDiagnostics && blocked ? (
        <p className="text-xs text-[var(--text-muted)]">
          Diagnostics not recorded for this capture. Rerun validation with Full stage capture to collect diagnostics.
        </p>
      ) : (
        <p className="text-xs text-[var(--text-muted)]">None</p>
      )}
    </ReviewBlock>
  )
}

function diagnosticCopy(diagnostic: WorkflowStageFailureDiagnosticProjection) {
  if (diagnostic.error_code === 'model_output_contract_validation_failed') {
    return 'Model response did not match the required contract.'
  }
  if (diagnostic.error_code === 'model_output_json_parse_failed') {
    return 'Model response did not contain a valid JSON object.'
  }
  if (diagnostic.error_code === 'model_output_json_not_object') {
    return 'Model response JSON was not an object.'
  }
  if (diagnostic.error_code === 'model_output_too_large') {
    return 'Model response exceeded the normalization size limit.'
  }
  if (diagnostic.error_code === 'model_output_too_deep') {
    return 'Model response exceeded the normalization depth limit.'
  }
  return 'Stage stopped with a safe diagnostic code.'
}

function SafeJson({ value }: { value: unknown }) {
  return (
    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-2 font-mono text-[11px] text-[var(--text-primary)]">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function compactValue(value: unknown) {
  if (value === null || value === undefined || value === '') return 'None'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (Array.isArray(value)) return `${value.length} items`
  return `${Object.keys(value as Record<string, unknown>).length} fields`
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
