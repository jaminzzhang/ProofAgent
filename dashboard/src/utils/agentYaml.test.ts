import { describe, expect, it } from 'vitest'
import {
  readWorkflowStageConfigs,
  readWorkflowTemplateDescriptorVersion,
  replaceAgentContextConfiguration,
  replaceAgentYamlMapping,
  replaceMemoryCapabilityConfiguration,
  replaceToolCapabilityConfiguration,
  replaceWorkflowStages,
  updateAgentYamlField,
} from './agentYaml'

const AGENT_YAML = `name: insurance_customer_service
purpose: "Provide customer service."

capabilities:
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: true
        retention_days: 30
        max_records: 5
        allow_restricted: false
      user:
        enabled: false
      shared:
        enabled: false
`

describe('agentYaml', () => {
  it('updates deeply nested memory scope scalars', () => {
    const updated = updateAgentYamlField(
      AGENT_YAML,
      ['capabilities', 'memory', 'scopes', 'case', 'retention_days'],
      '45',
    )

    expect(updated).toContain('        retention_days: 45')
    expect(updated).toContain('        max_records: 5')
  })

  it('writes only an explicit context budget override from Agent Context controls', () => {
    const updated = replaceAgentContextConfiguration(
      AGENT_YAML,
      ['context', 'budget_profile', 'max_tokens'],
      '4096',
    )

    expect(updated).toContain(`context:
  budget_profile:
    max_tokens: 4096
    reserved_output_tokens: 0
    estimation_strategy: heuristic
    profile_version: context_budget.v1`)
    expect(updated).not.toContain('convergence:')
    expect(updated).not.toContain('dynamic_calibration:')
  })

  it('preserves existing context siblings when writing Agent Context controls', () => {
    const updated = replaceAgentContextConfiguration(
      `name: insurance
context:
  source_policies:
    conversation:
      max_turns: 6
`,
      ['context', 'budget_profile', 'max_tokens'],
      '4096',
    )

    expect(updated).toContain(`conversation:
      max_turns: 6`)
    expect(updated).toContain('max_tokens: 4096')
  })

  it('does not materialize an explicit budget profile when editing memory recall policy', () => {
    const updated = replaceAgentContextConfiguration(
      AGENT_YAML,
      ['context', 'source_policies', 'memory_recall', 'scopes', 'case', 'enabled'],
      'false',
    )

    expect(updated).toContain(`context:
  source_policies:
    memory_recall:
      scopes:
        case:
          enabled: false
        user:
          enabled: false
        shared:
          enabled: false`)
    expect(updated).not.toContain('budget_profile:')
  })

  it('does not materialize an explicit budget profile when a blank budget value is submitted without an existing budget', () => {
    const updated = replaceAgentContextConfiguration(
      AGENT_YAML,
      ['context', 'budget_profile', 'max_tokens'],
      '',
    )

    expect(updated).not.toContain('budget_profile:')
  })

  it('preserves unrelated top-level context siblings when writing Agent Context controls', () => {
    const updated = replaceAgentContextConfiguration(
      `name: insurance
context:
  custom_runtime_policy:
    mode: strict
  source_policies:
    conversation:
      max_turns: 6
`,
      ['context', 'budget_profile', 'max_tokens'],
      '4096',
    )

    expect(updated).toContain(`custom_runtime_policy:
    mode: strict`)
    expect(updated).toContain(`conversation:
      max_turns: 6`)
    expect(updated).toContain('max_tokens: 4096')
  })

  it('creates canonical memory configuration and strips legacy top-level memory', () => {
    const updated = replaceMemoryCapabilityConfiguration(
      `name: insurance
memory:
  provider: local
policy:
  file: ./policy.yaml
`,
      ['capabilities', 'memory', 'provider'],
      'session',
    )

    expect(updated).toContain(`capabilities:
  memory:
    enabled: true
    provider: session
    scopes:
      case:
        enabled: false
        retention_days: 30
        max_records: 5
        allow_restricted: false
      user:
        enabled: false
        retention_days: 30
        max_records: 5
        allow_restricted: false
      shared:
        enabled: false`)
    expect(updated).not.toContain('\nmemory:\n')
    expect(updated).toContain(`policy:
  file: ./policy.yaml`)
  })

  it('writes minimal memory configuration when memory is disabled', () => {
    const updated = replaceMemoryCapabilityConfiguration(
      AGENT_YAML,
      ['capabilities', 'memory', 'enabled'],
      'false',
    )

    expect(updated).toContain(`capabilities:
  memory:
    enabled: false`)
    expect(updated).not.toContain('provider: local')
    expect(updated).not.toContain('scopes:')
  })

  it('materializes user memory scope defaults when User Memory is enabled', () => {
    const updated = replaceMemoryCapabilityConfiguration(
      AGENT_YAML,
      ['capabilities', 'memory', 'scopes', 'user', 'enabled'],
      'true',
    )

    expect(updated).toContain(`user:
        enabled: true
        retention_days: 30
        max_records: 5
        allow_restricted: false`)
  })

  it('inserts missing nested model params under an existing parent section', () => {
    const updated = updateAgentYamlField(
      `name: model_test
model:
  provider: deepseek
  name: deepseek-v4-flash
policy:
  file: ./policy.yaml
`,
      ['model', 'params', 'api_key_env'],
      'DEEPSEEK_API_KEY',
    )

    expect(updated).toContain(`model:
  provider: deepseek
  name: deepseek-v4-flash
  params:
    api_key_env: DEEPSEEK_API_KEY
policy:`)
  })

  it('inserts an optional top-level configuration section when it is absent', () => {
    const updated = updateAgentYamlField(
      `name: response_test
policy:
  file: ./policy.yaml
`,
      ['response', 'include_review_results'],
      'true',
    )

    expect(updated).toContain(`response:
  include_review_results: true`)
  })

  it('writes canonical Tool Capability configuration and removes the retired top-level section', () => {
    const updated = replaceToolCapabilityConfiguration(
      `name: tools_test
tools:
  file: ./legacy-tools.yaml
capabilities:
  tools:
    enabled: false
`,
      ['capabilities', 'tools', 'file'],
      './tools.yaml',
    )

    expect(updated).toContain(`capabilities:
  tools:
    enabled: true
    file: ./tools.yaml`)
    expect(updated).not.toContain('\ntools:\n')
  })

  it('replaces one mapping block without preserving stale sibling keys', () => {
    const updated = replaceAgentYamlMapping(
      `name: model_test
model:
  provider: deepseek
  name: deepseek-chat
  params:
    temperature: 0
    timeout_seconds: 30
policy:
  file: ./policy.yaml
`,
      ['model'],
      {
        model_source: 'shared',
        connection_id: 'model_deepseek_default',
        params: {
          temperature: '0',
          timeout_seconds: '5',
        },
      },
    )

    expect(updated).toContain(`model:
  model_source: shared
  connection_id: model_deepseek_default
  params:
    temperature: 0
    timeout_seconds: 5
policy:`)
    expect(updated).not.toContain('provider: deepseek')
    expect(updated).not.toContain('name: deepseek-chat')
  })

  it('replaces workflow stage arrays while preserving core workflow settings', () => {
    const updated = replaceWorkflowStages(
      `name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    type: memory
  stages:
    - id: plan
      prompt:
        business_context: "Old context"
policy:
  file: ./policy.yaml
`,
      'react_enterprise_qa.v1',
      [
        {
          id: 'plan',
          prompt: {
            business_context: 'Claims context',
            task_instructions: ['Prefer retrieval first.'],
            output_preferences: ['Keep concise.'],
          },
          context: {
            include_agent_purpose: true,
            include_bound_tools: false,
          },
        },
      ],
    )

    expect(updated).toContain(`workflow:
  template_descriptor_version: react_enterprise_qa.v1
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    type: memory
  stages:
    - id: plan
      prompt:
        business_context: "Claims context"
        task_instructions:
          - "Prefer retrieval first."
        output_preferences:
          - "Keep concise."
      context:
        include_agent_purpose: true
policy:`)
    expect(updated).not.toContain('Old context')
    expect(readWorkflowTemplateDescriptorVersion(updated)).toBe('react_enterprise_qa.v1')
    expect(readWorkflowStageConfigs(updated)).toEqual([
      {
        id: 'plan',
        prompt: {
          business_context: 'Claims context',
          task_instructions: ['Prefer retrieval first.'],
          output_preferences: ['Keep concise.'],
        },
        context: {
          include_agent_purpose: true,
        },
      },
    ])
  })

  it('reads workflow stages from PyYAML sequence indentation returned by the API', () => {
    const stages = readWorkflowStageConfigs(`name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  template_descriptor_version: react_enterprise_qa.v1
  stages:
  - id: plan
    prompt:
      business_context: "Claims context"
      task_instructions:
      - "Prefer retrieval first."
      output_preferences:
      - "Keep concise."
    context:
      include_agent_purpose: true
policy:
  file: ./policy.yaml
`)

    expect(stages).toEqual([
      {
        id: 'plan',
        prompt: {
          business_context: 'Claims context',
          task_instructions: ['Prefer retrieval first.'],
          output_preferences: ['Keep concise.'],
        },
        context: {
          include_agent_purpose: true,
        },
      },
    ])
  })
})

