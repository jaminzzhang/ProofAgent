import { useEffect, useId, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Badge, Button, ConfigPanel, KeyValueList, ReferenceChips, Switch } from '@proofagent/ui'
import { CodeBlock } from '../CodeBlock'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { useLocale } from '../../i18n/locale'
import { AgentDetailDrawer } from './AgentDetailDrawer'
import type {
  BusinessFlowSkillPackConfiguration,
  BusinessFlowSkillPackCreateRequest,
  BusinessFlowSkillPackProjection,
  BusinessFlowSkillPackUpdateRequest,
  WorkflowStagePromptConfig,
} from '../../api/types'

interface SkillsModuleEditorProps {
  config: BusinessFlowSkillPackConfiguration | null
  loading: boolean
  error: string | null
  busy: boolean
  onCreatePack: (payload: BusinessFlowSkillPackCreateRequest) => Promise<void>
  onUpdatePack: (packId: string, payload: BusinessFlowSkillPackUpdateRequest) => Promise<void>
  onDeletePack: (packId: string) => Promise<void>
}

interface StageDraft {
  businessContext: string
  taskInstructions: string
  outputPreferences: string
}

interface PackDraft {
  label: string
  description: string
  intentPatterns: string
  intentTaxonomyRefs: string
  admission: Record<string, unknown>
  minConfidence: string
  knowledgeBindingRefs: string
  toolContractRefs: string
  policyRuleRefs: string
  validatorRefs: string
  default: boolean
  stages: Record<string, StageDraft>
}

const EMPTY_STAGE_DRAFT: StageDraft = {
  businessContext: '',
  taskInstructions: '',
  outputPreferences: '',
}

