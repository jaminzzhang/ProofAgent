export type TaskPhase = 'active' | 'waiting_for_input' | 'paused' | 'complete' | 'failed' | 'cancelled'
export type TaskScalar = string | number | boolean
export interface TaskCriterion {
  criterion_id: string
  description: string
  required: boolean
  verifier: 'source_support' | 'verified_tool' | 'answer_coverage' | 'grounded_analysis'
  query?: string | null
  expected_text?: string | null
  tool_step_id?: string | null
}
export interface TaskGoal {
  task_id: string
  revision: number
  objective: string
  source_input_ref: string
  acceptance_criteria: TaskCriterion[]
  constraints: string[]
  required_context: string[]
}
export interface TaskQuestionField {
  name: string
  label: string
  value_type: 'string' | 'integer' | 'number' | 'boolean'
  required: boolean
  choices: string[]
  max_length: number
}
export interface TaskQuestion {
  status: 'pending' | 'answered' | 'expired' | 'superseded'
  request: {
    question_id: string
    task_id: string
    goal_revision: number
    stage: string
    fields: TaskQuestionField[]
    blocking: boolean
    affected_criteria: string[]
    expires_at: string
    dedupe_key: string
    checkpoint_ref: string
  }
  answer?: { values: Record<string, TaskScalar> } | null
}
export interface WorkflowTask {
  schema_version: 1
  goal: TaskGoal
  owner: { actor_subject: string; agent_id: string; agent_version: string }
  version: number
  phase: TaskPhase
  questions: TaskQuestion[]
  assessments: { criterion_id: string; goal_revision: number; status: 'unassessed' | 'satisfied' | 'failed'; proof_refs: string[] }[]
  budget_usage: { model_calls: number; retrieval_calls: number; tool_calls: number; tokens: number | null; unknown_model_calls?: number; active_seconds?: number }
  conversation_id?: string | null
  latest_run_id?: string | null
  created_at: string
  updated_at: string
}
export interface WorkflowTaskResponse {
  task: WorkflowTask
  run_id: string | null
  final_output?: string
  created?: boolean
  replayed?: boolean
  run_state?: import('./types').RunLifecycleState
  failure_code?: string | null
}
export interface CreateWorkflowTaskInput {
  agent_id: string
  objective: string
  acceptance_criteria?: TaskCriterion[]
  constraints?: string[]
  required_context?: string[]
  conversation_id?: string
  allow_untrusted_web_supplement?: boolean
}
