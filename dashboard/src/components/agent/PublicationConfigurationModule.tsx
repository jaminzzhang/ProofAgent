import { Badge, Button, ConfigPanel } from '@proofagent/ui'
import type { ProductionAgentPublicationConfiguration } from '../../api/types'
import { useLocale } from '../../i18n/locale'
import { LoadingSpinner } from '../ui/LoadingSpinner'

interface PublicationConfigurationModuleProps {
  configuration: ProductionAgentPublicationConfiguration | null
  loading: boolean
  error: string | null
  onNavigate: (moduleId: string) => void
}

export function PublicationConfigurationModule({
  configuration,
  loading,
  error,
  onNavigate,
}: PublicationConfigurationModuleProps) {
  const { t } = useLocale()

  if (loading) {
    return <div className="flex justify-center py-12"><LoadingSpinner /></div>
  }
  if (error) {
    return (
      <ConfigPanel title={t('publicationConfiguration.title')}>
        <div role="alert" className="text-sm text-[var(--danger)]">{error}</div>
      </ConfigPanel>
    )
  }
  if (!configuration) return null

  const candidate = configuration.knowledge.candidate
  const ready = configuration.authoring_configuration_state === 'ready'

  return (
    <div className="space-y-5">
      <ConfigPanel
        title={t('publicationConfiguration.title')}
        description={t('publicationConfiguration.description')}
        actions={(
          <Badge variant={ready ? 'success' : 'danger'}>
            {ready
              ? t('publicationConfiguration.draftReady')
              : t('publicationConfiguration.draftBlocked')}
          </Badge>
        )}
      >
        <div className="grid gap-3 md:grid-cols-3">
          <Fact
            label={t('publicationConfiguration.draftRevision')}
            value={t('publicationConfiguration.draftRevisionValue').replace(
              '{revision}',
              String(configuration.draft_revision),
            )}
          />
          <Fact
            label={t('publicationConfiguration.formalState')}
            value={t('publicationConfiguration.workspaceDraftNotBound')}
          />
          <Fact
            label={t('publicationConfiguration.activation')}
            value={t('publicationConfiguration.postgresAtomicCas')}
          />
        </div>
      </ConfigPanel>

      {configuration.configuration_blockers.length > 0 && (
        <ConfigPanel
          title={t('publicationConfiguration.blockers')}
          description={t('publicationConfiguration.blockersDescription')}
        >
          <div className="space-y-3">
            {configuration.configuration_blockers.map((blocker) => (
              <div
                key={`${blocker.code}:${blocker.module_id}`}
                className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] p-3"
              >
                <div>
                  <div className="font-mono text-xs text-[var(--danger-fg)]">{blocker.code}</div>
                  <div className="mt-1 text-sm text-[var(--danger-fg)]">{blocker.message}</div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onNavigate(blocker.module_id)}
                >
                  {t('publicationConfiguration.openModule')}
                </Button>
              </div>
            ))}
          </div>
        </ConfigPanel>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        <ConfigPanel
          title={t('publicationConfiguration.workflow')}
          actions={(
            <Button variant="outline" size="sm" onClick={() => onNavigate('workflow')}>
              {t('publicationConfiguration.editSource')}
            </Button>
          )}
        >
          <div className="grid gap-3">
            <Fact
              label={t('publicationConfiguration.template')}
              value={configuration.workflow.template ?? t('publicationConfiguration.notConfigured')}
            />
            <Fact
              label={t('publicationConfiguration.descriptorVersion')}
              value={configuration.workflow.template_descriptor_version ?? t('publicationConfiguration.notConfigured')}
            />
          </div>
        </ConfigPanel>

        <ConfigPanel
          title={t('publicationConfiguration.knowledge')}
          actions={(
            <Button variant="outline" size="sm" onClick={() => onNavigate('knowledge')}>
              {t('publicationConfiguration.editSource')}
            </Button>
          )}
        >
          <div className="grid gap-3">
            <Fact
              label={t('publicationConfiguration.release')}
              value={candidate?.knowledge_base_release_id ?? t('publicationConfiguration.notConfigured')}
            />
            <Fact
              label={t('publicationConfiguration.releaseState')}
              value={configuration.knowledge.queryable
                ? t('publicationConfiguration.queryable')
                : t('publicationConfiguration.notQueryable')}
            />
          </div>
        </ConfigPanel>
      </div>

      <ConfigPanel
        title={t('publicationConfiguration.modelRoles')}
        actions={(
          <Button variant="outline" size="sm" onClick={() => onNavigate('model')}>
            {t('publicationConfiguration.editSource')}
          </Button>
        )}
      >
        <div className="divide-y divide-[var(--border)]">
          {configuration.model_roles.map((role) => (
            <div key={role.role} className="grid gap-2 py-3 first:pt-0 last:pb-0 md:grid-cols-[160px_1fr_auto] md:items-center">
              <div className="font-mono text-xs text-[var(--text-muted)]">{role.role}</div>
              <div>
                <div className="break-all font-mono text-xs text-[var(--text-primary)]">
                  {role.connection_id ?? t('publicationConfiguration.notConfigured')}
                </div>
                {(role.provider || role.model_identifier) && (
                  <div className="mt-1 text-xs text-[var(--text-muted)]">
                    {[role.provider, role.model_identifier].filter(Boolean).join(' / ')}
                  </div>
                )}
              </div>
              <Badge variant={role.configuration_state === 'ready' ? 'success' : 'danger'}>
                {role.configuration_state === 'ready'
                  ? t('publicationConfiguration.configured')
                  : t('publicationConfiguration.blocked')}
              </Badge>
            </div>
          ))}
        </div>
      </ConfigPanel>

      <ConfigPanel
        title={t('publicationConfiguration.formalRequirements')}
        description={t('publicationConfiguration.formalRequirementsDescription')}
        actions={<Badge variant="warning">{t('publicationConfiguration.workspaceDraftNotBound')}</Badge>}
      >
        <div className="grid gap-3 md:grid-cols-2">
          <Fact
            label={t('publicationConfiguration.phaseFEvidence')}
            value={configuration.formal_requirements.phase_f_evidence.join(', ')}
          />
          <Fact
            label={t('publicationConfiguration.onlineSmoke')}
            value={configuration.formal_requirements.online_smoke_required
              ? t('publicationConfiguration.required')
              : t('publicationConfiguration.notRequired')}
          />
        </div>
        <p className="mt-4 rounded-md border border-[var(--warning-border)] bg-[var(--warning-bg)] p-3 text-sm text-[var(--warning-fg)]">
          {t('publicationConfiguration.noDashboardPublish')}
        </p>
      </ConfigPanel>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 break-all text-sm text-[var(--text-primary)]">{value}</div>
    </div>
  )
}
