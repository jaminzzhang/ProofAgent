interface CodeBlockProps {
  children: string
}

export function CodeBlock({ children }: CodeBlockProps) {
  return (
    <pre className="bg-[var(--bg-base)] border border-[var(--border)] rounded-md p-3 text-xs font-mono text-[var(--text-secondary)] overflow-x-auto whitespace-pre-wrap">
      {children}
    </pre>
  )
}
