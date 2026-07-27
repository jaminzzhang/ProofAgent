// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchReleases } from '../../api/client'
import { useSession } from '../../auth/session'
import { Sidebar } from '../../components/Sidebar'
import { ReleasesPage } from '../ReleasesPage'

vi.mock('../../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/client')>()
  return { ...original, fetchReleases: vi.fn() }
})
vi.mock('../../auth/session', () => ({ useSession: vi.fn() }))


describe('ReleasesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useSession).mockReturnValue({
      session: null,
      status: 'authenticated',
      hasPermission: (permission: string) => permission === 'audit.export',
    })
    vi.mocked(fetchReleases).mockResolvedValue({
      releases: [
        {
          release_id: 'proofagent-2026.07.25-rc1',
          state: 'FINALIZED',
          candidate_binding_sha256: 'a'.repeat(64),
          created_at: '2026-07-25T08:00:00+00:00',
          finalized_at: '2026-07-25T08:30:00+00:00',
          bundle_available: true,
          artifact_names: [
            'release-bundle-index.json',
            'release-readiness-report.html',
          ],
        },
        {
          release_id: 'proofagent-2026.07.26-rc1',
          state: 'PREPARING',
          candidate_binding_sha256: 'b'.repeat(64),
          created_at: '2026-07-26T08:00:00+00:00',
          finalized_at: null,
          bundle_available: false,
          artifact_names: [],
        },
      ],
    })
  })

  it('adds Releases to monitoring navigation', () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: 'Releases' })).toHaveAttribute(
      'href',
      '/releases',
    )
  })

  it('lists lifecycle state and exact authenticated artifact links', async () => {
    render(
      <MemoryRouter>
        <ReleasesPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('proofagent-2026.07.25-rc1')).toBeInTheDocument()
    expect(screen.getByText('proofagent-2026.07.26-rc1')).toBeInTheDocument()
    expect(screen.getByText('FINALIZED')).toBeInTheDocument()
    expect(screen.getByText('PREPARING')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'release-bundle-index.json' })).toHaveAttribute(
      'href',
      '/api/releases/proofagent-2026.07.25-rc1/bundle/release-bundle-index.json',
    )
    expect(
      screen.getByRole('link', { name: 'release-readiness-report.html' }),
    ).toHaveAttribute(
      'href',
      '/api/releases/proofagent-2026.07.25-rc1/bundle/release-readiness-report.html',
    )
    expect(screen.getByText('Bundle finalization is still in progress.')).toBeInTheDocument()
  })

  it('does not query or expose downloads without audit.export', () => {
    vi.mocked(useSession).mockReturnValue({
      session: null,
      status: 'authenticated',
      hasPermission: () => false,
    })

    render(
      <MemoryRouter>
        <ReleasesPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('You do not have permission to export release bundles.')).toBeInTheDocument()
    expect(fetchReleases).not.toHaveBeenCalled()
  })
})
