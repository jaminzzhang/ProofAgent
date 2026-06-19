import { RunDetailContent } from '../../pages/RunDetailPage'
import { AgentDetailDrawer } from './AgentDetailDrawer'

interface RunDetailDrawerProps {
  runId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RunDetailDrawer({ runId, open, onOpenChange }: RunDetailDrawerProps) {
  return (
    <AgentDetailDrawer
      open={open}
      onOpenChange={onOpenChange}
      title="Run detail"
      description="Governed run detail opened from the Agent detail workspace."
    >
      <RunDetailContent
        runId={runId ?? undefined}
        showBackLink={false}
        className="max-w-none"
      />
    </AgentDetailDrawer>
  )
}
