import { useEffect, useState } from 'react'
import { fetchWorkflowTemplates } from '../api/client'
import type { WorkflowTemplateDescriptor } from '../api/types'
import { productionWorkflowTemplates } from '../workflowTemplates'

interface UseWorkflowTemplatesResult {
  /** Template descriptors from the Dynamic Workflow Template Catalog. */
  templates: WorkflowTemplateDescriptor[]
  /** Template names, suitable as the Template selector option set. */
  names: string[]
  /** True once the fetch has settled (success or failure). */
  loaded: boolean
  /** Error message when the catalog failed to load; null otherwise. */
  error: string | null
}

// Module-level cache: the catalog is global and rarely changes, so we avoid
// re-fetching on every Agent detail page open / tab switch. Cleared only by a
// full page reload. See CONTEXT.md "Dynamic Workflow Template Catalog".
interface CachedCatalog {
  templates: WorkflowTemplateDescriptor[]
  error: string | null
}

let catalogCache: CachedCatalog | null = null
let inflight: Promise<CachedCatalog> | null = null

function loadCatalog(): Promise<CachedCatalog> {
  if (catalogCache) return Promise.resolve(catalogCache)
  if (inflight) return inflight
  inflight = fetchWorkflowTemplates()
    .then((response) => {
      const catalog: CachedCatalog = {
        templates: productionWorkflowTemplates(response.data),
        error: null,
      }
      catalogCache = catalog
      inflight = null
      return catalog
    })
    .catch((err: unknown) => {
      const error = err instanceof Error ? err.message : String(err)
      inflight = null
      // Do not cache failures: a later mount can retry.
      return { templates: [], error }
    })
  return inflight
}

/**
 * Loads the Dynamic Workflow Template Catalog once and exposes the template
 * names + descriptors to the Template selector.
 *
 * The catalog is cached at module scope so repeated mounts (tab switches,
 * reopens) do not re-fetch. When the fetch fails, `templates` is empty and
 * `error` is set; callers are expected to fall back to a static option list
 * (Template Selector Fallback) so the selector is never empty.
 *
 * See CONTEXT.md "Dynamic Workflow Template Catalog" and
 * "Template Selector Fallback".
 */
export function useWorkflowTemplates(): UseWorkflowTemplatesResult {
  const [templates, setTemplates] = useState<WorkflowTemplateDescriptor[]>(
    catalogCache?.templates ?? [],
  )
  const [error, setError] = useState<string | null>(catalogCache?.error ?? null)
  const [loaded, setLoaded] = useState<boolean>(catalogCache !== null)

  useEffect(() => {
    if (catalogCache) return
    let mounted = true
    loadCatalog().then((catalog) => {
      if (!mounted) return
      setTemplates(catalog.templates)
      setError(catalog.error)
      setLoaded(true)
    })
    return () => {
      mounted = false
    }
  }, [])

  return {
    templates,
    names: templates.map((template) => template.name),
    loaded,
    error,
  }
}
