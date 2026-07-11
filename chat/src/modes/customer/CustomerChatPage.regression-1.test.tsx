/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import type { CustomerConversation, CustomerRunResponse } from '../../api/types'
import { CustomerChatPage } from './CustomerChatPage'
import {
  createCustomerConversation,
  createCustomerRun,
  fetchCustomerAgents,
  fetchCustomerConversation,
} from './customerAdapter'

// ISSUE-009 regression from
// .gstack/qa-reports/qa-report-proofagent-local-2026-07-11.md
vi.mock('./customerAdapter', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./customerAdapter')>()
  return {
    ...actual,
    createCustomerConversation: vi.fn(),
    createCustomerRun: vi.fn(),
    fetchCustomerAgents: vi.fn(),
    fetchCustomerConversation: vi.fn(),
  }
})

const mockedCreateCustomerConversation = vi.mocked(createCustomerConversation)
const mockedCreateCustomerRun = vi.mocked(createCustomerRun)
const mockedFetchCustomerAgents = vi.mocked(fetchCustomerAgents)
const mockedFetchCustomerConversation = vi.mocked(fetchCustomerConversation)

describe('CustomerChatPage ISSUE-009 regressions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedFetchCustomerAgents.mockResolvedValue({
      data: [
        {
          agent_id: 'agent-1',
          display_name: 'Customer Agent',
          purpose: 'Customer-safe support.',
          agent_version_id: 'version-1',
          customer_facing: true,
        },
      ],
      meta: { total: 1 },
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  test.each([
    [null, 'Guest', 'Anonymous'],
    ['CUST-001', 'Demo 1', 'CUST-001'],
    ['CUST-002', 'Demo 2', 'CUST-002'],
  ] as const)(
    'restores customer mode from a deep-linked server record (%s)',
    async (customerId, modeLabel, customerLabel) => {
      mockedFetchCustomerConversation.mockResolvedValue(
        customerConversation('conversation-1', customerId),
      )

      renderCustomerRoute('/customer/c/conversation-1')

      await waitFor(() => {
        expect(mockedFetchCustomerConversation).toHaveBeenCalledWith('conversation-1')
      })
      expect(screen.getByText(customerLabel)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: modeLabel })).toHaveClass('text-[var(--accent)]')
    },
  )

  test('fails closed for an unsupported deep-linked customer identity', async () => {
    mockedFetchCustomerConversation.mockResolvedValue(
      customerConversation('conversation-1', 'CUST-999'),
    )

    renderCustomerRoute('/customer/c/conversation-1')

    expect(
      await screen.findByText('The conversation is unavailable. Please start a new session.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('CUST-999')).not.toBeInTheDocument()
  })

  test('does not run when a created conversation identity diverges from the active UI mode', async () => {
    mockedCreateCustomerConversation.mockResolvedValue(
      customerConversation('conversation-created', 'CUST-001'),
    )
    mockedCreateCustomerRun.mockResolvedValue(customerRun('conversation-created'))
    mockedFetchCustomerConversation.mockResolvedValue(
      customerConversation('conversation-created', 'CUST-001'),
    )

    renderCustomerRoute('/customer/agents/agent-1')

    await screen.findByPlaceholderText('Ask about a policy, claim, or reimbursement')
    fireEvent.click(screen.getByRole('button', { name: 'Demo 2' }))
    expect(await screen.findByText('CUST-002')).toBeInTheDocument()
    const input = await screen.findByPlaceholderText('Ask about a policy, claim, or reimbursement')
    fireEvent.change(input, { target: { value: 'Where is my claim?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(mockedCreateCustomerConversation).toHaveBeenCalledWith('agent-1', 'CUST-002')
    })
    await waitFor(() => {
      expect(screen.getByText('The service is unavailable. Please try again.')).toBeInTheDocument()
    })
    expect(mockedCreateCustomerRun).not.toHaveBeenCalled()
    expect(screen.getByText('Anonymous')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Guest' })).toHaveClass('text-[var(--accent)]')
    expect(screen.queryByText('CUST-002')).not.toBeInTheDocument()
  })

  test.each([
    {
      name: 'customer identity',
      mutate: (record: CustomerConversation) => {
        record.customer_id = 'CUST-002'
      },
    },
    {
      name: 'conversation route',
      mutate: (record: CustomerConversation) => {
        record.conversation_id = 'different-conversation'
      },
    },
  ])('fails closed before an existing run when $name becomes stale', async ({ mutate }) => {
    const record = customerConversation(
      'conversation-1',
      'CUST-001',
      'Previously authorized answer',
    )
    mockedFetchCustomerConversation.mockResolvedValue(record)
    mockedCreateCustomerRun.mockResolvedValue(customerRun('conversation-1'))

    renderCustomerRoute('/customer/c/conversation-1')
    expect(await screen.findByText('Previously authorized answer')).toBeInTheDocument()
    expect(screen.getByText('CUST-001')).toBeInTheDocument()

    mutate(record)
    const input = screen.getByPlaceholderText('Ask about a policy, claim, or reimbursement')
    fireEvent.change(input, { target: { value: 'Do not run stale state' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(
      await screen.findByText('The service is unavailable. Please try again.'),
    ).toBeInTheDocument()
    expect(mockedCreateCustomerRun).not.toHaveBeenCalled()
    expect(screen.queryByText('Previously authorized answer')).not.toBeInTheDocument()
    expect(screen.getByText('Anonymous')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Guest' })).toHaveClass('text-[var(--accent)]')
  })

  test('fails closed when the fetched record id differs from the active route', async () => {
    mockedFetchCustomerConversation.mockResolvedValue(
      customerConversation('different-conversation', 'CUST-001'),
    )

    renderCustomerRoute('/customer/c/conversation-1')

    expect(
      await screen.findByText('The conversation is unavailable. Please start a new session.'),
    ).toBeInTheDocument()
    expect(mockedCreateCustomerRun).not.toHaveBeenCalled()
  })

  test('runs an existing conversation only with its route-bound server identity', async () => {
    mockedFetchCustomerConversation.mockResolvedValue(
      customerConversation('conversation-1', 'CUST-001', 'Existing answer'),
    )
    mockedCreateCustomerRun.mockResolvedValue(customerRun('conversation-1'))

    renderCustomerRoute('/customer/c/conversation-1')

    expect(await screen.findByText('CUST-001')).toBeInTheDocument()
    const input = screen.getByPlaceholderText('Ask about a policy, claim, or reimbursement')
    fireEvent.change(input, { target: { value: 'Where is my claim?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(mockedCreateCustomerRun).toHaveBeenCalledWith(
        'conversation-1',
        'Where is my claim?',
        { allowUntrustedWebSupplement: false },
      )
    })
  })

  test('ignores an older deep-link response that finishes after a newer route', async () => {
    const firstLoad = deferred<CustomerConversation>()
    const secondLoad = deferred<CustomerConversation>()
    mockedFetchCustomerConversation.mockImplementation((conversationId) => {
      if (conversationId === 'conversation-1') return firstLoad.promise
      if (conversationId === 'conversation-2') return secondLoad.promise
      throw new Error(`Unexpected conversation ${conversationId}`)
    })

    renderCustomerRoute('/customer/c/conversation-1')
    await waitFor(() => {
      expect(mockedFetchCustomerConversation).toHaveBeenCalledWith('conversation-1')
    })
    fireEvent.click(screen.getByRole('button', { name: 'navigate /customer/c/conversation-2' }))
    await waitFor(() => {
      expect(mockedFetchCustomerConversation).toHaveBeenCalledWith('conversation-2')
    })

    await act(async () => {
      secondLoad.resolve(customerConversation('conversation-2', 'CUST-002', 'New route answer'))
      await secondLoad.promise
    })
    expect(await screen.findByText('New route answer')).toBeInTheDocument()

    await act(async () => {
      firstLoad.resolve(customerConversation('conversation-1', 'CUST-001', 'Stale answer'))
      await firstLoad.promise
    })
    expect(screen.queryByText('Stale answer')).not.toBeInTheDocument()
    expect(screen.getByText('New route answer')).toBeInTheDocument()
    expect(screen.getByText('CUST-002')).toBeInTheDocument()
  })

  test('ignores an older deep-link rejection after a newer route is active', async () => {
    const firstLoad = deferred<CustomerConversation>()
    mockedFetchCustomerConversation.mockImplementation((conversationId) => {
      if (conversationId === 'conversation-1') return firstLoad.promise
      return Promise.resolve(
        customerConversation('conversation-2', 'CUST-002', 'Current route answer'),
      )
    })

    renderCustomerRoute('/customer/c/conversation-1')
    await waitFor(() => {
      expect(mockedFetchCustomerConversation).toHaveBeenCalledWith('conversation-1')
    })
    fireEvent.click(screen.getByRole('button', { name: 'navigate /customer/c/conversation-2' }))
    expect(await screen.findByText('Current route answer')).toBeInTheDocument()

    await act(async () => {
      firstLoad.reject(new Error('obsolete load failed'))
      await firstLoad.promise.catch(() => undefined)
    })

    expect(screen.getByText('Current route answer')).toBeInTheDocument()
    expect(screen.getByText('CUST-002')).toBeInTheDocument()
    expect(
      screen.queryByText('The conversation is unavailable. Please start a new session.'),
    ).not.toBeInTheDocument()
  })

  test('clears a loaded conversation before a missing replacement route resolves', async () => {
    const missingLoad = deferred<CustomerConversation>()
    mockedFetchCustomerConversation.mockImplementation((conversationId) => {
      if (conversationId === 'conversation-1') {
        return Promise.resolve(
          customerConversation('conversation-1', 'CUST-001', 'Private old answer'),
        )
      }
      return missingLoad.promise
    })

    renderCustomerRoute('/customer/c/conversation-1')
    expect(await screen.findByText('Private old answer')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'navigate /customer/c/missing' }))
    await waitFor(() => {
      expect(mockedFetchCustomerConversation).toHaveBeenCalledWith('missing')
    })
    expect(screen.queryByText('Private old answer')).not.toBeInTheDocument()
    expect(screen.getByText('Anonymous')).toBeInTheDocument()

    await act(async () => {
      missingLoad.reject(new Error('missing'))
      await missingLoad.promise.catch(() => undefined)
    })
    expect(
      await screen.findByText('The conversation is unavailable. Please start a new session.'),
    ).toBeInTheDocument()
    expect(mockedCreateCustomerRun).not.toHaveBeenCalled()
  })

  test('clears a loaded conversation before a different route resolves', async () => {
    const differentLoad = deferred<CustomerConversation>()
    mockedFetchCustomerConversation.mockImplementation((conversationId) => {
      if (conversationId === 'conversation-1') {
        return Promise.resolve(
          customerConversation('conversation-1', 'CUST-001', 'Private old answer'),
        )
      }
      return differentLoad.promise
    })

    renderCustomerRoute('/customer/c/conversation-1')
    expect(await screen.findByText('Private old answer')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'navigate /customer/c/conversation-2' }))
    await waitFor(() => {
      expect(mockedFetchCustomerConversation).toHaveBeenCalledWith('conversation-2')
    })
    expect(screen.queryByText('Private old answer')).not.toBeInTheDocument()
    expect(screen.getByText('Anonymous')).toBeInTheDocument()

    await act(async () => {
      differentLoad.resolve(
        customerConversation('conversation-2', 'CUST-002', 'Different route answer'),
      )
      await differentLoad.promise
    })
    expect(await screen.findByText('Different route answer')).toBeInTheDocument()
    expect(screen.getByText('CUST-002')).toBeInTheDocument()
  })

  test.each(['/customer', '/customer/new', '/customer/agents/agent-1'])(
    'clears server conversation state when navigating to %s',
    async (target) => {
      mockedFetchCustomerConversation.mockResolvedValue(
        customerConversation('conversation-1', 'CUST-001', 'Private old answer'),
      )

      renderCustomerRoute('/customer/c/conversation-1')
      expect(await screen.findByText('Private old answer')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: `navigate ${target}` }))

      await waitFor(() => {
        expect(screen.getByTestId('customer-location')).toHaveTextContent(target)
      })
      expect(screen.queryByText('Private old answer')).not.toBeInTheDocument()
      expect(await screen.findByText('Anonymous')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Guest' })).toHaveClass('text-[var(--accent)]')
      expect(mockedCreateCustomerRun).not.toHaveBeenCalled()
    },
  )

  test('preserves the first submission through a controlled new-conversation binding', async () => {
    const updated = customerConversation('conversation-created', null)
    mockedCreateCustomerConversation.mockResolvedValue(
      customerConversation('conversation-created', null),
    )
    mockedCreateCustomerRun.mockResolvedValue(customerRun('conversation-created'))
    mockedFetchCustomerConversation.mockResolvedValue(updated)

    renderCustomerRoute('/customer/agents/agent-1')
    await submitQuestion('What is covered?')

    await waitFor(() => {
      expect(mockedCreateCustomerRun).toHaveBeenCalledWith(
        'conversation-created',
        'What is covered?',
        { allowUntrustedWebSupplement: false },
      )
    })
    await waitFor(() => {
      expect(screen.getByTestId('customer-location')).toHaveTextContent(
        '/customer/c/conversation-created',
      )
    })
    expect(await screen.findByText('Answer')).toBeInTheDocument()
  })

  test('does not start a run when create completes after navigation', async () => {
    const create = deferred<CustomerConversation>()
    mockedCreateCustomerConversation.mockReturnValue(create.promise)

    renderCustomerRoute('/customer/agents/agent-1')
    await submitQuestion('Do not reuse me')
    await waitFor(() => {
      expect(mockedCreateCustomerConversation).toHaveBeenCalledOnce()
    })

    fireEvent.click(screen.getByRole('button', { name: 'navigate /customer' }))
    await act(async () => {
      create.resolve(customerConversation('conversation-created', null))
      await create.promise
    })

    expect(mockedCreateCustomerRun).not.toHaveBeenCalled()
    await expectCleanGuestRoute('/customer')
  })

  test('does not refresh or write state when run completes after navigation', async () => {
    const run = deferred<CustomerRunResponse>()
    mockedCreateCustomerConversation.mockResolvedValue(
      customerConversation('conversation-created', null),
    )
    mockedCreateCustomerRun.mockReturnValue(run.promise)

    renderCustomerRoute('/customer/agents/agent-1')
    await submitQuestion('Do not refresh me')
    await waitFor(() => {
      expect(mockedCreateCustomerRun).toHaveBeenCalledOnce()
    })

    fireEvent.click(screen.getByRole('button', { name: 'navigate /customer' }))
    await act(async () => {
      run.resolve(customerRun('conversation-created'))
      await run.promise
    })

    expect(mockedFetchCustomerConversation).not.toHaveBeenCalled()
    await expectCleanGuestRoute('/customer')
  })

  test('does not write or navigate when refresh completes after navigation', async () => {
    const refresh = deferred<CustomerConversation>()
    mockedCreateCustomerConversation.mockResolvedValue(
      customerConversation('conversation-created', null),
    )
    mockedCreateCustomerRun.mockResolvedValue(customerRun('conversation-created'))
    mockedFetchCustomerConversation.mockReturnValue(refresh.promise)

    renderCustomerRoute('/customer/agents/agent-1')
    await submitQuestion('Do not restore me')
    await waitFor(() => {
      expect(mockedFetchCustomerConversation).toHaveBeenCalledWith('conversation-created')
    })

    fireEvent.click(screen.getByRole('button', { name: 'navigate /customer' }))
    await act(async () => {
      refresh.resolve(
        customerConversation('conversation-created', null, 'Obsolete refreshed answer'),
      )
      await refresh.promise
    })

    expect(screen.queryByText('Obsolete refreshed answer')).not.toBeInTheDocument()
    await expectCleanGuestRoute('/customer')
  })

  test.each(['create', 'run', 'refresh'] as const)(
    'does not show a stale error when obsolete %s rejects',
    async (stage) => {
      let rejectPending!: (reason?: unknown) => void
      if (stage === 'create') {
        const pending = deferred<CustomerConversation>()
        rejectPending = pending.reject
        mockedCreateCustomerConversation.mockReturnValue(pending.promise)
      } else {
        mockedCreateCustomerConversation.mockResolvedValue(
          customerConversation('conversation-created', null),
        )
        if (stage === 'run') {
          const pending = deferred<CustomerRunResponse>()
          rejectPending = pending.reject
          mockedCreateCustomerRun.mockReturnValue(pending.promise)
        } else {
          mockedCreateCustomerRun.mockResolvedValue(customerRun('conversation-created'))
          const pending = deferred<CustomerConversation>()
          rejectPending = pending.reject
          mockedFetchCustomerConversation.mockReturnValue(pending.promise)
        }
      }

      renderCustomerRoute('/customer/agents/agent-1')
      await submitQuestion(`Reject obsolete ${stage}`)
      await waitFor(() => {
        const stageMock =
          stage === 'create'
            ? mockedCreateCustomerConversation
            : stage === 'run'
              ? mockedCreateCustomerRun
              : mockedFetchCustomerConversation
        expect(stageMock).toHaveBeenCalledOnce()
      })

      fireEvent.click(screen.getByRole('button', { name: 'navigate /customer' }))
      await act(async () => {
        rejectPending(new Error(`obsolete ${stage} failed`))
        await Promise.resolve()
      })

      await expectCleanGuestRoute('/customer')
      if (stage === 'create') expect(mockedCreateCustomerRun).not.toHaveBeenCalled()
      if (stage === 'run') expect(mockedFetchCustomerConversation).not.toHaveBeenCalled()
    },
  )
})

function customerConversation(
  conversationId: string,
  customerId: string | null,
  answer?: string,
): CustomerConversation {
  return {
    conversation_id: conversationId,
    agent_id: 'agent-1',
    customer_id: customerId,
    turns: answer
      ? [
          {
            turn_id: `turn-${conversationId}`,
            run_id: `run-${conversationId}`,
            question: 'Stored question',
            response_snapshot: {
              ...customerRun(conversationId),
              turn_id: `turn-${conversationId}`,
              run_id: `run-${conversationId}`,
              message: answer,
            },
            created_at: '2026-07-11T00:00:00Z',
          },
        ]
      : [],
  }
}

function customerRun(conversationId: string): CustomerRunResponse {
  return {
    conversation_id: conversationId,
    turn_id: 'turn-1',
    run_id: 'run-1',
    progress_state: 'completed' as const,
    message: 'Answer',
    safe_sources: [],
  }
}

function renderCustomerRoute(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <NavigationControls />
      <LocationProbe />
      <Routes>
        <Route path="/customer" element={<CustomerChatPage />} />
        <Route path="/customer/new" element={<CustomerChatPage />} />
        <Route path="/customer/agents/:agentId" element={<CustomerChatPage />} />
        <Route path="/customer/c/:conversationId" element={<CustomerChatPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function NavigationControls() {
  const navigate = useNavigate()
  const destinations = [
    '/customer',
    '/customer/new',
    '/customer/agents/agent-1',
    '/customer/c/conversation-2',
    '/customer/c/missing',
  ]
  return (
    <nav aria-label="Test navigation">
      {destinations.map((destination) => (
        <button
          key={destination}
          type="button"
          aria-label={`navigate ${destination}`}
          onClick={() => navigate(destination)}
        >
          {destination}
        </button>
      ))}
    </nav>
  )
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="customer-location">{location.pathname}</output>
}

async function submitQuestion(question: string) {
  const input = await screen.findByPlaceholderText('Ask about a policy, claim, or reimbursement')
  fireEvent.change(input, { target: { value: question } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

async function expectCleanGuestRoute(pathname: string) {
  await waitFor(() => {
    expect(screen.getByTestId('customer-location')).toHaveTextContent(pathname)
  })
  expect(screen.queryByText('Obsolete refreshed answer')).not.toBeInTheDocument()
  expect(await screen.findByText('Anonymous')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Guest' })).toHaveClass('text-[var(--accent)]')
  expect(screen.queryByText('The service is unavailable. Please try again.')).not.toBeInTheDocument()
  expect(screen.getByPlaceholderText('Ask about a policy, claim, or reimbursement')).not.toBeDisabled()
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}
