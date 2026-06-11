import {
  createConversation,
  createConversationRun,
  deleteConversation,
  fetchChatAgents,
  fetchConversation,
  fetchConversations,
  updateConversation,
} from '../../api/client'
import type {
  ChatRunResponse,
  ConversationRecord,
  PublishedAgentDirectoryResponse,
} from '../../api/types'

export const fetchOperatorAgents = fetchChatAgents
export const fetchOperatorConversations = fetchConversations
export const createOperatorConversation = createConversation
export const fetchOperatorConversation = fetchConversation
export const updateOperatorConversation = updateConversation
export const deleteOperatorConversation = deleteConversation

interface OperatorRunOptions {
  includeGovernanceDetails?: boolean
  allowUntrustedWebSupplement?: boolean
}

export function createOperatorConversationRun(
  conversationId: string,
  question: string,
  options: OperatorRunOptions = {},
): Promise<ChatRunResponse> {
  return createConversationRun(
    conversationId,
    question,
    {
      includeGovernanceDetails: options.includeGovernanceDetails ?? false,
      allowUntrustedWebSupplement: options.allowUntrustedWebSupplement ?? false,
    },
  )
}

export type { ChatRunResponse, ConversationRecord, PublishedAgentDirectoryResponse }
