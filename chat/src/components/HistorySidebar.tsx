import { useState, useRef, useEffect, useCallback } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import type { ConversationRecord } from '../api/types'

interface HistorySidebarProps {
  conversations: ConversationRecord[]
  onNewChat: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onTogglePin: (id: string, pinned: boolean) => void
}

export function HistorySidebar({
  conversations,
  onNewChat,
  onRename,
  onDelete,
  onTogglePin,
}: HistorySidebarProps) {
  const location = useLocation()
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameSubmittingRef = useRef(false)
  const menuContainerRef = useRef<HTMLDivElement>(null)

  // Close menu on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuOpenId && menuContainerRef.current && !menuContainerRef.current.contains(e.target as Node)) {
        setMenuOpenId(null)
      }
    }
    if (menuOpenId) {
      document.addEventListener('mousedown', handleClick)
      return () => document.removeEventListener('mousedown', handleClick)
    }
  }, [menuOpenId])

  const handleRenameStart = useCallback((conv: ConversationRecord) => {
    setMenuOpenId(null)
    setRenamingId(conv.conversation_id)
    setRenameValue(conv.title || '')
  }, [])

  const handleRenameSubmit = useCallback((id: string) => {
    if (renameSubmittingRef.current) return
    renameSubmittingRef.current = true
    onRename(id, renameValue)
    setRenamingId(null)
    setRenameValue('')
    // Allow next submit after state settles
    setTimeout(() => {
      renameSubmittingRef.current = false
    }, 0)
  }, [onRename, renameValue])

  const handleRenameCancel = useCallback(() => {
    setRenamingId(null)
    setRenameValue('')
  }, [])

  const handleRenameKeyDown = useCallback((e: React.KeyboardEvent, id: string) => {
    if (e.key === 'Enter') {
      handleRenameSubmit(id)
    } else if (e.key === 'Escape') {
      handleRenameCancel()
    }
  }, [handleRenameSubmit, handleRenameCancel])

  const handleDeleteStart = useCallback((id: string) => {
    setMenuOpenId(null)
    setDeletingId(id)
  }, [])

  const handleDeleteConfirm = useCallback((id: string) => {
    setDeletingId(null)
    onDelete(id)
  }, [onDelete])

  return (
    <aside className="w-64 shrink-0 border-r border-[var(--border)] bg-[var(--bg-surface)] flex flex-col overflow-hidden">
      <div className="p-4">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-[var(--accent)] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-all shadow-sm active:scale-95"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4 custom-scrollbar" ref={menuContainerRef}>
        {conversations.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <p className="text-xs text-[var(--text-muted)]">No conversations yet.</p>
            <p className="text-xs text-[var(--text-muted)] mt-1">Click "New Chat" to start.</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {conversations.map((conv) => {
              const isActive = location.pathname === `/c/${conv.conversation_id}`
              const displayTitle =
                conv.title || conv.turns[0]?.question || 'New Conversation'
              const isRenaming = renamingId === conv.conversation_id

              return (
                <div key={conv.conversation_id}>
                  <div className="group relative">
                    <NavLink
                      to={`/c/${conv.conversation_id}`}
                      className={`flex flex-col px-3 py-2.5 rounded-lg transition-colors ${
                        isActive
                          ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 w-full">
                        {conv.pinned && (
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            width="12"
                            height="12"
                            viewBox="0 0 24 24"
                            fill="currentColor"
                            className="shrink-0 text-[var(--text-muted)]"
                          >
                            <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z" />
                          </svg>
                        )}
                        {isRenaming ? (
                          <input
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onBlur={() => handleRenameSubmit(conv.conversation_id)}
                            onKeyDown={(e) => handleRenameKeyDown(e, conv.conversation_id)}
                            className="text-[13px] font-medium bg-[var(--bg-base)] border border-[var(--accent)] rounded px-1.5 py-0.5 w-full outline-none text-[var(--text-primary)]"
                            autoFocus
                            // eslint-disable-next-line jsx-a11y/no-autofocus
                          />
                        ) : (
                          <span className="text-[13px] font-medium truncate leading-tight">
                            {displayTitle}
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-[var(--text-muted)] mt-1 font-mono uppercase tracking-tighter">
                        {formatDate(conv.updated_at)}
                      </span>
                    </NavLink>

                    {/* Three-dot menu button */}
                    <button
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        setMenuOpenId(
                          menuOpenId === conv.conversation_id
                            ? null
                            : conv.conversation_id
                        )
                      }}
                      className={`absolute right-1 top-1.5 p-1 rounded transition-all ${
                        menuOpenId === conv.conversation_id
                          ? 'opacity-100 text-[var(--text-primary)]'
                          : 'opacity-0 group-hover:opacity-100 text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                        <circle cx="12" cy="5" r="2" />
                        <circle cx="12" cy="12" r="2" />
                        <circle cx="12" cy="19" r="2" />
                      </svg>
                    </button>

                    {/* Dropdown menu */}
                    {menuOpenId === conv.conversation_id && (
                      <div
                        className="absolute right-1 top-9 z-50 w-36 bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg shadow-lg py-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() => handleRenameStart(conv)}
                          className="w-full text-left px-3 py-1.5 text-[13px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors"
                        >
                          Rename
                        </button>
                        <button
                          onClick={() => {
                            setMenuOpenId(null)
                            onTogglePin(conv.conversation_id, !conv.pinned)
                          }}
                          className="w-full text-left px-3 py-1.5 text-[13px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors"
                        >
                          {conv.pinned ? 'Unpin' : 'Pin to Top'}
                        </button>
                        <button
                          onClick={() => handleDeleteStart(conv.conversation_id)}
                          className="w-full text-left px-3 py-1.5 text-[13px] text-red-500 hover:bg-[var(--bg-hover)] transition-colors"
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Delete confirmation */}
                  {deletingId === conv.conversation_id && (
                    <div className="px-3 py-2 mt-0.5 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/40 rounded-lg">
                      <p className="text-[11px] text-red-800 dark:text-red-300 mb-2">
                        Delete this conversation? This cannot be undone.
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleDeleteConfirm(conv.conversation_id)}
                          className="px-2.5 py-1 text-[11px] font-medium bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setDeletingId(null)}
                          className="px-2.5 py-1 text-[11px] font-medium bg-[var(--bg-hover)] text-[var(--text-secondary)] rounded hover:text-[var(--text-primary)] transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </aside>
  )
}

function formatDate(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return ts
  }
}
