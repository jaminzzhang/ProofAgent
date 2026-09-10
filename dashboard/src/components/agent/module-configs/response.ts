export const RESPONSE_FIELDS = [
  {
    label: '澄清程度',
    path: ['response', 'clarification_level'],
    input: 'select' as const,
    options: ['minimal', 'balanced', 'thorough'],
    optionLabels: { minimal: '少澄清', balanced: '均衡（默认）', thorough: '详细澄清' },
    defaultValue: 'balanced',
    description: '少澄清：优先广泛查询；均衡：说明合理默认范围后继续；详细澄清：先确认影响答案侧重的偏好。身份、权限和规则适用条件始终需要明确。',
  },
  {
    label: 'Include Reasoning Summary',
    path: ['response', 'include_reasoning_summary'],
    input: 'switch' as const,
    description: 'Controls whether the response detail exposes a concise reasoning summary for audit review.',
  },
  {
    label: 'Include Review Results',
    path: ['response', 'include_review_results'],
    input: 'switch' as const,
    description: 'Controls whether reviewer findings and validation outcomes are included with the response detail.',
  },
]
