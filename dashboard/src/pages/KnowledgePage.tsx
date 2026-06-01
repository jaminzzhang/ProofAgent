import { useEffect, useState } from 'react'
import {
  createKnowledgeSource,
  fetchKnowledgeDocuments,
  fetchKnowledgeSources,
  uploadKnowledgeDocument,
} from '../api/client'
import type { KnowledgeDocument, KnowledgeSource } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

const DEFAULT_LOCAL_INDEX_PATH = './data/indexes/knowledge'

export function KnowledgePage() {
  const [sources, setSources] = useState<readonly KnowledgeSource[]>([])
  const [documentsBySource, setDocumentsBySource] = useState<Record<string, readonly KnowledgeDocument[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [busy, setBusy] = useState<string | null>(null)
  const [name, setName] = useState('Local Index Knowledge')
  const [sourceId, setSourceId] = useState('')
  const [indexPath, setIndexPath] = useState(DEFAULT_LOCAL_INDEX_PATH)

  async function loadSources() {
    const { data } = await fetchKnowledgeSources()
    setSources(data)
  }

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const { data } = await fetchKnowledgeSources()
        if (!cancelled) {
          setSources(data)
          setError(null)
        }
      } catch {
        if (!cancelled) setError('Unable to load knowledge sources.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  async function createSource() {
    setBusy('create')
    setError(null)
    setStatus(null)
    try {
      const source = await createKnowledgeSource({
        source_id: sourceId || undefined,
        name,
        provider: 'local_index',
        params: {
          index_path: indexPath,
        },
        actor: 'dashboard',
      })
      setStatus(`Created ${source.name}.`)
      setSourceId('')
      setIndexPath(DEFAULT_LOCAL_INDEX_PATH)
      await loadSources()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create knowledge source.')
    } finally {
      setBusy(null)
    }
  }

  async function toggle(source: KnowledgeSource) {
    const isOpen = expanded.has(source.source_id)
    setExpanded((prev) => {
      const next = new Set(prev)
      if (isOpen) next.delete(source.source_id)
      else next.add(source.source_id)
      return next
    })
    if (!isOpen && !documentsBySource[source.source_id]) {
      await loadDocuments(source.source_id)
    }
  }

  async function loadDocuments(id: string) {
    const { data } = await fetchKnowledgeDocuments(id)
    setDocumentsBySource((prev) => ({ ...prev, [id]: data }))
  }

  async function uploadDocument(source: KnowledgeSource, file: File | undefined) {
    if (!file) return
    setBusy(`upload-${source.source_id}`)
    setError(null)
    setStatus(null)
    try {
      const contentBase64 = await fileToBase64(file)
      const document = await uploadKnowledgeDocument(source.source_id, {
        filename: file.name,
        content_type: file.type || contentTypeForName(file.name),
        content_base64: contentBase64,
        actor: 'dashboard',
      })
      setStatus(`${document.filename} is ${document.state}.`)
      await loadSources()
      await loadDocuments(source.source_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to upload document.')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><LoadingSpinner /></div>

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Knowledge Sources</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Manage shared knowledge sources independently, then bind them from Agent configuration.
        </p>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Create Local Index Source
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Upload PDF or Markdown into a governed local index source. Index build runs before publication.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <TextField label="Name" value={name} onChange={setName} />
          <TextField label="Source ID" value={sourceId} onChange={setSourceId} placeholder="ks_policies" />
          <TextField label="Index Path" value={indexPath} onChange={setIndexPath} />
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={createSource}
            disabled={busy === 'create' || !name.trim() || !indexPath.trim()}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {busy === 'create' ? 'Creating...' : 'Create Source'}
          </button>
        </div>
      </div>

      {status && (
        <div className="rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-4 py-3 text-sm text-[var(--success)]">
          {status}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {sources.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-6">
          <EmptyState message="No knowledge sources configured." />
        </div>
      ) : (
        <div className="space-y-3">
          {sources.map((source) => {
            const isOpen = expanded.has(source.source_id)
            const documents = documentsBySource[source.source_id] ?? []
            return (
              <div key={source.source_id} className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]">
                <button
                  onClick={() => void toggle(source)}
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-5 py-4 text-left hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <span className={`shrink-0 text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-90' : ''}`}>&#9654;</span>
                  <span className="min-w-0 flex-1 basis-44 truncate font-medium text-[var(--text-primary)]">{source.name}</span>
                  <span className="rounded-md bg-[var(--bg-base)] px-2 py-0.5 text-xs font-mono text-[var(--text-secondary)]">{source.provider}</span>
                  <span className="text-xs text-[var(--text-muted)]">{source.ready_document_count} / {source.document_count} ready</span>
                  <span className="basis-full pl-6 text-xs font-mono text-[var(--text-muted)] md:basis-auto md:pl-0">{source.source_id}</span>
                </button>

                {isOpen && (
                  <div className="space-y-4 border-t border-[var(--border)] px-5 py-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-sm text-[var(--text-muted)]">
                        Upload PDF or Markdown. The backend validates content and stages it for Local Index ingestion.
                      </div>
                      <label className="cursor-pointer rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]">
                        {busy === `upload-${source.source_id}` ? 'Uploading...' : 'Upload Document'}
                        <input
                          type="file"
                          accept=".pdf,.md,.markdown,application/pdf,text/markdown,text/plain"
                          disabled={busy === `upload-${source.source_id}`}
                          onChange={(event) => void uploadDocument(source, event.target.files?.[0])}
                          className="hidden"
                        />
                      </label>
                    </div>
                    {documents.length === 0 ? (
                      <div className="rounded-md border border-dashed border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--text-muted)]">
                        No documents uploaded yet.
                      </div>
                    ) : (
                      <div className="divide-y divide-[var(--border)] rounded-md border border-[var(--border)]">
                        {documents.map((document) => (
                          <div key={document.document_id} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[1fr_auto_auto]">
                            <span className="truncate font-medium text-[var(--text-primary)]">{document.filename}</span>
                            <span className="font-mono text-xs text-[var(--text-muted)]">{formatBytes(document.size_bytes)}</span>
                            <span className={`text-xs font-medium ${document.state === 'ready' ? 'text-[var(--success)]' : 'text-[var(--text-muted)]'}`}>
                              {document.state}
                            </span>
                            {document.error_message && (
                              <span className="md:col-span-3 text-xs text-[var(--danger)]">{document.error_message}</span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
      />
    </label>
  )
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Unable to read file.'))
    reader.onload = () => {
      const result = String(reader.result ?? '')
      resolve(result.includes(',') ? result.split(',')[1] : result)
    }
    reader.readAsDataURL(file)
  })
}

function contentTypeForName(filename: string): string {
  const suffix = filename.toLowerCase().split('.').pop()
  if (suffix === 'pdf') return 'application/pdf'
  if (suffix === 'md' || suffix === 'markdown') return 'text/markdown'
  return 'application/octet-stream'
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