// Covers the API serializer as well as the local advanced-YAML projection.
describe('unified Workflow Prompt round trips', () => {
  it.each(['true', '123', 'null', '背景\n任务\n输出 😀', 'Quote " and path C:\\claims', '任务\n\n'])('preserves free-form text %j', (text) => {
    const stages = [{ id: 'plan', prompt: { business_context: text, task_instructions: [], output_preferences: [] }, context: {} }]
    expect(readWorkflowStageConfigs(replaceWorkflowStages('workflow:\n  template: react_enterprise_qa_v3\n', 'react_enterprise_qa.v3', stages))[0].prompt.business_context).toBe(text)
  })
  it("reads multiline YAML emitted by the backend serializer", () => {
    const stages = readWorkflowStageConfigs("workflow:\n  template: react_enterprise_qa_v3\n  stages:\n  - id: plan\n    prompt:\n      business_context: '保险服务背景\n\n\n        核对版本 \"A\"，保留路径 C:\\claims\n\n        输出简洁 😀\n\n        '\n      task_instructions:\n      - '旧指令\n\n        第二行'\n      output_preferences:\n      - 简洁\n    context:\n      include_agent_purpose: true\n")
    expect(stages[0].prompt.business_context).toBe("保险服务背景\n\n核对版本 \"A\"，保留路径 C:\\claims\n输出简洁 😀\n")
    expect(stages[0].prompt.task_instructions).toEqual(["旧指令\n第二行"])
    expect(stages[0].context).toEqual({ include_agent_purpose: true })
  })
})
