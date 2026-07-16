// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchEgressPolicies,
  fetchPermissionMappings,
  createPermissionMapping,
} from '../../api/client'
import { useSession } from '../../auth/session'
import { SecurityPage } from '../SecurityPage'

vi.mock('../../api/client', () => ({
  activateEgressPolicy: vi.fn(),
  activatePermissionMapping: vi.fn(),
  createEgressPolicy: vi.fn(),
  createPermissionMapping: vi.fn(),
  fetchEgressPolicies: vi.fn(),
  fetchPermissionMappings: vi.fn(),
  validateSecretHandle: vi.fn(),
}))
vi.mock('../../auth/session', () => ({ useSession: vi.fn() }))

const mappingResponse = {
  active: null,
  versions: [{
    version_id: 'mapping-v1', revision: 1, rules: [], created_at: '2026-07-15T00:00:00Z', created_by: 'admin',
  }],
  recovery_mapping: {
    claim_path: 'groups', group_name: 'proof-agent-recovery', permissions: ['permission_mapping.edit'],
  },
  permission_epoch: 0,
}

describe('SecurityPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchPermissionMappings).mockResolvedValue(mappingResponse)
    vi.mocked(fetchEgressPolicies).mockResolvedValue({
      active: null,
      versions: [{
        version_id: 'egress-v1', revision: 1, rules: [], created_at: '2026-07-15T00:00:00Z', created_by: 'admin',
      }],
    })
  })

  it('shows immutable Recovery mapping but hides mutation controls without edit permission', async () => {
    vi.mocked(useSession).mockReturnValue({
      session: null,
      status: 'authenticated',
      hasPermission: (permission: string) => [
        'permission_mapping.view', 'egress_policy.view',
      ].includes(permission),
    })

    render(<SecurityPage />)

    expect(await screen.findByText('proof-agent-recovery')).toBeInTheDocument()
    expect(screen.getByText('immutable')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Activate' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Handle ID')).not.toBeInTheDocument()
  })

  it('shows direct activation and Secret Handle metadata validation with permissions', async () => {
    vi.mocked(useSession).mockReturnValue({
      session: null,
      status: 'authenticated',
      hasPermission: () => true,
    })

    render(<SecurityPage />)

    expect((await screen.findAllByRole('button', { name: 'Activate' })).length).toBe(2)
    expect(screen.getByLabelText('Handle ID')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Validate metadata' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'New mapping version' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New egress policy' })).toBeInTheDocument()
  })

  it('creates an ordinary permission mapping directly without changing Recovery mapping', async () => {
    vi.mocked(useSession).mockReturnValue({
      session: null,
      status: 'authenticated',
      hasPermission: () => true,
    })
    vi.mocked(createPermissionMapping).mockResolvedValue(mappingResponse.versions[0])
    render(<SecurityPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'New mapping version' }))
    fireEvent.change(screen.getByLabelText('Permission mapping version ID'), {
      target: { value: 'mapping-v2' },
    })
    fireEvent.change(screen.getByLabelText('Permission rules JSON'), {
      target: { value: '[{"claim_path":"groups","claim_value":"agents","permissions":["run.view"]}]' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save mapping version' }))

    await waitFor(() => expect(createPermissionMapping).toHaveBeenCalledWith({
      version_id: 'mapping-v2',
      expected_revision: 1,
      rules: [{ claim_path: 'groups', claim_value: 'agents', permissions: ['run.view'] }],
    }))
  })
})
