/**
 * Default API origin in the browser.
 * Microsoft Entra ID allows http://localhost redirect URIs in dev, but not http://127.0.0.1.
 * OAuth "state" is stored in the session cookie on the host that serves /auth/microsoft/login;
 * that host must match the redirect/callback host (localhost), so we map 127.0.0.1 → localhost.
 */
export function defaultKpiApiBase() {
  if (typeof window === 'undefined') return 'http://localhost:8000'
  let host = window.location.hostname || 'localhost'
  if (host === '127.0.0.1') host = 'localhost'
  return `http://${host}:8000`
}

/** Resolved API base (trimmed, no trailing slash). Honors VITE_API_BASE when set. */
export function kpiApiBase() {
  let raw = (import.meta.env.VITE_API_BASE || defaultKpiApiBase()).replace(/\/$/, '')
  // Entra ID only allows http://localhost (not 127.0.0.1) for dev redirects — align API host.
  raw = raw.replace(/^http:\/\/127\.0\.0\.1(?=:)/, 'http://localhost')
  return raw
}