export function SkillsModuleEditor({
  config,
  loading,
  error,
  busy,
  onCreatePack,
  onUpdatePack,
  onDeletePack,
}: SkillsModuleEditorProps) {
  const { t } = useLocale()
  const [selectedPackId, setSelectedPackId] = useState<string | null>(null)
  const [draft, setDraft] = useState<PackDraft | null>(null)
  const [newPackId, setNewPackId] = useState('')
  const [newPackLabel, setNewPackLabel] = useState('')
  const [newPackDescription, setNewPackDescription] = useState('')
  const [newPackIntentPatterns, setNewPackIntentPatterns] = useState('')
  const [newPackIntentTaxonomyRefs, setNewPackIntentTaxonomyRefs] = useState('')
  const [newPackMinConfidence, setNewPackMinConfidence] = useState('')
  const [newPackKnowledgeBindingRefs, setNewPackKnowledgeBindingRefs] = useState('')
  const [newPackToolContractRefs, setNewPackToolContractRefs] = useState('')
  const [newPackPolicyRuleRefs, setNewPackPolicyRuleRefs] = useState('')
  const [newPackValidatorRefs, setNewPackValidatorRefs] = useState('')
  const [newPackDefault, setNewPackDefault] = useState(false)
  const [newPackStages, setNewPackStages] = useState<Record<string, StageDraft>>({})
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit' | null>(null)

  const selectedPack = useMemo(
    () => config?.packs.find((pack) => pack.id === selectedPackId) ?? config?.packs[0] ?? null,
    [config, selectedPackId],
  )

  useEffect(() => {
    if (!config || config.packs.length === 0) {
      setSelectedPackId(null)
      return
    }
    if (!selectedPackId || !config.packs.some((pack) => pack.id === selectedPackId)) {
      setSelectedPackId(config.packs[0].id)
    }
  }, [config, selectedPackId])

  useEffect(() => {
    if (!selectedPack || !config) {
      setDraft(null)
      return
    }
    setDraft(packToDraft(selectedPack, config))
  }, [config, selectedPack])

  if (loading) {
    return (
      <div className="border border-[var(--border)] bg-[var(--bg-surface)] p-8">
        <div className="flex justify-center">
          <LoadingSpinner />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-5 text-sm text-[var(--danger)]">
        {error}
      </div>
    )
  }

  if (!config) {
    return (
      <div className="border border-[var(--border)] bg-[var(--bg-surface)] p-5 text-sm text-[var(--text-muted)]">
        {t('skills.notLoaded')}
      </div>
    )
  }

  async function createPack() {
    const id = newPackId.trim()
    const label = newPackLabel.trim()
    if (!id || !label) return
    await onCreatePack({
      id,
      label,
      description: newPackDescription.trim(),
      intent_patterns: splitLines(newPackIntentPatterns),
      intent_taxonomy_refs: splitLines(newPackIntentTaxonomyRefs),
      default: newPackDefault,
    })
    const supplementalPayload = newPackSupplementalUpdatePayload()
    if (hasSupplementalCreateUpdate(supplementalPayload)) {
      await onUpdatePack(id, supplementalPayload)
    }
    resetNewPackForm()
    setSelectedPackId(id)
    setDrawerMode(null)
  }

  async function savePack() {
    if (!selectedPack || !draft) return
    await onUpdatePack(selectedPack.id, draftToUpdatePayload(draft))
    setDrawerMode(null)
  }

  async function deletePack() {
    if (!selectedPack) return
    await onDeletePack(selectedPack.id)
    setDrawerMode(null)
  }

  function openEditPack(pack: BusinessFlowSkillPackProjection) {
    if (!config) return
    setSelectedPackId(pack.id)
    setDraft(packToDraft(pack, config))
    setDrawerMode('edit')
  }

  function resetNewPackForm() {
    setNewPackId('')
    setNewPackLabel('')
    setNewPackDescription('')
    setNewPackIntentPatterns('')
    setNewPackIntentTaxonomyRefs('')
    setNewPackMinConfidence('')
    setNewPackKnowledgeBindingRefs('')
    setNewPackToolContractRefs('')
    setNewPackPolicyRuleRefs('')
    setNewPackValidatorRefs('')
    setNewPackDefault(false)
    setNewPackStages({})
  }

  function newPackSupplementalUpdatePayload(): BusinessFlowSkillPackUpdateRequest {
    const admission: Record<string, unknown> = {}
    const minConfidence = Number(newPackMinConfidence)
    if (newPackMinConfidence.trim() && Number.isFinite(minConfidence)) {
      admission.min_confidence = minConfidence
    }

    return {
      intent_taxonomy_refs: splitLines(newPackIntentTaxonomyRefs),
      stage_prompt_addenda: stageDraftsToPromptConfig(newPackStages),
      knowledge_binding_refs: splitLines(newPackKnowledgeBindingRefs),
      tool_contract_refs: splitLines(newPackToolContractRefs),
      policy_rule_refs: splitLines(newPackPolicyRuleRefs),
      validator_refs: splitLines(newPackValidatorRefs),
      admission,
      default: newPackDefault,
    }
  }

  function patchNewStageDraft(stageId: string, patch: Partial<StageDraft>) {
    setNewPackStages((current) => ({
      ...current,
      [stageId]: {
        ...(current[stageId] ?? EMPTY_STAGE_DRAFT),
        ...patch,
      },
    }))
  }

  return (
    <div className="border border-[var(--border)] bg-[var(--bg-surface)]">
      <div className="border-b border-[var(--border)] p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              {t('skills.configuration')}
            </h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('skills.description').replace('{template}', config.template_name)}
            </p>
          </div>
          <div className="grid gap-2 text-xs text-[var(--text-muted)] sm:grid-cols-3 xl:min-w-[420px]">
            <Metric label={t('skills.enabled')} value={config.enabled ? t('skills.yes') : t('skills.no')} />
            <Metric label={t('skills.template')} value={config.template_descriptor_version} />
            <Metric label={t('skills.slots')} value={String(config.addendum_slots.length)} />
          </div>
        </div>
      </div>

      <div className="space-y-5 p-5">
        <ConfigPanel
          variant="nested"
          headingLevel={4}
          title={
            <span className="flex min-w-0 items-center gap-2">
              {t('skills.businessFlowPacks')}
              <Badge variant="subtle">{config.packs.length}</Badge>
            </span>
          }
          description={t('skills.packsDescription')}
          actions={
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                resetNewPackForm()
                setDrawerMode('create')
              }}
            >
              {t('skills.newPack')}
            </Button>
          }
        >
          {config.packs.length === 0 ? (
            <div className="mt-1 border border-dashed border-[var(--border)] bg-[var(--bg-surface)] p-6 text-sm text-[var(--text-muted)]">
              {t('skills.noneConfigured')}
            </div>
          ) : (
            <div className="mt-1 space-y-3">
              {config.packs.map((pack) => (
                <SkillPackListRow
                  key={pack.id}
                  pack={pack}
                  slotCount={config.addendum_slots.length}
                  busy={busy}
                  onEdit={() => openEditPack(pack)}
                  onDelete={() => onDeletePack(pack.id)}
                />
              ))}
            </div>
          )}
        </ConfigPanel>

        <ConfigPanel
          variant="nested"
          headingLevel={4}
          title={
            <span className="flex min-w-0 items-center gap-2">
              {t('skills.availableSlots')}
              <Badge variant="subtle">{config.addendum_slots.length}</Badge>
            </span>
          }
          description={t('skills.slotsDescription')}
        >
          <div className="mt-1 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {config.addendum_slots.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">{t('skills.noEmbeddableStages')}</p>
            ) : (
              config.addendum_slots.map((slot) => (
                <div key={slot.stage_id} className="border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-3">
                  <div className="text-sm font-medium text-[var(--text-primary)]">{slot.stage_label}</div>
                  <div translate="no" className="mt-1 break-all font-mono text-xs text-[var(--text-muted)]">{slot.stage_id}</div>
                </div>
              ))
            )}
          </div>
        </ConfigPanel>

        {drawerMode === 'create' ? (
          <SkillPackDrawer
            title="Create Business Flow Skill Pack"
            onClose={() => setDrawerMode(null)}
            footer={
              <button
                type="button"
                onClick={createPack}
                disabled={busy || !newPackId.trim() || !newPackLabel.trim()}
                className="inline-flex items-center justify-center rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                {busy ? 'Saving...' : 'Create Skill Pack'}
              </button>
            }
          >
            <SkillPackDrawerSection title="Basics" defaultOpen>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <TextInput
                  label="Pack ID"
                  value={newPackId}
                  onChange={setNewPackId}
                  placeholder="claims_qa"
                />
                <TextInput
                  label="Label"
                  value={newPackLabel}
                  onChange={setNewPackLabel}
                  placeholder="Claims QA"
                />
              </div>
              <div className="mt-4 flex items-center justify-between gap-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)]">
                <span>Default for unmatched admitted intents</span>
                <Switch
                  checked={newPackDefault}
                  onCheckedChange={setNewPackDefault}
                  aria-label="Default for unmatched admitted intents"
                />
              </div>
              <div className="mt-4">
                <TextArea
                  label="Description"
                  value={newPackDescription}
                  onChange={setNewPackDescription}
                  rows={3}
                />
              </div>
            </SkillPackDrawerSection>

            <SkillPackDrawerSection title="Routing" defaultOpen>
              <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
                <TextArea
                  label="Intent Patterns"
                  value={newPackIntentPatterns}
                  onChange={setNewPackIntentPatterns}
                  rows={5}
                  placeholder="One pattern per line"
                />
                <TextInput
                  label="Minimum Confidence"
                  type="number"
                  value={newPackMinConfidence}
                  onChange={setNewPackMinConfidence}
                />
              </div>
              <div className="mt-4">
                <TextArea
                  label="Intent Taxonomy Refs"
                  value={newPackIntentTaxonomyRefs}
                  onChange={setNewPackIntentTaxonomyRefs}
                  rows={2}
                  placeholder="One taxonomy ref per line"
                />
              </div>
            </SkillPackDrawerSection>

            <SkillPackDrawerSection title="Capability References">
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <ReferenceEditor label="Knowledge Bindings" value={newPackKnowledgeBindingRefs} onChange={setNewPackKnowledgeBindingRefs} />
                <ReferenceEditor label="Tool Contracts" value={newPackToolContractRefs} onChange={setNewPackToolContractRefs} />
                <ReferenceEditor label="Policy Rules" value={newPackPolicyRuleRefs} onChange={setNewPackPolicyRuleRefs} />
                <ReferenceEditor label="Validators" value={newPackValidatorRefs} onChange={setNewPackValidatorRefs} />
              </div>
            </SkillPackDrawerSection>

            <SkillPackDrawerSection title="Stage Addenda">
              <div className="mt-4 space-y-4">
                {config.addendum_slots.map((slot) => {
                  const stageDraft = newPackStages[slot.stage_id] ?? EMPTY_STAGE_DRAFT
                  return (
                    <div key={slot.stage_id} className="border border-[var(--border)] bg-[var(--bg-surface)] p-4">
                      <div>
                        <h5 className="text-sm font-semibold text-[var(--text-primary)]">{slot.stage_label}</h5>
                        <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{slot.stage_id}</p>
                      </div>
                      <div className="mt-4 grid gap-4 xl:grid-cols-3">
                        <TextArea
                          label={`${slot.stage_label} Business Context`}
                          value={stageDraft.businessContext}
                          onChange={(value) => patchNewStageDraft(slot.stage_id, { businessContext: value })}
                          rows={5}
                        />
                        <TextArea
                          label={`${slot.stage_label} Task Instructions`}
                          value={stageDraft.taskInstructions}
                          onChange={(value) => patchNewStageDraft(slot.stage_id, { taskInstructions: value })}
                          rows={5}
                        />
                        <TextArea
                          label={`${slot.stage_label} Output Preferences`}
                          value={stageDraft.outputPreferences}
                          onChange={(value) => patchNewStageDraft(slot.stage_id, { outputPreferences: value })}
                          rows={5}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </SkillPackDrawerSection>

            <SkillPackDrawerSection title="Preview">
              <NewSkillPackPreview
                packId={newPackId}
                label={newPackLabel}
                defaultPack={newPackDefault}
                intentPatterns={splitLines(newPackIntentPatterns)}
                minConfidence={newPackMinConfidence}
                knowledgeBindingRefs={splitLines(newPackKnowledgeBindingRefs)}
                toolContractRefs={splitLines(newPackToolContractRefs)}
                policyRuleRefs={splitLines(newPackPolicyRuleRefs)}
                validatorRefs={splitLines(newPackValidatorRefs)}
                addendumSlots={config.addendum_slots}
                stageDrafts={newPackStages}
              />
            </SkillPackDrawerSection>
          </SkillPackDrawer>
        ) : null}

        {drawerMode === 'edit' && selectedPack && draft ? (
          <SkillPackDrawer
            title="Edit Business Flow Skill Pack"
            onClose={() => setDrawerMode(null)}
            footer={
              <>
                <button
                  type="button"
                  onClick={deletePack}
                  disabled={busy}
                  className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm font-medium text-[var(--danger)] hover:bg-[var(--danger)]/15 disabled:opacity-50"
                >
                  Delete Skill Pack
                </button>
                <button
                  type="button"
                  onClick={savePack}
                  disabled={busy}
                  className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                >
                  {busy ? 'Saving...' : 'Save Skill Pack'}
                </button>
              </>
            }
          >
              <SkillPackDrawerSection title="Basics" defaultOpen>
                <div className="border-b border-[var(--border)] pb-4">
                  <p className="mt-1 break-all font-mono text-xs text-[var(--text-muted)]">
                    {selectedPack.definition}
                  </p>
                </div>

                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <TextInput label="Label" value={draft.label} onChange={(value) => patchDraft({ label: value })} />
                  <div className="flex items-center justify-between gap-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)]">
                    <span>Default for unmatched admitted intents</span>
                    <Switch
                      checked={draft.default}
                      onCheckedChange={(checked) => patchDraft({ default: checked })}
                      aria-label="Default for unmatched admitted intents"
                    />
                  </div>
                </div>
                <div className="mt-4">
                  <TextArea
                    label="Description"
                    value={draft.description}
                    onChange={(value) => patchDraft({ description: value })}
                    rows={3}
                  />
                </div>
              </SkillPackDrawerSection>

              <SkillPackDrawerSection title="Routing & Admission" defaultOpen>
                <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
                  <TextArea
                    label="Intent Patterns"
                    value={draft.intentPatterns}
                    onChange={(value) => patchDraft({ intentPatterns: value })}
                    rows={4}
                  />
                  <TextInput
                    label="Minimum Confidence"
                    type="number"
                    value={draft.minConfidence}
                    onChange={(value) => patchDraft({ minConfidence: value })}
                  />
                </div>
                <div className="mt-4">
                  <TextArea
                    label="Intent Taxonomy Refs"
                    value={draft.intentTaxonomyRefs}
                    onChange={(value) => patchDraft({ intentTaxonomyRefs: value })}
                    rows={2}
                  />
                </div>
                <div className="mt-4">
                  <h5 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Routing-Safe Summary
                  </h5>
                  <CodeBlock>{formatJson(selectedPack.routing_admission.routing_safe_summary)}</CodeBlock>
                </div>
              </SkillPackDrawerSection>

              <SkillPackDrawerSection title="Capability References">
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <ReferenceEditor label="Knowledge Bindings" value={draft.knowledgeBindingRefs} onChange={(value) => patchDraft({ knowledgeBindingRefs: value })} />
                  <ReferenceEditor label="Tool Contracts" value={draft.toolContractRefs} onChange={(value) => patchDraft({ toolContractRefs: value })} />
                  <ReferenceEditor label="Policy Rules" value={draft.policyRuleRefs} onChange={(value) => patchDraft({ policyRuleRefs: value })} />
                  <ReferenceEditor label="Validators" value={draft.validatorRefs} onChange={(value) => patchDraft({ validatorRefs: value })} />
                </div>
              </SkillPackDrawerSection>

              <SkillPackDrawerSection title="Stage Addendum Slots">
                <div className="mt-4 space-y-4">
                  {config.addendum_slots.map((slot) => {
                    const stageDraft = draft.stages[slot.stage_id] ?? EMPTY_STAGE_DRAFT
                    const projection = selectedPack.stage_addenda.find((stage) => stage.stage_id === slot.stage_id)
                    return (
                      <div key={slot.stage_id} className="border border-[var(--border)] bg-[var(--bg-surface)] p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <h5 className="text-sm font-semibold text-[var(--text-primary)]">{slot.stage_label}</h5>
                            <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{slot.stage_id}</p>
                          </div>
                          <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                            projection?.configured
                              ? 'bg-[var(--success)]/10 text-[var(--success)]'
                              : 'bg-[var(--bg-hover)] text-[var(--text-secondary)]'
                          }`}>
                            {projection?.configured ? 'Configured' : 'Empty'}
                          </span>
                        </div>
                        <div className="mt-4 grid gap-4 xl:grid-cols-3">
                          <TextArea
                            label={`${slot.stage_label} Business Context`}
                            value={stageDraft.businessContext}
                            onChange={(value) => patchStageDraft(slot.stage_id, { businessContext: value })}
                            rows={5}
                          />
                          <TextArea
                            label={`${slot.stage_label} Task Instructions`}
                            value={stageDraft.taskInstructions}
                            onChange={(value) => patchStageDraft(slot.stage_id, { taskInstructions: value })}
                            rows={5}
                          />
                          <TextArea
                            label={`${slot.stage_label} Output Preferences`}
                            value={stageDraft.outputPreferences}
                            onChange={(value) => patchStageDraft(slot.stage_id, { outputPreferences: value })}
                            rows={5}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </SkillPackDrawerSection>

              <SkillPackDrawerSection title="Prompt Preview">
                <div className="mt-4 grid gap-4 xl:grid-cols-2">
                  {selectedPack.stage_addenda.map((stage) => (
                    <div key={stage.stage_id} className="min-w-0 border border-[var(--border)] bg-[var(--bg-surface)] p-4">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <h5 className="text-sm font-semibold text-[var(--text-primary)]">{stage.stage_label}</h5>
                        <span className="rounded-full bg-[var(--bg-hover)] px-2 py-1 text-xs text-[var(--text-secondary)]">
                          {stage.preview.merge_mode}
                        </span>
                      </div>
                      <CodeBlock>{previewText(draftStagePreview(stage, draft.stages[stage.stage_id]))}</CodeBlock>
                    </div>
                  ))}
                </div>
              </SkillPackDrawerSection>
          </SkillPackDrawer>
        ) : null}
      </div>
    </div>
  )

  function patchDraft(patch: Partial<PackDraft>) {
    setDraft((current) => current ? { ...current, ...patch } : current)
  }

  function patchStageDraft(stageId: string, patch: Partial<StageDraft>) {
    setDraft((current) => {
      if (!current) return current
      return {
        ...current,
        stages: {
          ...current.stages,
          [stageId]: {
            ...(current.stages[stageId] ?? EMPTY_STAGE_DRAFT),
            ...patch,
          },
        },
      }
    })
  }
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 truncate font-mono text-xs text-[var(--text-primary)]">{value}</div>
    </div>
  )
}

function SkillPackDrawer({
  title,
  children,
  footer,
  onClose,
}: {
  title: string
  children: ReactNode
  footer: ReactNode
  onClose: () => void
}) {
  return (
    <AgentDetailDrawer
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title={title}
      description="Configure the Pack without leaving the Business Flow Skill Packs list."
      footer={footer}
      bodyClassName="space-y-4"
    >
      {children}
    </AgentDetailDrawer>
  )
}

function SkillPackDrawerSection({
  title,
  children,
  defaultOpen = false,
}: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const contentId = useId()
  return (
    <section className="border border-[var(--border)] bg-[var(--bg-base)]">
      <button
        type="button"
        aria-label={title}
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[var(--bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          {title}
        </span>
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`h-4 w-4 shrink-0 text-[var(--text-muted)] transition-transform ${
            open ? 'rotate-180' : ''
          }`}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open ? (
        <div id={contentId} className="border-t border-[var(--border)] p-4">
          {children}
        </div>
      ) : null}
    </section>
  )
}

function SkillPackListRow({
  pack,
  slotCount,
  busy,
  onEdit,
  onDelete,
}: {
  pack: BusinessFlowSkillPackProjection
  slotCount: number
  busy: boolean
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <article className="border border-[var(--border)] bg-[var(--bg-surface)] p-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_168px] xl:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h5 className="min-w-0 text-sm font-semibold text-[var(--text-primary)]">
              {pack.label}
            </h5>
            {pack.default ? (
              <Badge variant="success" className="shrink-0">Default</Badge>
            ) : null}
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-[var(--text-muted)]">
            <span translate="no" className="break-all">{pack.id}</span>
            <span translate="no" className="break-all">{pack.definition}</span>
          </div>
          {pack.description ? (
            <p className="mt-2 min-w-0 break-words text-sm text-[var(--text-muted)]">
              {pack.description}
            </p>
          ) : null}
        </div>
        <div className="grid grid-cols-2 gap-2 xl:w-[168px]">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onEdit}
          >
            Edit
          </Button>
          <Button
            type="button"
            variant="destructive-outline"
            size="sm"
            onClick={onDelete}
            disabled={busy}
          >
            Delete
          </Button>
        </div>
      </div>

      <div className="mt-4">
        <KeyValueList
          variant="inline"
          items={[
            { label: 'Intent', value: formatIntentPreview(pack), kind: 'text' },
            {
              label: 'Stages',
              value: formatStageCoverage(pack, slotCount),
              kind: 'text',
            },
            {
              label: 'Refs',
              value: formatCapabilityCounts(pack),
              kind: 'text',
            },
            {
              label: 'Admission',
              value: formatAdmissionSummary(pack),
              kind: 'text',
            },
          ]}
        />
      </div>
    </article>
  )
}

function SkillPackSummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2">
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-1 break-words text-sm text-[var(--text-primary)]">{value}</dd>
    </div>
  )
}

function NewSkillPackPreview({
  packId,
  label,
  defaultPack,
  intentPatterns,
  minConfidence,
  knowledgeBindingRefs,
  toolContractRefs,
  policyRuleRefs,
  validatorRefs,
  addendumSlots,
  stageDrafts,
}: {
  packId: string
  label: string
  defaultPack: boolean
  intentPatterns: string[]
  minConfidence: string
  knowledgeBindingRefs: string[]
  toolContractRefs: string[]
  policyRuleRefs: string[]
  validatorRefs: string[]
  addendumSlots: BusinessFlowSkillPackConfiguration['addendum_slots']
  stageDrafts: Record<string, StageDraft>
}) {
  const configuredSlots = addendumSlots.filter((slot) => isStageDraftConfigured(stageDrafts[slot.stage_id]))
  return (
    <div className="space-y-4">
      <section className="border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h5 className="text-sm font-semibold text-[var(--text-primary)]">Routing-Safe Preview</h5>
        <dl className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <SkillPackSummaryItem label="Pack ID" value={packId.trim() || 'Not set'} />
          <SkillPackSummaryItem label="Label" value={label.trim() || 'Not set'} />
          <SkillPackSummaryItem label="Routing" value={formatIntentPatternCount(intentPatterns)} />
          <SkillPackSummaryItem label="Admission" value={formatMinConfidence(minConfidence)} />
          <SkillPackSummaryItem label="Default" value={defaultPack ? 'Yes' : 'No'} />
          <SkillPackSummaryItem
            label="Capability References"
            value={formatCapabilityCountValues({
              knowledge_binding_refs: knowledgeBindingRefs,
              tool_contract_refs: toolContractRefs,
              policy_rule_refs: policyRuleRefs,
              validator_refs: validatorRefs,
            })}
          />
        </dl>
      </section>

      <section className="border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h5 className="text-sm font-semibold text-[var(--text-primary)]">Affected Addendum Slots</h5>
        {configuredSlots.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--text-muted)]">No addendum slots configured.</p>
        ) : (
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {configuredSlots.map((slot) => (
              <div key={slot.stage_id} className="border border-[var(--border)] bg-[var(--bg-base)] px-3 py-3">
                <div className="text-sm font-medium text-[var(--text-primary)]">{slot.stage_label}</div>
                <div className="mt-1 break-all font-mono text-xs text-[var(--text-muted)]">{slot.stage_id}</div>
                <div className="mt-2 text-xs text-[var(--text-secondary)]">append-only addendum configured</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <p className="text-sm text-[var(--text-muted)]">
        This preview is deterministic and does not call a model, run retrieval, execute tools, or write run trace.
      </p>
    </div>
  )
}

function formatIntentPreview(pack: BusinessFlowSkillPackProjection): string {
  const patterns = pack.routing_admission.intent_patterns
  if (patterns.length === 0) return 'No intent patterns'
  if (patterns.length === 1) return patterns[0]
  return `${patterns[0]} + ${patterns.length - 1} more`
}

function formatIntentPatternCount(patterns: string[]): string {
  if (patterns.length === 0) return 'No intent patterns'
  if (patterns.length === 1) return '1 intent pattern'
  return `${patterns.length} intent patterns`
}

function formatStageCoverage(pack: BusinessFlowSkillPackProjection, slotCount: number): string {
  return `${pack.coverage.configured_stage_ids.length}/${slotCount} stages configured`
}

function formatCapabilityCounts(pack: BusinessFlowSkillPackProjection): string {
  return formatCapabilityCountValues(pack.capability_refs)
}

function formatCapabilityCountValues(refs: {
  knowledge_binding_refs: string[]
  tool_contract_refs: string[]
  policy_rule_refs: string[]
  validator_refs: string[]
}): string {
  return [
    `${refs.knowledge_binding_refs.length} knowledge`,
    `${refs.tool_contract_refs.length} tools`,
    `${refs.policy_rule_refs.length} policy`,
    `${refs.validator_refs.length} validators`,
  ].join(' / ')
}

function formatMinConfidence(value: string): string {
  const trimmed = value.trim()
  return trimmed ? `min confidence ${trimmed}` : 'No admission threshold'
}

function isStageDraftConfigured(stageDraft: StageDraft | undefined): boolean {
  if (!stageDraft) return false
  return Boolean(
    stageDraft.businessContext.trim() ||
      splitLines(stageDraft.taskInstructions).length > 0 ||
      splitLines(stageDraft.outputPreferences).length > 0,
  )
}

function formatAdmissionSummary(pack: BusinessFlowSkillPackProjection): string {
  const minConfidence = pack.routing_admission.admission.min_confidence
  if (typeof minConfidence === 'number' || typeof minConfidence === 'string') {
    return `min confidence ${minConfidence}`
  }
  return 'No admission threshold'
}

function TextInput({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  type?: 'text' | 'number'
}) {
  const generatedId = useId()
  const fieldId = `skills-${generatedId}`
  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </label>
      <input
        id={fieldId}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
      />
    </div>
  )
}

function TextArea({
  label,
  value,
  onChange,
  rows,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows: number
  placeholder?: string
}) {
  const generatedId = useId()
  const fieldId = `skills-${generatedId}`
  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </label>
      <textarea
        id={fieldId}
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full resize-y rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
      />
    </div>
  )
}

function ReferenceEditor({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  const refs = splitLines(value)
  return (
    <div>
      <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </label>
      <ReferenceChips
        values={refs}
        onChange={(next) => onChange(next.join('\n'))}
        ariaLabel={label}
        placeholder={`Add a ${label.toLowerCase().replace(/s$/, '')} reference and press Enter`}
      />
    </div>
  )
}

function packToDraft(pack: BusinessFlowSkillPackProjection, config: BusinessFlowSkillPackConfiguration): PackDraft {
  const stages = Object.fromEntries(
    config.addendum_slots.map((slot) => {
      const addendum = pack.stage_addenda.find((stage) => stage.stage_id === slot.stage_id)
      return [
        slot.stage_id,
        {
          businessContext: stringValue(addendum?.prompt.business_context),
          taskInstructions: linesValue(addendum?.prompt.task_instructions),
          outputPreferences: linesValue(addendum?.prompt.output_preferences),
        },
      ]
    }),
  )

  return {
    label: pack.label,
    description: pack.description,
    intentPatterns: linesValue(pack.routing_admission.intent_patterns),
    intentTaxonomyRefs: linesValue(pack.routing_admission.intent_taxonomy_refs),
    admission: pack.routing_admission.admission,
    minConfidence: stringValue(pack.routing_admission.admission.min_confidence),
    knowledgeBindingRefs: linesValue(pack.capability_refs.knowledge_binding_refs),
    toolContractRefs: linesValue(pack.capability_refs.tool_contract_refs),
    policyRuleRefs: linesValue(pack.capability_refs.policy_rule_refs),
    validatorRefs: linesValue(pack.capability_refs.validator_refs),
    default: pack.default,
    stages,
  }
}

function draftToUpdatePayload(draft: PackDraft): BusinessFlowSkillPackUpdateRequest {
  const admission: Record<string, unknown> = { ...draft.admission }
  delete admission.min_confidence
  const minConfidence = Number(draft.minConfidence)
  if (draft.minConfidence.trim() && Number.isFinite(minConfidence)) {
    admission.min_confidence = minConfidence
  }

  return {
    label: draft.label.trim(),
    description: draft.description.trim(),
    intent_patterns: splitLines(draft.intentPatterns),
    intent_taxonomy_refs: splitLines(draft.intentTaxonomyRefs),
    stage_prompt_addenda: stageDraftsToPromptConfig(draft.stages),
    knowledge_binding_refs: splitLines(draft.knowledgeBindingRefs),
    tool_contract_refs: splitLines(draft.toolContractRefs),
    policy_rule_refs: splitLines(draft.policyRuleRefs),
    validator_refs: splitLines(draft.validatorRefs),
    admission,
    default: draft.default,
  }
}

function hasSupplementalCreateUpdate(payload: BusinessFlowSkillPackUpdateRequest): boolean {
  return Boolean(
    Object.keys(payload.admission ?? {}).length > 0 ||
      Object.keys(payload.stage_prompt_addenda ?? {}).length > 0 ||
      (payload.knowledge_binding_refs?.length ?? 0) > 0 ||
      (payload.tool_contract_refs?.length ?? 0) > 0 ||
      (payload.policy_rule_refs?.length ?? 0) > 0 ||
      (payload.validator_refs?.length ?? 0) > 0,
  )
}

function stageDraftsToPromptConfig(stages: Record<string, StageDraft>): Record<string, WorkflowStagePromptConfig> {
  return Object.fromEntries(
    Object.entries(stages)
      .map(([stageId, stageDraft]) => {
        const prompt = {
          business_context: stageDraft.businessContext.trim(),
          task_instructions: splitLines(stageDraft.taskInstructions),
          output_preferences: splitLines(stageDraft.outputPreferences),
        }
        return [stageId, prompt] as const
      })
      .filter(([, prompt]) =>
        Boolean(
          prompt.business_context ||
            prompt.task_instructions.length > 0 ||
            prompt.output_preferences.length > 0,
        ),
      ),
  )
}

function previewText(preview: {
  business_context: string
  task_instructions: string[]
  output_preferences: string[]
}) {
  const sections = [
    preview.business_context ? `Business Context\n${preview.business_context}` : '',
    preview.task_instructions.length > 0 ? `Task Instructions\n${preview.task_instructions.map((item) => `- ${item}`).join('\n')}` : '',
    preview.output_preferences.length > 0 ? `Output Preferences\n${preview.output_preferences.map((item) => `- ${item}`).join('\n')}` : '',
  ].filter(Boolean)
  return sections.join('\n\n') || 'No prompt addendum configured.'
}

function draftStagePreview(
  stage: BusinessFlowSkillPackProjection['stage_addenda'][number],
  stageDraft: StageDraft | undefined,
): {
  business_context: string
  task_instructions: string[]
  output_preferences: string[]
} {
  if (!stageDraft) return stage.preview
  return {
    business_context: replaceTextAddendum(
      stage.preview.business_context,
      stringValue(stage.prompt.business_context),
      stageDraft.businessContext,
    ),
    task_instructions: replaceListAddendum(
      stage.preview.task_instructions,
      splitLines(linesValue(stage.prompt.task_instructions)),
      splitLines(stageDraft.taskInstructions),
    ),
    output_preferences: replaceListAddendum(
      stage.preview.output_preferences,
      splitLines(linesValue(stage.prompt.output_preferences)),
      splitLines(stageDraft.outputPreferences),
    ),
  }
}

function replaceTextAddendum(basePlusAddendum: string, originalAddendum: string, draftAddendum: string): string {
  const base = removeTextSuffix(basePlusAddendum, originalAddendum)
  return [base, draftAddendum.trim()].filter(Boolean).join('\n\n')
}

function removeTextSuffix(value: string, suffix: string): string {
  const trimmedValue = value.trim()
  const trimmedSuffix = suffix.trim()
  if (!trimmedSuffix || !trimmedValue.endsWith(trimmedSuffix)) return trimmedValue
  return trimmedValue.slice(0, trimmedValue.length - trimmedSuffix.length).trim()
}

function replaceListAddendum(basePlusAddendum: string[], originalAddendum: string[], draftAddendum: string[]): string[] {
  return [...removeListSuffix(basePlusAddendum, originalAddendum), ...draftAddendum]
}

function removeListSuffix(value: string[], suffix: string[]): string[] {
  if (suffix.length === 0 || suffix.length > value.length) return value
  const offset = value.length - suffix.length
  const suffixMatches = suffix.every((item, index) => value[offset + index] === item)
  return suffixMatches ? value.slice(0, offset) : value
}

function formatJson(value: Record<string, unknown>): string {
  return Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : '{}'
}

function splitLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function linesValue(value: unknown): string {
  return Array.isArray(value) ? value.map((item) => String(item)).join('\n') : ''
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

export type { SkillsModuleEditorProps }
