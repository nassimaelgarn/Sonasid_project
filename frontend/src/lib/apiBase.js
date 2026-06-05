/**
 * API base URL. Vite dev proxies /auth /chat → :8001 (same origin, no CORS).
 */

export function defaultKpiApiBase() {
  if (typeof window === 'undefined') return 'http://localhost:8001'

  const { hostname, port, protocol, origin } = window.location
  let host = hostname || 'localhost'
  if (host === '127.0.0.1') host = 'localhost'

  if (import.meta.env.DEV) {
    return origin
  }

  const p = String(port || '')
  if (!p || p === '80' || p === '443') {
    return `${protocol}//${host}`
  }
  return `http://${host}:8001`
}

export function kpiApiBase() {
  let raw = (import.meta.env.VITE_API_BASE || defaultKpiApiBase()).replace(/\/$/, '')
  raw = raw.replace(/^http:\/\/127\.0\.0\.1(?=:)/, 'http://localhost')
  return raw
}
