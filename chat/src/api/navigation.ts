/** Built apps share an origin by default; only the Vite dev server uses sibling ports. */
export function dashboardUrl(path: string): string {
  const base = import.meta.env.VITE_DASHBOARD_URL ?? (import.meta.env.DEV
    ? `${window.location.protocol}//${window.location.hostname}:5173` : '')
  return `${base.replace(/\/+$/, '')}${path}`
}
