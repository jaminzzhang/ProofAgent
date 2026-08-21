import { Badge, ConfigPanel } from '@proofagent/ui'
import { CodeBlock } from '../CodeBlock'
import { extractAgentYamlPathSection } from '../../utils/agentYaml'

interface ConfigurationSection {
  label: string
  path?: string[]
  content?: string
}

interface ReadOnlyConfigurationModuleProps {
  title: string
  description: string
  status: string
  agentYaml: string
  sections: ConfigurationSection[]
  emptyMessage: string
}

/**
 * Read-only projection of one logical Agent configuration module.
 *
 * Production keeps the full Draft Contract visible even when a module's write
 * authority has not yet moved behind a production command endpoint. The
 * projection deliberately owns no mutation callbacks, so visibility can never
 * be mistaken for edit authority.
 */
export function ReadOnlyConfigurationModule({
  title,
  description,
  status,
  agentYaml,
  sections,
  emptyMessage,
}: ReadOnlyConfigurationModuleProps) {
  const projections = sections
    .map((section) => ({
      label: section.label,
      content: section.content ?? (
        section.path ? extractAgentYamlPathSection(agentYaml, section.path) : ''
      ),
    }))
    .filter((section) => section.content.trim().length > 0)

  return (
    <ConfigPanel
      headingLevel={3}
      title={title}
      description={description}
      actions={<Badge variant="subtle">{status}</Badge>}
    >
      {projections.length > 0 ? (
        <div className="space-y-5">
          {projections.map((section) => (
            <section key={section.label} className="space-y-2">
              <h4 className="font-mono text-xs font-semibold text-[var(--text-muted)]">
                {section.label}
              </h4>
              <CodeBlock>{section.content}</CodeBlock>
            </section>
          ))}
        </div>
      ) : (
        <p className="text-sm text-[var(--text-muted)]">{emptyMessage}</p>
      )}
    </ConfigPanel>
  )
}

export type { ConfigurationSection, ReadOnlyConfigurationModuleProps }
