let csrfToken: string | null = null
const expiredListeners = new Set<() => void>()

export function currentCsrfToken(): string | null {
  return csrfToken
}

export function setCurrentCsrfToken(value: string | null): void {
  csrfToken = value
}

export function notifySessionExpired(): void {
  csrfToken = null
  expiredListeners.forEach((listener) => listener())
}

export function onSessionExpired(listener: () => void): () => void {
  expiredListeners.add(listener)
  return () => expiredListeners.delete(listener)
}
