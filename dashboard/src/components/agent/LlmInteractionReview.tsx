import { CodeBlock, CopyButton } from '@proofagent/ui'
import type { WorkflowStageLlmInteractionCapture } from '../../api/types'

interface LlmInteractionReviewProps {
  interactions: WorkflowStageLlmInteractionCapture[]
}

/**
 * LLM Interaction Message View — renders each Workflow Stage LLM Interaction
 * Capture's request messages as role-headed cards (verbatim content) plus the
 * response as a JSON block, so an operator can inspect the exact context sent
 * to and returned from the model without a raw JSON dump. See ADR-0044.
 */
export function LlmInteractionReview({ interactions }: LlmInteractionReviewProps) {
  if (interactions.length === 0) {
    return <p className="text-xs text-[var(--text-muted)]">Not recorded</p>
  }

  return (
    <div className="grid gap-3">
      {interactions.map((interaction, index) => {
        const recovered = isRecoveredInteraction(interactions, interaction, index)
        return (
          <div key={`${interaction.role}-${index}`} className="grid gap-2">
            <dl className="grid gap-2 sm:grid-cols-2">
              <CaptureFact label="Role" value={interaction.role} />
              <CaptureFact label="Model" value={`${interaction.provider}/${interaction.model}`} />
            </dl>
            <div className="grid gap-2">
              {messagesOf(interaction).map((message, messageIndex) => (
                <MessageCard
                  key={`${messageIndex}-${message.role}`}
                  message={message}
                />
              ))}
            </div>
            {interaction.response_json !== null && interaction.response_json !== undefined && (
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Response
                </div>
                <CodeBlock className="mt-1 max-h-64">
                  {stringifyValue(interaction.response_json)}
                </CodeBlock>
              </div>
            )}
            {interaction.response_json_parse_error_code && (
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Response
                </div>
                <p className={`mt-1 text-xs ${recovered ? 'text-[var(--text-muted)]' : 'text-[var(--danger-fg)]'}`}>
                  {recovered
                    ? 'Recovered after retry.'
                    : responseDiagnosticCopy(interaction.response_json_parse_error_code)}
                </p>
                <p className="mt-1 font-mono text-[10px] text-[var(--text-muted)]">
                  {interaction.response_json_parse_error_code}
                  {interaction.response_content_length
                    ? ` · ${interaction.response_content_length} chars received`
                    : ''}
                </p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

interface RequestMessage {
  role?: unknown
  content?: unknown
}

function messagesOf(interaction: WorkflowStageLlmInteractionCapture): RequestMessage[] {
  const messages = interaction.request_json?.messages
  return Array.isArray(messages) ? (messages as RequestMessage[]) : []
}

function isRecoveredInteraction(
  interactions: WorkflowStageLlmInteractionCapture[],
  interaction: WorkflowStageLlmInteractionCapture,
  index: number,
): boolean {
  if (!interaction.response_json_parse_error_code) return false
  return interactions.some((candidate, candidateIndex) => (
    candidateIndex > index
    && candidate.stage_id === interaction.stage_id
    && candidate.role === interaction.role
    && !candidate.response_json_parse_error_code
    && candidate.response_json !== null
    && candidate.response_json !== undefined
  ))
}

function MessageCard({ message }: { message: RequestMessage }) {
  const role = typeof message.role === 'string' ? message.role : 'message'
  const content = typeof message.content === 'string' ? message.content : stringifyValue(message.content)
  const charCount = content.length

  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          {role}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[var(--text-muted)]">{charCount} chars</span>
          {content.length > 0 && (
            <CopyButton value={content} label={`Copy ${role} message`} size={12} />
          )}
        </div>
      </div>
      <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-[var(--text-primary)]">
        {content}
      </pre>
    </div>
  )
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

// Mirrors the human-readable copy in ValidationCapturePanel.diagnosticCopy so
// the message view and the failure-diagnostics block use one voice. Kept local
// rather than shared to avoid coupling these two independent surfaces.
function responseDiagnosticCopy(errorCode: string): string {
  if (errorCode === 'model_output_contract_validation_failed') {
    return 'Model response did not match the required contract.'
  }
  if (errorCode === 'model_output_json_parse_failed') {
    return 'Model response did not contain a valid JSON object.'
  }
  if (errorCode === 'model_output_json_not_object') {
    return 'Model response JSON was not an object.'
  }
  if (errorCode === 'model_output_too_large') {
    return 'Model response exceeded the normalization size limit.'
  }
  if (errorCode === 'model_output_too_deep') {
    return 'Model response exceeded the normalization depth limit.'
  }
  return 'Stage stopped with a safe diagnostic code.'
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
