import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import { cn } from '../lib/cn'

interface MarkdownProps {
  children: string
  className?: string
}

/**
 * Render assistant message content as GitHub-flavored Markdown.
 *
 * This is the single biggest productization gap it closes: assistant output
 * was previously plain `whitespace-pre-wrap` text. Lists, bold, code blocks,
 * tables, and links now render correctly. External links open safely in a new
 * tab with `rel="noopener noreferrer"`.
 *
 * Prose styling lives in `global.css` under the `.prose-chat` class.
 */
const components: Components = {
  a: ({ node, ...props }) => (
    <a
      {...props}
      target={props.href?.startsWith('http') ? '_blank' : undefined}
      rel={props.href?.startsWith('http') ? 'noopener noreferrer' : undefined}
    />
  ),
}

function MarkdownImpl({ children, className }: MarkdownProps) {
  return (
    <div className={cn('prose-chat', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}

export const Markdown = memo(MarkdownImpl)
