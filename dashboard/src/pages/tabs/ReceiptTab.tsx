import { CodeBlock } from '../../components/CodeBlock'
import { EmptyState } from '../../components/EmptyState'

interface ReceiptTabProps {
  markdown: string
}

export function ReceiptTab({ markdown }: ReceiptTabProps) {
  if (!markdown) return <EmptyState message="No receipt available." />
  return <CodeBlock>{markdown}</CodeBlock>
}
