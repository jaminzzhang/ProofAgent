import type { BadgeProps } from '@proofagent/ui'

const EVENT_LABELS: Record<string, string> = {
  run_started: 'Run started',
  manifest_loaded: 'Manifest loaded',
  workflow_stage_configuration_trace_summary: 'Workflow stage configuration',
  workflow_stage_context_applied: 'Stage context applied',
  workflow_stage_result: 'Stage result',
  workflow_stage_completed: 'Stage completed',
  workflow_stage_blocked: 'Stage blocked',
  workflow_stage_waiting: 'Stage waiting',
  intent_resolution: 'Intent resolution',
  retrieval_query_set: 'Retrieval query set',
  business_flow_skill_pack_admission: 'Business flow admission',
  reasoning_summary: 'Reasoning summary',
  action_proposal: 'Action proposal',
  review_requested: 'Review requested',
  review_decision: 'Review decision',
  review_error: 'Review error',
  review_overridden: 'Review overridden',
  clarification_requested: 'Clarification requested',
  policy_decision: 'Policy decision',
  retrieval_started: 'Retrieval started',
  retrieval_plan: 'Retrieval plan',
  retrieval_step: 'Retrieval step',
  retrieval_result: 'Retrieval result',
  evidence_evaluation: 'Evidence evaluation',
  context_admission: 'Context admission',
  approval_requested: 'Approval requested',
  pending_approval_created: 'Pending approval created',
  approval_granted: 'Approval granted',
  approval_denied: 'Approval denied',
  approval_timeout: 'Approval timeout',
  customer_handoff_created: 'Customer handoff created',
  tool_request: 'Tool request',
  tool_result: 'Tool result',
  memory_read: 'Memory read',
  memory_candidate_generated: 'Memory candidate generated',
  memory_write_requested: 'Memory write requested',
  memory_write_decision: 'Memory write decision',
  memory_admission: 'Memory admission',
  memory_export_decision: 'Memory export decision',
  memory_delete_decision: 'Memory delete decision',
  model_request: 'Model request',
  model_connection_resolution: 'Model connection resolution',
  model_response: 'Model response',
  model_error: 'Model error',
  model_output_normalization_failed: 'Model output normalization failed',
  final_output: 'Final output',
  final_output_disclosure: 'Final output disclosure',
  redaction_applied: 'Redaction applied',
  artifact_written: 'Artifact written',
  run_failed: 'Run failed',
}

export function traceEventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] ?? eventType
}

export function statusVariant(status: string): BadgeProps['variant'] {
  if (status === 'ok' || status === 'completed') return 'success'
  if (status === 'waiting') return 'warning'
  if (status === 'blocked' || status === 'error') return 'danger'
  if (status === 'skipped') return 'neutral'
  return 'subtle'
}

export function stringifyTraceValue(value: unknown): string {
  if (value === undefined) return 'undefined'
  try {
    const json = JSON.stringify(value, null, 2)
    return json === undefined ? String(value) : json
  } catch {
    return String(value)
  }
}

export function formatTraceTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ts
  }
}
