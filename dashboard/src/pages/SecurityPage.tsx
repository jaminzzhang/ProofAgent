import { useEffect, useState } from 'react'
import { Badge, Card, EmptyState, Skeleton } from '@proofagent/ui'
import { PageHeader } from '../components/PageHeader'
import {
  activateEgressPolicy,
  activatePermissionMapping,
  createEgressPolicy,
  createPermissionMapping,
  fetchEgressPolicies,
  fetchPermissionMappings,
  validateSecretHandle,
} from '../api/client'
import type {
  EgressPoliciesResponse,
  PermissionMappingsResponse,
  SecretHandleValidation,
} from '../api/types'
import { useSession } from '../auth/session'

export function SecurityPage() {
  const { hasPermission } = useSession()
  const canViewMappings = hasPermission('permission_mapping.view')
  const canEditMappings = hasPermission('permission_mapping.edit')
  const canViewEgress = hasPermission('egress_policy.view')
  const canEditEgress = hasPermission('egress_policy.edit')
  const canUseSecrets = hasPermission('secret_handle.view') && hasPermission('secret_handle.use')
  const [mappings, setMappings] = useState<PermissionMappingsResponse | null>(null)
  const [egress, setEgress] = useState<EgressPoliciesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [handleId, setHandleId] = useState('')
  const [secretValidation, setSecretValidation] = useState<SecretHandleValidation | null>(null)
  const [mappingVersionId, setMappingVersionId] = useState('')
  const [mappingRules, setMappingRules] = useState('[]')
  const [showMappingForm, setShowMappingForm] = useState(false)
  const [egressVersionId, setEgressVersionId] = useState('')
  const [egressRules, setEgressRules] = useState('[]')
  const [showEgressForm, setShowEgressForm] = useState(false)

  async function savePermissionMapping() {
    try {
      const rules = JSON.parse(mappingRules) as PermissionMappingsResponse['versions'][number]['rules']
      if (!Array.isArray(rules)) throw new Error('Permission rules must be a JSON array.')
      await createPermissionMapping({
        version_id: mappingVersionId,
        expected_revision: Math.max(0, ...(mappings?.versions.map((item) => item.revision) ?? [])),
        rules,
      })
      setShowMappingForm(false)
      setMappingVersionId('')
      setMappingRules('[]')
      await reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to create permission mapping.')
    }
  }

  async function saveEgressPolicy() {
    try {
      const rules = JSON.parse(egressRules) as EgressPoliciesResponse['versions'][number]['rules']
      if (!Array.isArray(rules)) throw new Error('Egress rules must be a JSON array.')
      await createEgressPolicy({
        version_id: egressVersionId,
        expected_revision: Math.max(0, ...(egress?.versions.map((item) => item.revision) ?? [])),
        rules,
      })
      setShowEgressForm(false)
      setEgressVersionId('')
      setEgressRules('[]')
      await reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to create egress policy.')
    }
  }

  async function reload() {
    setLoading(true)
    try {
      const [mappingResult, egressResult] = await Promise.all([
        canViewMappings ? fetchPermissionMappings() : Promise.resolve(null),
        canViewEgress ? fetchEgressPolicies() : Promise.resolve(null),
      ])
      setMappings(mappingResult)
      setEgress(egressResult)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load security configuration.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void reload() }, [canViewMappings, canViewEgress])

  if (!canViewMappings && !canViewEgress && !canUseSecrets) {
    return <Card><EmptyState message="You do not have permission to view security configuration." /></Card>
  }

  return (
    <div className="max-w-7xl space-y-5">
      <PageHeader title="Security" description="Tenant-global identity, egress, and Secret Handle controls." />
      {loading ? <Skeleton className="h-40 rounded-lg" /> : error ? <div role="alert">{error}</div> : null}

      {mappings && (
        <Card className="space-y-4">
          <h2 className="text-lg font-semibold">Permission mappings</h2>
          <div data-testid="recovery-mapping" className="rounded border border-[var(--border)] p-3">
            <div className="flex gap-2"><strong>Recovery OIDC Group</strong><Badge variant="subtle">immutable</Badge></div>
            <div className="font-mono text-sm">{mappings.recovery_mapping.group_name}</div>
          </div>
          {mappings.versions.map((version) => (
            <div key={version.version_id} className="flex items-center justify-between border-t border-[var(--border)] pt-3">
              <span>Revision {version.revision} · {version.version_id}</span>
              {mappings.active?.version_id === version.version_id ? <Badge>active</Badge> : canEditMappings ? (
                <button onClick={() => activatePermissionMapping(version.version_id).then(reload)}>Activate</button>
              ) : null}
            </div>
          ))}
          {canEditMappings && !showMappingForm && (
            <button onClick={() => setShowMappingForm(true)}>New mapping version</button>
          )}
          {canEditMappings && showMappingForm && (
            <div className="space-y-2 border-t border-[var(--border)] pt-3">
              <label className="block text-sm">Version ID<input aria-label="Permission mapping version ID" value={mappingVersionId} onChange={(event) => setMappingVersionId(event.target.value)} className="ml-2 border" /></label>
              <label className="block text-sm">Rules JSON<textarea aria-label="Permission rules JSON" value={mappingRules} onChange={(event) => setMappingRules(event.target.value)} className="block min-h-24 w-full border font-mono" /></label>
              <button disabled={!mappingVersionId} onClick={() => void savePermissionMapping()}>Save mapping version</button>
            </div>
          )}
        </Card>
      )}

      {egress && (
        <Card className="space-y-4">
          <h2 className="text-lg font-semibold">Egress policies</h2>
          {egress.versions.map((version) => (
            <div key={version.version_id} className="flex items-center justify-between border-t border-[var(--border)] pt-3">
              <span>Revision {version.revision} · {version.rules.length} exact origin(s)</span>
              {egress.active?.version_id === version.version_id ? <Badge>active</Badge> : canEditEgress ? (
                <button onClick={() => activateEgressPolicy(version.version_id).then(reload)}>Activate</button>
              ) : null}
            </div>
          ))}
          {canEditEgress && !showEgressForm && (
            <button onClick={() => setShowEgressForm(true)}>New egress policy</button>
          )}
          {canEditEgress && showEgressForm && (
            <div className="space-y-2 border-t border-[var(--border)] pt-3">
              <label className="block text-sm">Version ID<input aria-label="Egress policy version ID" value={egressVersionId} onChange={(event) => setEgressVersionId(event.target.value)} className="ml-2 border" /></label>
              <label className="block text-sm">Rules JSON<textarea aria-label="Egress rules JSON" value={egressRules} onChange={(event) => setEgressRules(event.target.value)} className="block min-h-24 w-full border font-mono" /></label>
              <button disabled={!egressVersionId} onClick={() => void saveEgressPolicy()}>Save egress policy</button>
            </div>
          )}
        </Card>
      )}

      {canUseSecrets && (
        <Card className="space-y-3">
          <h2 className="text-lg font-semibold">Validate Secret Handle</h2>
          <label className="block text-sm">Handle ID<input aria-label="Handle ID" value={handleId} onChange={(event) => setHandleId(event.target.value)} className="ml-2 border" /></label>
          <button disabled={!handleId} onClick={() => validateSecretHandle({
            protocol_id: 'hashicorp-vault-2.0-kv-v2',
            handle_id: handleId,
            purpose: 'model_credential',
          }).then(setSecretValidation)}>Validate metadata</button>
          {secretValidation && <div role="status">{secretValidation.resolvable ? 'Resolvable' : secretValidation.reason_code}</div>}
        </Card>
      )}
    </div>
  )
}
