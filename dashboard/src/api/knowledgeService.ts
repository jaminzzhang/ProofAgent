import { fetchJson } from './client'
import type {
  KnowledgeServiceBaseProjection,
  KnowledgeServiceManagementWorkspace,
  KnowledgeServiceSourceProjection,
  KnowledgeServiceSpaceProjection,
} from './types'

const BASE = '/api/config/knowledge-service'

export function fetchKnowledgeServiceWorkspace(): Promise<KnowledgeServiceManagementWorkspace> {
  return fetchJson(`${BASE}/workspace`)
}

export function createKnowledgeServiceSpace(
  knowledgeSpaceId: string,
): Promise<KnowledgeServiceSpaceProjection> {
  return fetchJson(`${BASE}/spaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ knowledge_space_id: knowledgeSpaceId }),
  })
}

export function createKnowledgeServiceSource(
  knowledgeSpaceId: string,
  knowledgeSourceId: string,
): Promise<KnowledgeServiceSourceProjection> {
  return fetchJson(
    `${BASE}/spaces/${encodeURIComponent(knowledgeSpaceId)}/sources`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ knowledge_source_id: knowledgeSourceId }),
    },
  )
}

export function createKnowledgeServiceBase(
  knowledgeSpaceId: string,
  knowledgeBaseId: string,
): Promise<KnowledgeServiceBaseProjection> {
  return fetchJson(
    `${BASE}/spaces/${encodeURIComponent(knowledgeSpaceId)}/bases`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ knowledge_base_id: knowledgeBaseId }),
    },
  )
}
