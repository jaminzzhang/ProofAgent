import {
  createConversation,
  createConversationRun,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  updateConversation,
} from '../../api/client'
import type { ChatRunResponse, ConversationRecord } from '../../api/types'

export const fetchOperatorConversations = fetchConversations
export const createOperatorConversation = createConversation
export const fetchOperatorConversation = fetchConversation
export const updateOperatorConversation = updateConversation
export const deleteOperatorConversation = deleteConversation

interface OperatorRunOptions {
  approved?: boolean
  includeGovernanceDetails?: boolean
}

export function createOperatorConversationRun(
  conversationId: string,
  question: string,
  options: OperatorRunOptions = {},
): Promise<ChatRunResponse> {
  return createConversationRun(
    conversationId,
    question,
    options.approved,
    options.includeGovernanceDetails ?? false,
  )
}

export type { ChatRunResponse, ConversationRecord }
