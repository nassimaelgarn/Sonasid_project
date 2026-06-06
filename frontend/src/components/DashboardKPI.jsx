import React, { useEffect, useMemo, useRef, useState } from 'react'
import { kpiApiBase } from '../lib/apiBase'
import {
  SONASID_CHAT_PLACEHOLDER,
  SONASID_CHAT_SUBTITLE,
  SONASID_TAGLINE,
  SONASID_WELCOME_HINT,
  buildSonasidWelcomeText,
} from '../lib/sonasidCopy'
import { SonasidBrandLogo, SteelPlantBackground } from '../lib/sonasidTheme'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line, Bar } from 'react-chartjs-2'
// (reverted) removed platform header abstraction

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Tooltip,
  Legend,
  Filler,
)

function formatDurationSeconds(sec) {
  const s = Number(sec ?? 0)
  if (!Number.isFinite(s)) return '—'
  const min = s / 60
  const hr = s / 3600
  if (s < 120) return `${Math.round(s)} s`
  if (s < 7200) return `${Math.round(s)} s (${min.toFixed(1)} min)`
  return `${Math.round(s)} s (${min.toFixed(1)} min / ${hr.toFixed(2)} h)`
}

function toIsoDate(d) {
  const dt = new Date(d)
  if (!Number.isFinite(dt.getTime())) return ''
  const yyyy = dt.getFullYear()
  const mm = String(dt.getMonth() + 1).padStart(2, '0')
  const dd = String(dt.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

function addDaysIso(iso, days) {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + days)
  return toIsoDate(d)
}

function isAlreadyDated(q) {
  const s = (q || '').toLowerCase()
  return (
    /\b20\d{2}-\d{2}-\d{2}\b/.test(s) ||
    /\b20\d{2}-\d{2}\b/.test(s) ||
    /\b20\d{2}\b/.test(s) ||
    /\b(?:du|de)\s+\d{4}-\d{2}-\d{2}\s+(?:au|a|à)\s+\d{4}-\d{2}-\d{2}\b/.test(s)
  )
}

function applyPeriodToQuestion(q, { start, end, force = true }) {
  const base = (q || '').trim()
  if (!base) return base
  if (!start || !end) return base
  // If user explicitly provided dates/year/month, don't force-inject a period unless asked.
  if (!force && isAlreadyDated(base)) return base
  // Avoid duplicating a range if it's already present
  if (/\b(?:du|de)\s+\d{4}-\d{2}-\d{2}\s+(?:au|a|à)\s+\d{4}-\d{2}-\d{2}\b/i.test(base)) return base
  return `${base} du ${start} au ${end}`
}

function isNoDataResponse(res) {
  const msg = String(res?.message ?? '')
  return msg.toLowerCase().includes('aucune donnée') || msg.toLowerCase().includes('aucune donnee')
}

function formatMsgTime(createdAtSeconds) {
  const t = Number(createdAtSeconds)
  if (!Number.isFinite(t) || t <= 0) return ''
  const d = new Date(t * 1000)
  if (!Number.isFinite(d.getTime())) return ''
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

const DEFAULT_QUICK_KPIS = [
  { label: 'Navires actifs', question: 'nombre de navires actifs', key: 'nombre_navires', fmt: (v) => String(v) },
  { label: 'Arrivages', question: `nombre d'arrivages en ${new Date().getFullYear()}`, key: 'nombre_arrivages', fmt: (v) => String(v) },
]

function clsx(...xs) {
  return xs.filter(Boolean).join(' ')
}

function withKpiInterpretation(text, res) {
  const interp = typeof res?.interpretation === 'string' ? res.interpretation.trim() : ''
  if (!interp) return text
  return `${text}\n\n---\n\n**Analyse**\n\n${interp}`
}

function buildWelcomeText(actorName) {
  return buildSonasidWelcomeText(actorName)
}

function pickValue(res, key) {
  if (!res || typeof res !== 'object') return null
  if (key in res) return res[key]
  if ('result' in res && typeof res.result === 'number') return res.result
  return null
}

function formatAssistantCompact(res, { clientMode } = { clientMode: false }) {
  if (!res || typeof res !== 'object') return String(res ?? '')
  if (res?.error) return res?.message ? res.message : `Erreur: ${res.error}`
  if (res?.notice) {
    if (clientMode && /LLM indisponible/i.test(String(res.notice))) {
      return "Assistant IA temporairement indisponible. Je t’affiche quand même le résultat via le moteur KPI."
    }
    return res.notice
  }
  if (res?.message) return withKpiInterpretation(String(res.message).trim(), res)

  // Common KPI fields → readable text (client-friendly)
  if (typeof res?.TD_percent === 'number') return withKpiInterpretation(`TD: ${res.TD_percent}%`, res)
  if (typeof res?.TR_percent === 'number') return withKpiInterpretation(`TR: ${res.TR_percent}%`, res)
  if (typeof res?.MTBF_secondes === 'number') {
    return withKpiInterpretation(`MTBF: ${formatDurationSeconds(res.MTBF_secondes)}`, res)
  }
  if (typeof res?.MTTR_secondes === 'number') {
    return withKpiInterpretation(`MTTR: ${formatDurationSeconds(res.MTTR_secondes)}`, res)
  }
  if (typeof res?.Rendement_percent === 'number') {
    return withKpiInterpretation(`Rendement: ${res.Rendement_percent}%`, res)
  }

  // Consumption dict (pipeline legacy)
  const consoKeys = [
    'Consommation_Totale',
    'Consommation_MWh',
    'Consommation_EAF',
    'Consommation_LF',
    'Consommation_Oxygène',
    'Consommation_Carbon',
    'Consommation_GPL',
  ].filter((k) => k in res)
  if (consoKeys.length) {
    const fmtConso = (k, v) => {
      if (typeof v !== 'number' || !Number.isFinite(v)) return String(v ?? '—')
      if (k === 'Consommation_MWh') return `${v.toFixed(2)} MWh`
      const num = Number.isInteger(v) ? v.toLocaleString('fr-FR') : v.toLocaleString('fr-FR', { maximumFractionDigits: 2 })
      const isElec = typeof res?.Consommation_MWh === 'number'
      const suffix = isElec && (k === 'Consommation_Totale' || k === 'Consommation_EAF' || k === 'Consommation_LF') ? ' kWh' : ''
      return `${num}${suffix}`
    }
    return withKpiInterpretation(
      consoKeys.map((k) => `${k.replace('Consommation_', '')}: ${fmtConso(k, res[k])}`).join('\n'),
      res,
    )
  }

  if (typeof res?.result === 'number') return withKpiInterpretation(`Résultat: ${res.result}`, res)
  if (Array.isArray(res?.result)) {
    const arr = res.result
    if (!arr.length) return 'Aucun résultat.'

    const fmt = (v) => {
      if (v == null) return '—'
      if (typeof v === 'number') {
        if (!Number.isFinite(v)) return '—'
        if (Math.abs(v) >= 1000 && Number.isInteger(v)) return v.toLocaleString('fr-FR')
        return Number.isInteger(v) ? String(v) : v.toFixed(2)
      }
      return String(v)
    }

    // If it’s a list of objects (rows), render a compact preview in chat.
    const first = arr[0]
    if (first && typeof first === 'object' && !Array.isArray(first)) {
      const keys = Object.keys(first).slice(0, 4)

      const isSimplePeriodValue =
        keys.length >= 2 && keys.includes('period') && keys.includes('value') && keys.every((k) => ['period', 'value'].includes(k))

      const preview = arr.slice(0, 5).map((row) => {
        if (isSimplePeriodValue) return `${fmt(row?.period)}: ${fmt(row?.value)}`
        const parts = keys.map((k) => `${k}: ${fmt(row?.[k])}`)
        return parts.join(' · ')
      })
      // Keep chat clean; extra rows are accessible via the "Voir les N lignes" button.
      return withKpiInterpretation(preview.join('\n'), res)
    }

    // Fallback: array of primitives
    const preview = arr.slice(0, 8).map((v) => `${fmt(v)}`)
    return withKpiInterpretation(preview.join('\n'), res)
  }

  // Fallback: show non-technical keys only.
  const hidden = new Set([
    'question',
    'source',
    'llm_status',
    'llm_reason',
    'llm_provider',
    'llm_sql',
    'interpretation',
  ])
  const keys = Object.keys(res).filter((k) => !hidden.has(k))
  if (!keys.length) return 'OK.'
  return keys.map((k) => `${k}: ${JSON.stringify(res[k])}`).join('\n')
}

function tryParseLooseObject(text) {
  const s = String(text ?? '').trim()
  if (!s.startsWith('{') || !s.endsWith('}')) return null
  // First try strict JSON (backend may store valid JSON strings).
  try {
    return JSON.parse(s)
  } catch {
    // fallthrough
  }
  // Convert Python-ish dict string to JSON-ish best-effort
  const jsonish = s
    .replace(/'/g, '"')
    .replace(/\bNone\b/g, 'null')
    .replace(/\bTrue\b/g, 'true')
    .replace(/\bFalse\b/g, 'false')
  try {
    return JSON.parse(jsonish)
  } catch {
    return null
  }
}

function normalizeHistoryMessage(content, { clientMode } = { clientMode: false }) {
  const parsed = tryParseLooseObject(content)
  if (parsed && typeof parsed === 'object') return formatAssistantCompact(parsed, { clientMode })
  return String(content ?? '')
}

function parseAssistantHistoryMessage(content, { clientMode } = { clientMode: false }) {
  const raw = tryParseLooseObject(content)
  if (raw && typeof raw === 'object') {
    if (raw.__kind === 'kpi_table' && Array.isArray(raw.rows)) {
      const text = raw.preview || formatAssistantCompact({ result: raw.rows }, { clientMode })
      return {
        content: text,
        meta: { raw: { result: raw.rows }, series: null },
      }
    }
    return { content: formatAssistantCompact(raw, { clientMode }) }
  }
  return { content: String(content ?? '') }
}

function isTableRows(v) {
  return (
    Array.isArray(v) &&
    v.length > 0 &&
    v.every((r) => r && typeof r === 'object' && !Array.isArray(r))
  )
}

function renderTableLines(rows, limit = 5) {
  if (!isTableRows(rows)) return null
  const keys = Object.keys(rows[0]).slice(0, 4)
  const fmt = (v) => {
    if (v == null) return '—'
    if (typeof v === 'number') {
      if (!Number.isFinite(v)) return '—'
      if (Math.abs(v) >= 1000 && Number.isInteger(v)) return v.toLocaleString('fr-FR')
      return Number.isInteger(v) ? String(v) : v.toFixed(2)
    }
    return String(v)
  }
  return rows.slice(0, limit).map((row, i) => {
    const parts = keys.map((k) => `${k}: ${fmt(row?.[k])}`)
    return `${i + 1}) ${parts.join(' · ')}`
  })
}

function MiniTable({ rows, maxHeight = 260 }) {
  if (!isTableRows(rows)) return null
  const cols = Object.keys(rows[0]).slice(0, 6)
  return (
    <div
      className="mt-2 overflow-auto rounded-xl border border-slate-200/70 bg-white/70"
      style={{ maxHeight }}
    >
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-white/90 backdrop-blur">
          <tr className="border-b border-slate-200/70">
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 font-medium text-slate-700">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              className={clsx(
                'border-b border-slate-200/50 last:border-b-0',
                i % 2 === 0 ? 'bg-white/60' : 'bg-slate-50/60',
                'hover:bg-blue-50/50 transition-colors',
              )}
            >
              {cols.map((c) => (
                <td key={c} className="px-3 py-2 text-slate-800 whitespace-nowrap">
                  {r?.[c] == null ? '' : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function newSessionId() {
  return `s_${crypto?.randomUUID?.() || String(Date.now())}`
}

function getOrCreateCurrentSessionId() {
  const key = 'sonasid_current_session_id'
  const existing = localStorage.getItem(key)
  if (existing) return existing
  const sid = newSessionId()
  localStorage.setItem(key, sid)
  return sid
}

function getOrCreateModelForSession(sessionId) {
  const key = `sonasid_model_${sessionId}`
  const existing = localStorage.getItem(key)
  if (existing) {
    // Backward-compat: old preset key was "mistral" for the Flash model
    if (existing === 'mistral') return 'flash'
    return existing
  }
  localStorage.setItem(key, 'trinity')
  return 'trinity'
}

function setModelForSession(sessionId, modelName) {
  localStorage.setItem(`sonasid_model_${sessionId}`, modelName)
}

async function apiChat(baseUrl, question, sessionId, modelName) {
  const r = await fetch(`${baseUrl}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ question, session_id: sessionId, model_name: modelName }),
  })
  const json = await r.json().catch(() => null)
  if (!r.ok) {
    const msg = json?.detail || json?.error || `HTTP ${r.status}`
    throw new Error(msg)
  }
  return json
}

async function apiListConversations(baseUrl) {
  const r = await fetch(`${baseUrl}/conversations`, { credentials: 'include' })
  const json = await r.json().catch(() => null)
  if (!r.ok) throw new Error(json?.detail || `HTTP ${r.status}`)
  return json?.conversations || []
}

async function apiGetHistory(baseUrl, sessionId) {
  const r = await fetch(`${baseUrl}/conversations/${encodeURIComponent(sessionId)}/history`, { credentials: 'include' })
  const json = await r.json().catch(() => null)
  if (!r.ok) throw new Error(json?.detail || `HTTP ${r.status}`)
  return json?.messages || []
}

async function apiDeleteConversation(baseUrl, sessionId) {
  const r = await fetch(`${baseUrl}/conversations/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
}

function toSeries(res) {
  const rows = res?.result
  if (!Array.isArray(rows)) return null
  if (rows.length === 0) return null

  const r0 = rows[0]
  if (r0 && typeof r0 === 'object' && 'period' in r0 && 'value' in r0) {
    return {
      kind: 'time',
      labels: rows.map((r) => r.period),
      values: rows.map((r) => Number(r.value ?? 0)),
    }
  }
  if (r0 && typeof r0 === 'object' && 'grade' in r0 && 'value' in r0) {
    return {
      kind: 'grade',
      labels: rows.map((r) => r.grade),
      values: rows.map((r) => Number(r.value ?? 0)),
    }
  }
  if (r0 && typeof r0 === 'object' && 'categorie' in r0 && ('value' in r0 || 'poids' in r0)) {
    return {
      kind: 'cat',
      labels: rows.map((r) => r.categorie),
      values: rows.map((r) => Number((r.value ?? r.poids) ?? 0)),
    }
  }
  return null
}

function inferTableColumns(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return []
  const cols = []
  const seen = new Set()
  for (const r of rows) {
    if (!r || typeof r !== 'object' || Array.isArray(r)) continue
    for (const k of Object.keys(r)) {
      if (seen.has(k)) continue
      seen.add(k)
      cols.push(k)
    }
  }
  return cols
}

function toCsv(rows, columns) {
  const esc = (v) => {
    const s = v == null ? '' : String(v)
    if (/[",\n]/.test(s)) return `"${s.replaceAll('"', '""')}"`
    return s
  }
  const header = columns.map(esc).join(',')
  const lines = rows.map((r) => columns.map((c) => esc(r?.[c])).join(','))
  return [header, ...lines].join('\n')
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function applyVarsToQuestion(q, { grade, topN }) {
  let out = q
  if (topN && !/top\s+\d+/i.test(out) && /(par grade|par catégorie|par ferraille|par largeur|par epaisseur|par épaisseur)/i.test(out)) {
    out = out.replace(/(top\s+\d+)/i, `top ${topN}`)
    if (!/top\s+\d+/i.test(out)) out = out + ` top ${topN}`
  } else if (topN && /top\s+\d+/i.test(out)) {
    out = out.replace(/top\s+\d+/i, `top ${topN}`)
  }

  if (grade && !/grade\s+/i.test(out)) {
    // inject after keyword if present
    if (/(consommation|production|nombre|poids)/i.test(out)) {
      out = out.replace(/(consommation|production|nombre|poids)/i, (m) => `${m} grade ${grade}`)
    } else {
      out = out + ` grade ${grade}`
    }
  } else if (grade && /grade\s+[^\s]+/i.test(out)) {
    out = out.replace(/grade\s+[^\s]+/i, `grade ${grade}`)
  }

  return out
}

export default function DashboardKPI() {
  const baseUrl = kpiApiBase()
  const [sessionId, setSessionId] = useState(() => getOrCreateCurrentSessionId())
  const [modelName, setModelName] = useState(() => getOrCreateModelForSession(sessionId))
  const [history, setHistory] = useState([])
  const [historyBusy, setHistoryBusy] = useState(false)

  const [chatInput, setChatInput] = useState('')
  const [actorName] = useState(() => (localStorage.getItem('sonasid_actor_name') || '').trim())
  const [chat, setChat] = useState(() => [])
  const [busy, setBusy] = useState(false)
  const [selectedSeries, setSelectedSeries] = useState(null)
  const [lastResponse, setLastResponse] = useState(null)
  const [grade, setGrade] = useState('')
  const [topN, setTopN] = useState('5')
  const clientMode = true // livraison: UI 100% "client" (pas de mode debug)
  const [periodPreset, setPeriodPreset] = useState('none') // none | 7d | 30d | mtd | ytd | custom
  const [customStart, setCustomStart] = useState(() => addDaysIso(toIsoDate(new Date()), -29))
  const [customEnd, setCustomEnd] = useState(() => toIsoDate(new Date()))
  const [convSearch, setConvSearch] = useState('')
  const [yearPick, setYearPick] = useState('') // optional: e.g. "2025"
  const [quickKpis, setQuickKpis] = useState(
    DEFAULT_QUICK_KPIS.map((k) => ({ ...k, value: null, loading: false, error: null })),
  )
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('sonasid_theme')
    return saved === 'dark' ? 'dark' : 'light'
  })

  const [expandedRowsByMsg, setExpandedRowsByMsg] = useState(() => ({}))
  const chatScrollRef = useRef(null)
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true)
  const chatEndRef = useRef(null)
  const scrollToEnd = () => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })

  function onChatScroll() {
    const el = chatScrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setShouldAutoScroll(distanceFromBottom < 80)
  }

  const isWelcomeOnly = Array.isArray(chat) && chat.length === 0

  const period = useMemo(() => {
    const today = toIsoDate(new Date())
    if (periodPreset === 'none') return { label: '—', start: null, end: null, enabled: false }
    if (periodPreset === '7d') return { label: '7j', start: addDaysIso(today, -6), end: today }
    if (periodPreset === '30d') return { label: '30j', start: addDaysIso(today, -29), end: today }
    if (periodPreset === 'mtd') {
      const d = new Date()
      const start = toIsoDate(new Date(d.getFullYear(), d.getMonth(), 1))
      return { label: 'mois', start, end: today }
    }
    if (periodPreset === 'ytd') {
      const d = new Date()
      const start = toIsoDate(new Date(d.getFullYear(), 0, 1))
      return { label: 'YTD', start, end: today }
    }
    return { label: 'perso', start: customStart, end: customEnd, enabled: true }
  }, [periodPreset, customStart, customEnd])

  // Keep year picker in sync when period is a full calendar year.
  useEffect(() => {
    const m = /^(\d{4})-01-01$/.exec(customStart || '')
    if (periodPreset === 'custom' && m && customEnd === `${m[1]}-12-31`) setYearPick(m[1])
  }, [periodPreset, customStart, customEnd])

  const filteredHistory = useMemo(() => {
    const q = (convSearch || '').trim().toLowerCase()
    if (!q) return history
    return history.filter((h) => {
      const title = String(h?.title ?? '').toLowerCase()
      const sid = String(h?.session_id ?? '').toLowerCase()
      return title.includes(q) || sid.includes(q)
    })
  }, [history, convSearch])

  const chartData = useMemo(() => {
    if (!selectedSeries) return null
    const { labels, values, kind } = selectedSeries

    const color = kind === 'time' ? 'rgba(59, 130, 246, 1)' : 'rgba(168, 85, 247, 1)'
    const fill = kind === 'time' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(168, 85, 247, 0.14)'

    return {
      labels,
      datasets: [
        {
          label: 'Valeur',
          data: values,
          borderColor: color,
          backgroundColor: fill,
          tension: 0.25,
          fill: kind === 'time',
        },
      ],
    }
  }, [selectedSeries])

  const chartOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: {
          ticks: { color: 'rgba(71,85,105,0.85)' },
          grid: { color: 'rgba(148,163,184,0.25)' },
        },
        y: {
          ticks: { color: 'rgba(71,85,105,0.85)' },
          grid: { color: 'rgba(148,163,184,0.25)' },
        },
      },
    }),
    [],
  )

  useEffect(() => {
    localStorage.setItem('sonasid_current_session_id', sessionId)
    const m = getOrCreateModelForSession(sessionId)
    setModelName(m)
    ;(async () => {
      setHistoryBusy(true)
      try {
        const convs = await apiListConversations(baseUrl)
        setHistory(convs)
      } catch {
        // ignore
      } finally {
        setHistoryBusy(false)
      }
    })()
  }, [baseUrl, sessionId])

  async function apiGetHistoryWithRetry(baseUrl, sessionId, { tries = 4 } = {}) {
    let lastErr = null
    for (let i = 0; i < tries; i++) {
      try {
        return await apiGetHistory(baseUrl, sessionId)
      } catch (e) {
        lastErr = e
        // Backoff: 150ms, 300ms, 600ms...
        const wait = 150 * Math.pow(2, i)
        await new Promise((r) => setTimeout(r, wait))
      }
    }
    const msg = lastErr?.message || 'Erreur réseau'
    throw new Error(msg)
  }

  async function loadConversation(sid) {
    setSessionId(sid)
    try {
      const msgs = await apiGetHistoryWithRetry(baseUrl, sid, { tries: 4 })
      if (Array.isArray(msgs) && msgs.length) {
        setChat(
          msgs.map((m) => {
            const role = m.role === 'assistant' ? 'assistant' : 'user'
            const created_at = typeof m.created_at === 'number' ? m.created_at : Number(m.created_at || 0)
            if (role === 'assistant') {
              const parsed = parseAssistantHistoryMessage(m.content, { clientMode })
              return { role, content: parsed.content, meta: parsed.meta, created_at }
            }
            return { role, content: String(m.content ?? ''), created_at }
          }),
        )
      } else {
        // Empty conversation → show the centered home screen (ChatGPT-like).
        setChat([])
      }
    } catch (e) {
      const msg = e?.message || String(e || '')
      setChat([
        {
          role: 'assistant',
          content: `Impossible de charger l’historique.\n\nDétail: ${msg}\n\nClique “Nouvelle” puis re-clique la conversation (ou rafraîchis).`,
        },
      ])
    }
  }

  async function createNewConversation() {
    const sid = newSessionId()
    setSessionId(sid)
    setChat([])
    setLastResponse(null)
    setSelectedSeries(null)
    setConvSearch('')
    // Optimistic insert so the new conversation appears immediately in the list.
    setHistory((prev) => {
      const rest = Array.isArray(prev) ? prev.filter((h) => h?.session_id !== sid) : []
      return [{ session_id: sid, title: 'Nouvelle conversation' }, ...rest]
    })
    try {
      const convs = await apiListConversations(baseUrl)
      // Keep the optimistic conversation if backend doesn't persist it yet.
      setHistory((prev) => {
        const hasNew = Array.isArray(convs) && convs.some((c) => c?.session_id === sid)
        return hasNew ? convs : prev
      })
    } catch {
      // ignore
    }
  }

  async function deleteConversation(sid) {
    try {
      await apiDeleteConversation(baseUrl, sid)
    } catch {
      // ignore
    } finally {
      const convs = await apiListConversations(baseUrl).catch(() => [])
      setHistory(convs)
      if (sid === sessionId) createNewConversation()
    }
  }

  function onChangeModel(next) {
    setModelName(next)
    setModelForSession(sessionId, next)
  }

  async function fetchQuickKpis() {
    setQuickKpis((prev) => prev.map((k) => ({ ...k, loading: true, error: null })))
    try {
      const results = await Promise.all(
        DEFAULT_QUICK_KPIS.map(async (k) => {
          try {
            const q2 =
              periodPreset === 'none'
                ? k.question
                : applyPeriodToQuestion(k.question, { ...period, force: true })
            const res = await apiChat(baseUrl, q2, sessionId, modelName)
            const v = pickValue(res, k.key)
            return { ok: true, value: v, error: null }
          } catch (e) {
            return { ok: false, value: null, error: e?.message || 'Erreur API' }
          }
        }),
      )
      setQuickKpis((prev) =>
        prev.map((k, i) => ({
          ...k,
          value: results[i].value,
          error: results[i].error,
          loading: false,
        })),
      )
    } finally {
      // no-op
    }
  }

  async function sendChat(opts) {
    const rawText = typeof opts === 'string' ? opts : opts?.question
    const display = typeof opts === 'string' ? null : opts?.display
    const hideQuestion = typeof opts === 'string' ? false : Boolean(opts?.hideQuestion)

    const q = (rawText ?? chatInput).trim()
    if (!q || busy) return

    setBusy(true)
    setChatInput('')
    setChat((prev) => [...prev, { role: 'user', content: display || q }])

    try {
      const q2 = applyVarsToQuestion(q, { grade: grade.trim(), topN: String(topN || '').trim() })
      // For free-form chat, don't override an explicit year/month/date the user wrote.
      const q3 =
        periodPreset === 'none' ? q2 : applyPeriodToQuestion(q2, { ...period, force: false })
      const res = await apiChat(baseUrl, q3, sessionId, modelName)
      setLastResponse(res)
      const series = toSeries(res)
      if (series) setSelectedSeries(series)

      const compact = formatAssistantCompact(res, { clientMode })

      setChat((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: compact,
          meta: { raw: res, series },
        },
      ])
      // refresh sidebar titles/order
      apiListConversations(baseUrl).then(setHistory).catch(() => null)
      if (shouldAutoScroll) setTimeout(scrollToEnd, 0)
    } catch (e) {
      setChat((prev) => [
        ...prev,
        { role: 'assistant', content: `Erreur API /chat: ${e?.message || String(e)}` },
      ])
      if (shouldAutoScroll) setTimeout(scrollToEnd, 0)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={clsx('app-bg', theme === 'dark' ? 'theme-dark' : 'theme-light')}>
      <div className="blob b1" />
      <div className="blob b2" />
      <div className="blob b3" />
      <div className="noise" />
      <SteelPlantBackground />
      {/* Keep the workspace (left) accessible while chat scrolls */}
      <div className="relative mx-auto max-w-7xl px-2 py-4 sm:px-3 sm:py-6 h-[100dvh] flex flex-col overflow-hidden">
        <header className="shrink-0 flex relative">
          <div className="w-full mx-auto text-center">
            <div className="text-xs font-medium tracking-wide text-slate-500">Sonasid</div>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
              AI Assistant
            </h1>
            <p className="mt-1 text-sm text-slate-600">{SONASID_TAGLINE}</p>

            <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-xs">
              <span className="chip">
                Modèle{' '}
                <span className="ml-1 font-mono">
                  {modelName === 'ollama' ? 'llama3.1:8b (local)' : modelName}
                </span>
              </span>
              <span className="chip">
                Période{' '}
                <span className="ml-1 font-mono">
                  {periodPreset === 'none' || !period?.start || !period?.end ? '—' : `${period.start} → ${period.end}`}
                </span>
              </span>
              <span className="chip">
                {busy ? 'Analyse…' : 'Prêt'}{' '}
                <span className={clsx('ml-1 inline-block h-1.5 w-1.5 rounded-full', busy ? 'bg-blue-500/70' : 'bg-emerald-500/80')} />
              </span>
            </div>
          </div>
          <div className="hidden md:flex absolute left-0 top-0 items-center">
            <SonasidBrandLogo compact />
          </div>
        </header>

        {/* Section KPIs rapides supprimée */}

        <section className="mt-5 grid gap-4 lg:grid-cols-12 flex-1 min-h-0 overflow-hidden">
          <aside className="panel lg:col-span-4 flex flex-col min-h-0">
            <div className="border-b border-slate-200 px-4 py-3">
              <div className="text-sm font-medium text-slate-900">Workspace</div>
              <div className="text-xs text-slate-600">Modèle, période & conversations</div>
            </div>

            <div className="p-4 space-y-4 flex-1 min-h-0 overflow-y-auto">
              <div className="rounded-2xl border border-slate-200/60 bg-white/45 p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-slate-700">Paramètres</div>
                  </div>
                </div>

                <div className="mt-3 grid gap-4">
                  <div>
                    <div className="text-[11px] font-medium text-slate-600">Modèle</div>
                    <div className="mt-1 grid grid-cols-3 gap-1 rounded-xl border border-slate-200/70 bg-white/60 p-1">
              <button
                type="button"
                className={clsx(
                          'min-w-0 rounded-lg px-3 py-2 text-xs font-medium transition-all duration-200 flex items-center justify-center gap-2',
                          modelName === 'trinity'
                            ? 'bg-white text-slate-900 shadow-sm'
                            : 'text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => onChangeModel('trinity')}
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-blue-500/80" />
                        Trinity
              </button>
              <button
                type="button"
                className={clsx(
                          'min-w-0 rounded-lg px-3 py-2 text-xs font-medium transition-all duration-200 flex items-center justify-center gap-2',
                          modelName === 'flash'
                            ? 'bg-white text-slate-900 shadow-sm'
                            : 'text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => onChangeModel('flash')}
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-fuchsia-500/80" />
                        Flash
              </button>
            <button
              type="button"
              className={clsx(
                          'min-w-0 rounded-lg px-3 py-2 text-xs font-medium transition-all duration-200 flex items-center justify-center gap-2',
                          modelName === 'ollama'
                            ? 'bg-white text-slate-900 shadow-sm'
                            : 'text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => onChangeModel('ollama')}
                        title="Local via Ollama (llama3.1:8b)"
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500/80" />
                        Llama3.1
            </button>
          </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-500">
                      <span className="inline-flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-blue-500/70" /> Cloud
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500/70" /> Local
                      </span>
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] font-medium text-slate-600">Période</div>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="flex-1 min-w-0">
                        <input
                          value={yearPick}
                          onChange={(e) => setYearPick(e.target.value.replace(/[^\d]/g, '').slice(0, 4))}
                          placeholder="Année (ex: 2025)"
                          className={clsx(
                            'w-full rounded-xl px-3 py-2 text-xs',
                            'bg-white/60 text-slate-900 placeholder:text-slate-400',
                            'border border-slate-200/60 focus:outline-none focus:ring-2 focus:ring-blue-500/15',
                            'transition-all duration-200',
                          )}
                          inputMode="numeric"
                        />
                      </div>
            <button
                        type="button"
                        className="rounded-xl border border-slate-200/60 bg-white/60 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white/80 transition-all duration-200"
                        onClick={() => {
                          const y = (yearPick || '').trim()
                          if (!/^\d{4}$/.test(y)) return
                          setPeriodPreset('custom')
                          setCustomStart(`${y}-01-01`)
                          setCustomEnd(`${y}-12-31`)
                        }}
                        title="Appliquer l’année"
                      >
                        OK
                      </button>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
              type="button"
              className={clsx(
                          'rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                          periodPreset === 'none'
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900'
                            : 'border-slate-200/60 bg-white/60 text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => setPeriodPreset('none')}
                        title="Ne pas ajouter de période automatiquement"
                      >
                        Aucune
            </button>
                      <button
                        type="button"
                        className={clsx(
                          'rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                          periodPreset === '7d'
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900'
                            : 'border-slate-200/60 bg-white/60 text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => setPeriodPreset('7d')}
                      >
                        7j
                      </button>
                      <button
                        type="button"
                        className={clsx(
                          'rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                          periodPreset === '30d'
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900'
                            : 'border-slate-200/60 bg-white/60 text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => setPeriodPreset('30d')}
                      >
                        30j
                      </button>
                      <button
                        type="button"
                        className={clsx(
                          'rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                          periodPreset === 'mtd'
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900'
                            : 'border-slate-200/60 bg-white/60 text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => setPeriodPreset('mtd')}
                      >
                        Mois
                      </button>
                      <button
                        type="button"
                        className={clsx(
                          'rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                          periodPreset === 'ytd'
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900'
                            : 'border-slate-200/60 bg-white/60 text-slate-600 hover:bg-white/80',
                        )}
                        onClick={() => setPeriodPreset('ytd')}
                      >
                        YTD
                      </button>
                </div>
                    <button
                      type="button"
                      className={clsx(
                        'mt-2 w-full rounded-xl border px-3 py-2 text-xs font-medium transition-all duration-200',
                        periodPreset === 'custom'
                          ? 'border-blue-500/20 bg-blue-500/5 text-slate-900'
                          : 'border-slate-200/60 bg-white/60 text-slate-600 hover:bg-white/80',
                      )}
                      onClick={() => setPeriodPreset('custom')}
                    >
                      Personnalisé…
                    </button>
                    {periodPreset === 'custom' ? (
                      <div className="mt-2 grid grid-cols-2 gap-2">
                  <input
                          type="date"
                          className="w-full rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-xs text-slate-900 outline-none focus:ring-2 focus:ring-blue-500/20 transition-all duration-200"
                          value={customStart}
                          onChange={(e) => setCustomStart(e.target.value)}
                          aria-label="Début"
                        />
                        <input
                          type="date"
                          className="w-full rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-xs text-slate-900 outline-none focus:ring-2 focus:ring-blue-500/20 transition-all duration-200"
                          value={customEnd}
                          onChange={(e) => setCustomEnd(e.target.value)}
                          aria-label="Fin"
                        />
                      </div>
                    ) : null}
                  </div>
              </div>
            </div>

              <div className="rounded-2xl border border-slate-200/60 bg-white/45 p-4 shadow-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs font-medium text-slate-700">Conversations</div>
                    <div className="mt-0.5 text-[11px] text-slate-500">
                      {historyBusy ? 'chargement…' : `${filteredHistory.length} conversation(s)`}
                    </div>
                  </div>
                  <button type="button" className="btn-ghost text-xs" onClick={createNewConversation}>
                    Nouvelle
                  </button>
                </div>

                <div className="mt-3">
                      <input
                    value={convSearch}
                    onChange={(e) => setConvSearch(e.target.value)}
                    placeholder="Rechercher…"
                    className={clsx(
                      'w-full rounded-xl px-3 py-2 text-xs',
                      'bg-white/60 text-slate-900 placeholder:text-slate-400',
                      'border border-slate-200/60 focus:outline-none focus:ring-2 focus:ring-blue-500/15',
                      'transition-all duration-200',
                    )}
                  />
                  </div>

                <div className="mt-3 max-h-[520px] overflow-auto space-y-2">
                  {filteredHistory.map((h) => (
                    <div
                      key={h.session_id}
                            className={clsx(
                        'group rounded-2xl border p-3 transition-all duration-200',
                        h.session_id === sessionId
                          ? 'border-blue-500/25 bg-blue-500/5'
                          : 'border-slate-200/60 bg-white/60 hover:bg-white/80 hover:border-slate-300/60',
                      )}
                    >
                      <button
                        type="button"
                        className="w-full text-left"
                        onClick={() => loadConversation(h.session_id)}
                        title={h.session_id}
                      >
                        <div className="text-xs font-medium text-slate-900 line-clamp-2">{h.title || h.session_id}</div>
                        {!clientMode ? (
                          <div className="mt-1 text-[11px] text-slate-500 font-mono">{h.session_id}</div>
                        ) : null}
                          </button>
                      <div className="mt-2 flex justify-end">
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-slate-500 hover:text-rose-700 hover:bg-rose-50/60 transition-all duration-200"
                          onClick={() => deleteConversation(h.session_id)}
                          aria-label="Supprimer conversation"
                          title="Supprimer"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path
                              d="M9 3h6m-8 4h10m-9 0 1 14h6l1-14M10 7v12m4-12v12"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                          <span className="text-[11px]">Supprimer</span>
                        </button>
                      </div>
                    </div>
                  ))}
                  {filteredHistory.length === 0 ? (
                    <div className="rounded-xl border border-slate-200/60 bg-white/60 p-3 text-xs text-slate-600">
                      Aucune conversation pour l’instant.
              </div>
            ) : null}
                </div>
              </div>
            </div>
          </aside>

          <div className="panel lg:col-span-8 flex flex-col min-h-0 overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <div>
                <div className="text-sm font-medium text-slate-900">Chat</div>
                <div className="text-xs text-slate-600">{SONASID_CHAT_SUBTITLE}</div>
              </div>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <button
                  type="button"
                  className="btn-ghost text-[11px] px-3 py-1.5"
                  onClick={() => {
                    const next = theme === 'dark' ? 'light' : 'dark'
                    setTheme(next)
                    localStorage.setItem('sonasid_theme', next)
                  }}
                >
                  Mode {theme === 'dark' ? 'clair' : 'sombre'}
                </button>
                <span>{busy ? 'appel…' : 'prêt'}</span>
              </div>
            </div>

            <div
              ref={chatScrollRef}
              onScroll={onChatScroll}
              className="flex-1 min-h-0 overflow-y-auto px-4 py-4 scroll-smooth"
            >
                  <div className="flex flex-col gap-3">
                    {isWelcomeOnly ? (
                      <div className="min-h-[46vh] flex flex-col items-center justify-center text-center px-2">
                        <div className="text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
                          {actorName ? `Bonjour ${actorName}.` : 'Bonjour.'}
                        </div>
                        <div className="mt-3 max-w-[44rem] text-base text-slate-600 dark:text-slate-300">
                          Dites-moi ce que vous voulez consulter.
                        </div>
                        <div className="mt-4 max-w-[48rem] text-sm text-slate-600 dark:text-slate-300">
                          {SONASID_WELCOME_HINT}
                        </div>
                      </div>
                    ) : null}
                    {chat.map((m, idx) => (
                      <div
                        key={idx}
                    className={clsx('max-w-[92%] w-fit fade-in', m.role === 'user' ? 'bubble-user' : 'bubble-ai')}
                  >
                    <div className="whitespace-pre-wrap">{m.content}</div>
                    {m.role !== 'user' && m?.meta?.raw && isTableRows(m.meta.raw.result) ? (
                      (() => {
                        const rows = m.meta.raw.result
                        const expanded = Boolean(expandedRowsByMsg[idx])
                        if (!expanded && rows.length <= 5) return null
                        const hiddenCount = Math.max(0, rows.length - 5)
                        return (
                          <div className="mt-2">
                            {!expanded ? (
                              <button
                                type="button"
                                className="btn-ghost text-xs"
                                onClick={() =>
                                  setExpandedRowsByMsg((prev) => ({
                                    ...prev,
                                    [idx]: true,
                                  }))
                                }
                              >
                                Voir les {rows.length} lignes
                              </button>
                            ) : (
                              <>
                                <MiniTable rows={rows} maxHeight={280} />
                                <div className="mt-2 flex items-center justify-between">
                                  <div className="text-[11px] text-slate-500">
                                    {rows.length} lignes
                                  </div>
                                  <button
                                    type="button"
                                    className="btn-ghost text-xs"
                                    onClick={() =>
                                      setExpandedRowsByMsg((prev) => ({
                                        ...prev,
                                        [idx]: false,
                                      }))
                                    }
                                  >
                                    Replier
                                  </button>
                                </div>
                              </>
                            )}
                          </div>
                        )
                      })()
                    ) : null}
                    {m?.created_at ? (
                      <div
                        className={clsx(
                          'mt-1 text-[10px] text-right select-none',
                          m.role === 'user'
                            ? 'text-white/75 drop-shadow-[0_1px_1px_rgba(0,0,0,0.25)]'
                            : 'text-slate-500/80',
                        )}
                      >
                        {formatMsgTime(m.created_at)}
                      </div>
                    ) : null}
                      </div>
                    ))}
                {busy ? (
                  <div className="max-w-[92%] bubble-ai animate-pulse">
                    <div className="flex items-center gap-2 text-slate-600">
                      <span className="inline-block h-2 w-2 rounded-full bg-blue-500/70" />
                      <span className="inline-block h-2 w-2 rounded-full bg-fuchsia-500/60" />
                      <span className="inline-block h-2 w-2 rounded-full bg-slate-400/50" />
                      <span className="ml-1 text-xs text-slate-500">en train d’écrire…</span>
                    </div>
                  </div>
                ) : null}
                    <div ref={chatEndRef} />
                  </div>
                </div>

                <form
              className="flex gap-2 border-t border-slate-200 p-3"
                  onSubmit={(e) => {
                    e.preventDefault()
                    sendChat(chatInput)
                  }}
                >
                  <input
                    className={clsx(
                  'flex-1 rounded-xl px-4 py-3 text-sm',
                  'bg-white/70 text-slate-900 placeholder:text-slate-400',
                  'border border-slate-200/80 focus:outline-none focus:ring-2 focus:ring-blue-500/20',
                  'transition-all duration-200',
                )}
                placeholder={SONASID_CHAT_PLACEHOLDER}
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                  />
              <button type="submit" className={clsx('btn-primary', busy ? 'opacity-60' : '')} disabled={busy}>
                    Envoyer
                  </button>
                </form>
          </div>
        </section>
      </div>
    </div>
  )
}

