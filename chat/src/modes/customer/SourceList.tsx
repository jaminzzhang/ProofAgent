import type { CustomerSafeSource } from '../../api/types'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@proofagent/ui'

export function SourceList({ sources }: { sources: Array<string | CustomerSafeSource> }) {
  if (sources.length === 0) {
    return null
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex flex-wrap gap-2">
        {sources.map((source) => {
          const key = typeof source === 'string' ? source : source.source_id
          const label = typeof source === 'string' ? source : source.label
          const excerpt = typeof source === 'string' ? null : source.excerpt
          const chip = (
            <span className="rounded-md border border-[var(--border)] bg-[var(--bg-hover)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)]">
              {label}
            </span>
          )
          if (!excerpt) {
            return <span key={key}>{chip}</span>
          }
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <button type="button" className="cursor-help">
                  {chip}
                </button>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs whitespace-normal text-left">
                <span className="line-clamp-3">{excerpt}</span>
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
