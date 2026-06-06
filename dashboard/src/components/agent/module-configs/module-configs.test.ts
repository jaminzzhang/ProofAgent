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

function fieldPaths(fields: readonly { path: readonly string[] }[]): readonly string[] {
  return fields.map((field) => field.path.join('.'))
}

describe('module configuration field options', () => {
  it('uses backend-supported knowledge and retrieval values', () => {
    expect(optionsFor(KNOWLEDGE_FIELDS, 'Retrieval Strategy')).toEqual([
      'single_step',
      'agentic',
    ])
    expect(fieldPaths(KNOWLEDGE_FIELDS)).toEqual(expect.arrayContaining([
      'retrieval.strategy',
      'retrieval.top_k',
      'retrieval.min_score',
    ]))
  })

  it('uses backend-supported workflow, model, review, and memory values', () => {
    const modelProviders = ['deterministic', 'openai_compatible', 'openai', 'deepseek', 'azure_openai', 'anthropic']

    expect(optionsFor(WORKFLOW_FIELDS, 'Checkpointer Provider')).toEqual(['sqlite'])
    expect(optionsFor(MODEL_FIELDS, 'Answer Model Provider')).toEqual(modelProviders)
    expect(optionsFor(MODEL_FIELDS, 'Planner Provider')).toEqual(modelProviders)
    expect(optionsFor(MODEL_FIELDS, 'Review Mode')).toEqual(['rules_only', 'auto'])
    expect(optionsFor(MODEL_FIELDS, 'Reviewer Provider')).toEqual(modelProviders)
    expect(optionsFor(MODEL_FIELDS, 'Review Fail Closed')).toEqual(['true'])
    expect(optionsFor(MEMORY_FIELDS, 'Memory Provider')).toEqual(['session', 'local', 'mem0'])
  })

  it('exposes shared model params for answer, planner, and reviewer roles', () => {
    expect(fieldPaths(MODEL_FIELDS)).toEqual(expect.arrayContaining([
      'model.params.api_key_env',
      'model.params.base_url_env',
      'model.params.temperature',
      'model.params.max_output_tokens',
      'model.params.timeout_seconds',
      'react.planner.params.api_key_env',
      'react.planner.params.base_url_env',
      'react.planner.params.temperature',
      'react.planner.params.max_output_tokens',
      'react.planner.params.timeout_seconds',
      'review.subagent.params.api_key_env',
      'review.subagent.params.base_url_env',
      'review.subagent.params.temperature',
      'review.subagent.params.max_output_tokens',
      'review.subagent.params.timeout_seconds',
    ]))
  })
})
