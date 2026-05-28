export const MODEL_FIELDS = [
  { label: 'Answer Model Provider', path: ['model', 'provider'], input: 'select' as const, options: ['deterministic', 'openai', 'anthropic', 'azure'], description: 'Provider for final answer generation' },
  { label: 'Answer Model Name', path: ['model', 'name'], input: 'text' as const, description: 'Model identifier for final answers' },
  { label: 'Max ReAct Steps', path: ['react', 'max_steps'], input: 'number' as const, description: 'Maximum planning and action steps per run' },
  { label: 'Max Tool Calls', path: ['react', 'max_tool_calls'], input: 'number' as const, description: 'Maximum governed tool calls per run' },
  { label: 'Record Reasoning', path: ['react', 'record_reasoning_summary'], input: 'select' as const, options: ['true', 'false'], description: 'Record structured reasoning summary' },
  { label: 'Planner Provider', path: ['react', 'planner', 'provider'], input: 'select' as const, options: ['deterministic', 'openai', 'anthropic'], description: 'Provider for ReAct planner' },
  { label: 'Planner Model', path: ['react', 'planner', 'name'], input: 'text' as const, description: 'Model name for ReAct planner' },
  { label: 'Review Mode', path: ['review', 'mode'], input: 'select' as const, options: ['auto', 'manual'], description: 'Harness review mode' },
  { label: 'Reviewer Provider', path: ['review', 'subagent', 'provider'], input: 'select' as const, options: ['deterministic', 'openai', 'anthropic'], description: 'Provider for review subagent' },
  { label: 'Reviewer Model', path: ['review', 'subagent', 'name'], input: 'text' as const, description: 'Model name for review subagent' },
  { label: 'Review Timeout (s)', path: ['review', 'subagent', 'timeout_seconds'], input: 'number' as const },
  { label: 'Review Fail Closed', path: ['review', 'subagent', 'fail_closed'], input: 'select' as const, options: ['true', 'false'] },
]
