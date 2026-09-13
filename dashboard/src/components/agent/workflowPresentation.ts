import type { WorkflowStageDescriptor } from '../../api/types'

// These stages consume stage context in controlled_react/composition.py.
// Keep descriptor-governed data intact; this is an editor presentation boundary.
export const PROMPT_STAGE_IDS = ['intent_resolution', 'plan', 'model_answer']
export const CONTEXT_LABELS: Record<string, string> = {
  include_agent_purpose: '助手职责',
  include_recent_conversation_summary: '近期对话摘要',
  include_bound_knowledge_sources: '已绑定的知识来源',
  include_citation_requirements: '证据引用要求',
  include_response_disclosure_policy: '回答展示设置',
}
const STAGE_NAMES: Record<string, [string, string]> = {
  intent_resolution: [
    '理解用户诉求',
    '识别用户的子问题、验收要求，以及还缺少哪些关键信息。',
  ],
  plan: ['规划下一步', '根据未完成的问题和证据缺口，决定下一步查询或回答。'],
  model_answer: [
    '生成答案',
    '按问题组织有依据的回答，检查事实与覆盖情况；缺证据返回规划，表达错误有限修复。',
  ],
  clarification: ['补充提问', '将规划阶段提出的澄清问题返回给用户。'],
  retrieval_review: [
    '检索审查',
    '由系统检查检索计划。当前运行链路未将此节点的 Prompt 注入模型。',
  ],
  retrieval: ['检索知识', '根据审查结果执行检索，并接纳可用证据。'],
  tool_review: [
    '工具审查',
    '由系统检查工具请求。当前运行链路未将此节点的 Prompt 注入模型。',
  ],
  tool: ['查询工具', '通过工具网关执行获授权的查询。工具绑定在 Tools 中配置。'],
  memory: ['处理记忆', '按记忆策略处理上下文。记忆能力在 Memory 中配置。'],
  response: ['返回结果', '将处理结果返回给用户。答案措辞在“生成答案”中调整。'],
}
export function stageName(stage: WorkflowStageDescriptor): string {
  return STAGE_NAMES[stage.id]?.[0] ?? stage.label
}
export function stageDescription(stage: WorkflowStageDescriptor): string {
  return STAGE_NAMES[stage.id]?.[1] ?? stage.description
}
export function canConfigurePrompt(stage: WorkflowStageDescriptor): boolean {
  return (
    PROMPT_STAGE_IDS.includes(stage.id) &&
    stage.editable_prompt_fields.includes('business_context')
  )
}
