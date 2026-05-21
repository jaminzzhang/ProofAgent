// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test } from 'vitest'

import { AppRoutes } from './router'

afterEach(() => {
  cleanup()
})

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

test('root route shows explicit chat mode selection', () => {
  renderRoute('/')

  expect(screen.getByRole('heading', { name: 'Proof Agent Chat' })).toBeTruthy()
  expect(screen.getByRole('link', { name: /operator chat/i })).toHaveAttribute('href', '/operator')
  expect(screen.getByRole('link', { name: /customer chat/i })).toHaveAttribute('href', '/customer')
})

test('legacy un-namespaced chat routes do not open operator chat directly', () => {
  renderRoute('/new')

  expect(screen.getByRole('heading', { name: 'Proof Agent Chat' })).toBeTruthy()
  expect(screen.queryByText('Assisted Chat')).toBeNull()
})

test('customer route opens customer-safe chat mode without internal audit affordances', () => {
  renderRoute('/customer')

  expect(screen.getByRole('heading', { name: 'Customer Chat' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Guest' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Demo 1' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Demo 2' })).toBeTruthy()
  expect(screen.queryByText(/audit trace/i)).toBeNull()
  expect(screen.queryByText(/receipt/i)).toBeNull()
  expect(screen.queryByText(/governance/i)).toBeNull()
  expect(screen.queryByText(/approval/i)).toBeNull()
})
