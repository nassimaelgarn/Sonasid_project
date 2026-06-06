import React, { useEffect, useMemo, useState } from 'react'
import { kpiApiBase } from '../lib/apiBase'
import { SONASID_LOGIN_SUBTITLE } from '../lib/sonasidCopy'
import { SonasidBrandLogo, SteelPlantBackground, sonasidButtonClass } from '../lib/sonasidTheme'

function clsx(...xs) {
  return xs.filter(Boolean).join(' ')
}

function useApiBase() {
  return useMemo(() => kpiApiBase(), [])
}

async function apiJson(url, opts = {}) {
  const res = await fetch(url, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    credentials: 'include',
  })
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { raw: text }
  }
  if (!res.ok) {
    const msg = data?.message || data?.error || `HTTP ${res.status}`
    throw new Error(msg)
  }
  // Some endpoints return {ok:false,...} with HTTP 200.
  if (data && typeof data === 'object' && data.ok === false) {
    const msg = data?.message || data?.error || 'Erreur'
    throw new Error(msg)
  }
  return data
}

export default function AuthGate({ children }) {
  const baseUrl = useApiBase()
  const [loading, setLoading] = useState(true)
  const [me, setMe] = useState(null) // { authenticated, user }
  const [err, setErr] = useState('')

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [localOpen, setLocalOpen] = useState(true)
  const [busy, setBusy] = useState(false)

  async function refreshMe() {
    const data = await apiJson(`${baseUrl}/auth/me`)
    setMe(data)
    try {
      if (data?.authenticated && data?.user) {
        const dn = String(data.user.display_name || data.user.email || '').trim()
        if (dn) {
          localStorage.setItem('sonasid_actor_name', dn)
          localStorage.setItem('sonasid_actor_locked', '1')
        }
      } else {
        localStorage.removeItem('sonasid_actor_locked')
      }
    } catch {
      // ignore
    }
    return data
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        setLoading(true)
        setErr('')
        const url = new URL(window.location.href)
        const code = url.searchParams.get('code')
        const state = url.searchParams.get('state')
        const isMsCallback = Boolean(code && state)

        // Microsoft callback: exchange code -> session
        if (isMsCallback) {
          await apiJson(`${baseUrl}/auth/microsoft/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`)
          // Clean URL (remove code/state)
          url.searchParams.delete('code')
          url.searchParams.delete('state')
          url.searchParams.delete('session_state')
          window.history.replaceState({}, '', url.toString())
        }

        const data = await refreshMe()
        if (!cancelled) setMe(data)
      } catch (e) {
        if (!cancelled) setErr(e?.message || String(e || 'Erreur'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [baseUrl])

  // UX: remember last username for local login.
  // Use a v2 key so older saved values (e.g. display names with spaces) don't keep reappearing.
  useEffect(() => {
    try {
      const v = localStorage.getItem('sonasid_last_username_v2') || ''
      if (v && !username) setUsername(v)
    } catch {
      // ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    try {
      if (username) localStorage.setItem('sonasid_last_username_v2', username)
    } catch {
      // ignore
    }
  }, [username])

  async function onLocalLogin(e) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErr('')
    try {
      await apiJson(`${baseUrl}/auth/local/login`, {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      await refreshMe()
      setPassword('')
    } catch (e2) {
      const msg = e2?.message || String(e2 || 'Erreur')
      if (/failed to fetch|networkerror|load failed/i.test(msg)) {
        setErr(
          'Impossible de joindre l’API backend.\n'
            + 'Sur la VM : git pull && bash scripts/vm_setup_nginx.sh && pm2 restart my-backend my-frontend',
        )
      } else {
        setErr(msg)
      }
    } finally {
      setBusy(false)
    }
  }

  async function onMicrosoftLogin() {
    if (busy) return
    setBusy(true)
    setErr('')
    try {
      // Use browser redirect flow so session cookies/state are guaranteed.
      const ret = window.location.origin + window.location.pathname
      window.location.href = `${baseUrl}/auth/microsoft/login?redirect=1&return_to=${encodeURIComponent(ret)}`
    } catch (e2) {
      setErr(e2?.message || String(e2 || 'Erreur'))
      setBusy(false)
    }
  }

  if (loading) {
    return <div className="p-6 text-slate-700 dark:text-slate-200">Chargement…</div>
  }

  if (me?.authenticated) return children

  return (
    <div className="app-bg min-h-screen">
      <div className="noise" />
      <SteelPlantBackground variant="login" />
      <div className="mx-auto max-w-xl px-4 py-10 sm:py-14 relative">
        <div className="panel p-6 sm:p-8 border border-slate-200/70 dark:border-slate-700/55 shadow-[0_24px_60px_-32px_rgba(2,6,23,0.55)]">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                Sonasid
              </div>
              <div className="mt-1 text-2xl sm:text-3xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
                AI Assistant
              </div>
              <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                {SONASID_LOGIN_SUBTITLE}
              </div>
            </div>
            <div className="hidden sm:flex flex-col items-end">
              <SonasidBrandLogo />
            </div>
          </div>

          {err ? (
            <div className="mt-5 rounded-xl border border-rose-200/70 bg-rose-50/70 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/25 dark:text-rose-200 whitespace-pre-wrap">
              {err}
            </div>
          ) : null}

          <div className="mt-6 grid gap-4">
            <div className="rounded-2xl border border-slate-200/70 bg-white/55 p-4 dark:border-slate-700/55 dark:bg-slate-900/20 shadow-sm">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">Compte Microsoft</div>
                </div>
                <div className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
                  SSO
                </div>
              </div>
              <button
                type="button"
                className={clsx(
                  'w-full mt-3 rounded-xl px-4 py-2.5 text-sm font-semibold text-white',
                  sonasidButtonClass,
                  'active:scale-[0.99] transition text-white',
                  'focus:outline-none focus:ring-2',
                  busy && 'opacity-70 pointer-events-none',
                )}
                onClick={onMicrosoftLogin}
              >
                Se connecter avec Microsoft
              </button>
            </div>

            <div className="flex items-center gap-3 py-1">
              <div className="h-px flex-1 bg-slate-200/70 dark:bg-slate-600/50" />
              <div className="text-[11px] font-medium text-slate-500 dark:text-slate-400">ou</div>
              <div className="h-px flex-1 bg-slate-200/70 dark:bg-slate-600/50" />
            </div>

            <div className="rounded-2xl border border-slate-200/70 bg-white/50 dark:border-slate-700/55 dark:bg-slate-900/15 shadow-sm overflow-hidden">
              <button
                type="button"
                className="w-full px-4 py-3 text-left flex items-center justify-between gap-3 hover:bg-slate-50/60 dark:hover:bg-white/5"
                onClick={() => setLocalOpen((v) => !v)}
              >
                <div>
                  <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">Compte local</div>
                  <div className="mt-0.5 text-xs text-slate-600 dark:text-slate-300">
                    Utilise ce mode si l’utilisateur n’a pas de compte Microsoft.
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-[11px] font-medium text-slate-500 dark:text-slate-400">Local</div>
                  <div className={clsx('text-slate-500 dark:text-slate-400 transition-transform', localOpen && 'rotate-180')}>
                    ▾
                  </div>
                </div>
              </button>

              {localOpen ? (
                <div className="px-4 pb-4">
                  <form onSubmit={onLocalLogin} className="mt-1 grid gap-3">
                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
                        Nom d’utilisateur
                      </label>
                      <input
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-slate-200/80 dark:border-slate-600/55 bg-white/80 dark:bg-slate-800/45 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-red-500/15"
                        placeholder="Nom complet"
                        autoComplete="username"
                      />
                    </div>
                    <div>
                      <div className="flex items-center justify-between">
                        <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">Mot de passe</label>
                        <button
                          type="button"
                          className="text-[11px] font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
                          onClick={() => setShowPassword((v) => !v)}
                        >
                          {showPassword ? 'Masquer' : 'Afficher'}
                        </button>
                      </div>
                      <input
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        type={showPassword ? 'text' : 'password'}
                        className="mt-1 w-full rounded-xl border border-slate-200/80 dark:border-slate-600/55 bg-white/80 dark:bg-slate-800/45 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-red-500/15"
                        placeholder="••••••••"
                        autoComplete="current-password"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={busy || !username.trim() || !password}
                      className={clsx(
                        'w-full rounded-xl px-4 py-2.5 text-sm font-semibold text-white',
                        sonasidButtonClass,
                        'active:scale-[0.99] transition text-white',
                        'focus:outline-none focus:ring-2',
                        (busy || !username.trim() || !password) && 'opacity-50 cursor-not-allowed',
                      )}
                    >
                      {busy ? 'Connexion…' : 'Se connecter (compte local)'}
                    </button>
                  </form>
                </div>
              ) : null}
            </div>
          </div>

          <div className="mt-6 text-xs text-slate-500 dark:text-slate-400">
            Astuce: si Microsoft te reconnecte automatiquement, tu peux changer de compte via l’écran de sélection.
          </div>
        </div>
      </div>
    </div>
  )
}

