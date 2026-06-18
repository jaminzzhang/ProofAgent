import { useState, useRef, useEffect, useCallback } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import type { ConversationRecord } from '../api/types'
import { useLocale } from '../i18n/locale'

interface HistorySidebarProps {
  conversations: ConversationRecord[]
  onNewChat: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onTogglePin: (id: string, pinned: boolean) => void
  routePrefix?: string
}

export function HistorySidebar({
  conversations,
  onNewChat,
  onRename,
  onDelete,
  onTogglePin,
  routePrefix = '',
}: HistorySidebarProps) {
  const location = useLocation()
  const { t, formatDateTime } = useLocale()
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
          {t('history.newChat')}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4 custom-scrollbar" ref={menuContainerRef}>
        {conversations.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <p className="text-xs text-[var(--text-muted)]">{t('history.noConversations')}</p>
            <p className="text-xs text-[var(--text-muted)] mt-1">{t('history.startHint')}</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {conversations.map((conv) => {
              const isActive = location.pathname === `${routePrefix}/c/${conv.conversation_id}`
              const displayTitle =
                conv.title || conv.turns[0]?.question || t('history.newConversation')
              const isRenaming = renamingId === conv.conversation_id

              return (
                <div key={conv.conversation_id}>
                  <div className="group relative">
                    <NavLink
                      to={`${routePrefix}/c/${conv.conversation_id}`}
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
                        {formatDateTime(conv.updated_at)}
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
                      aria-label={t('history.conversationMenu', 'Conversation actions')}
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
                          {t('history.rename')}
                        </button>
                        <button
                          onClick={() => {
                            setMenuOpenId(null)
                            onTogglePin(conv.conversation_id, !conv.pinned)
                          }}
                          className="w-full text-left px-3 py-1.5 text-[13px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors"
                        >
                          {conv.pinned ? t('history.unpin') : t('history.pin')}
                        </button>
                        <button
                          onClick={() => handleDeleteStart(conv.conversation_id)}
                          className="w-full text-left px-3 py-1.5 text-[13px] text-[var(--danger-fg)] hover:bg-[var(--danger-bg)] transition-colors"
                        >
                          {t('history.delete')}
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Delete confirmation */}
                  {deletingId === conv.conversation_id && (
                    <div className="mt-0.5 rounded-lg border border-[var(--danger-border)] bg-[var(--danger-bg)] px-3 py-2">
                      <p className="mb-2 text-[11px] text-[var(--danger-fg)]">
                        {t('history.deleteConfirm')}
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleDeleteConfirm(conv.conversation_id)}
                          className="rounded bg-[var(--danger)] px-2.5 py-1 text-[11px] font-medium text-white transition-colors hover:opacity-90"
                        >
                          {t('history.delete')}
                        </button>
                        <button
                          onClick={() => setDeletingId(null)}
                          className="rounded bg-[var(--bg-hover)] px-2.5 py-1 text-[11px] font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
                        >
                          {t('history.cancel')}
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
