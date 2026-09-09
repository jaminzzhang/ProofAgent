import type { WorkflowStagePromptConfig } from '../../api/types'

/** Preserve legacy text and ordering; editing never parses headings back into fields. */
export function mergeStagePrompt(prompt: WorkflowStagePromptConfig): string {
  return [
    prompt.business_context ?? '',
    prompt.task_instructions?.length ? `Task instructions:\n${prompt.task_instructions.map((line) => `- ${line}`).join('\n')}` : '',
    prompt.output_preferences?.length ? `Output preferences:\n${prompt.output_preferences.map((line) => `- ${line}`).join('\n')}` : '',
  ].filter(Boolean).join('\n\n')
}

/** Editable section scaffolding only; never inserts business or stage instructions. */
export const STRUCTURED_PROMPT_TEMPLATE = `# Business Context
[填写业务背景、服务对象和适用范围]

# Task Instructions
[填写本节点的任务、步骤和注意事项]

# Output Preferences
[填写输出格式、语言和表达风格]`
