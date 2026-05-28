import { describe, expect, it } from 'vitest'
import { KNOWLEDGE_FIELDS } from './knowledge'
import { MEMORY_FIELDS } from './memory'
import { MODEL_FIELDS } from './model'
import { WORKFLOW_FIELDS } from './workflow'

function optionsFor(fields: readonly { label: string; options?: readonly string[] }[], label: string): readonly string[] {
  const field = fields.find((candidate) => candidate.label === label)
  if (!field?.options) throw new Error(`Missing select options for ${label}`)
  return field.options
}

describe('module configuration field options', () => {
  it('uses backend-supported knowledge and retrieval values', () => {
    expect(optionsFor(KNOWLEDGE_FIELDS, 'Knowledge Provider')).toEqual([
      'local_markdown',
      'local_vector',
      'pageindex',
      'remote_search',
    ])
    expect(optionsFor(KNOWLEDGE_FIELDS, 'Retrieval Strategy')).toEqual([
      'single_step',
      'agentic',
    ])
  })

  it('uses backend-supported workflow, model, review, and memory values', () => {
    const modelProviders = ['deterministic', 'openai_compatible', 'azure_openai', 'anthropic']

    expect(optionsFor(WORKFLOW_FIELDS, 'Checkpointer Provider')).toEqual(['sqlite'])
    expect(optionsFor(MODEL_FIELDS, 'Answer Model Provider')).toEqual(modelProviders)
    expect(optionsFor(MODEL_FIELDS, 'Planner Provider')).toEqual(modelProviders)
    expect(optionsFor(MODEL_FIELDS, 'Review Mode')).toEqual(['rules_only', 'auto'])
    expect(optionsFor(MODEL_FIELDS, 'Reviewer Provider')).toEqual(modelProviders)
    expect(optionsFor(MODEL_FIELDS, 'Review Fail Closed')).toEqual(['true'])
    expect(optionsFor(MEMORY_FIELDS, 'Memory Provider')).toEqual(['session', 'local', 'mem0'])
  })
})
