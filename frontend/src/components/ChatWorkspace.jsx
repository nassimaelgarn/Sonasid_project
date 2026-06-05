import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { kpiApiBase } from '../lib/apiBase'
import {
  SONASID_CHAT_PLACEHOLDER,
  SONASID_CHAT_SUBTITLE,
  SONASID_TAGLINE,
  SONASID_WELCOME_HINT,
  buildSonasidWelcomeText,
} from '../lib/sonasidCopy'
import { ChatMarkdown } from '../lib/chatMarkdown'
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

function clsx(...xs) {
  return xs.filter(Boolean).join(' ')
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
  if (data && typeof data === 'object' && data.ok === false) {
    const msg = data?.message || data?.error || 'Erreur'
    throw new Error(msg)
  }
  return data
}

function IconSun({ className }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="2" />
      <path
        d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}

function IconMoon({ className }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** Icône « panneau latéral » (style apps type ChatGPT). */
function IconSidebar({ className }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="M9 4v16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function IconPlus({ className }) {
  return (
    <svg className={className} width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  )
}

function IconMic({ className }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M19 11a7 7 0 0 1-14 0M12 18v3M8 21h8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function IconGear({ className }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" stroke="currentColor" strokeWidth="2" />
      <path
        d="M19.4 15a7.9 7.9 0 0 0 .1-1 7.9 7.9 0 0 0-.1-1l2.1-1.6-2-3.4-2.5 1a8.2 8.2 0 0 0-1.7-1L15 3h-6l-.3 3a8.2 8.2 0 0 0-1.7 1l-2.5-1-2 3.4L4.6 13a7.9 7.9 0 0 0-.1 1c0 .3 0 .7.1 1l-2.1 1.6 2 3.4 2.5-1c.5.4 1.1.8 1.7 1l.3 3h6l.3-3c.6-.2 1.2-.6 1.7-1l2.5 1 2-3.4L19.4 15Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

const CHAT_MODEL_OPTIONS = [
  { id: 'trinity', label: 'Trinity', hint: 'Cloud · OpenRouter', dot: 'bg-blue-500' },
  { id: 'flash', label: 'Flash', hint: 'Cloud · rapide', dot: 'bg-fuchsia-500' },
  { id: 'ollama', label: 'Llama3.1', hint: 'Local · Ollama', dot: 'bg-emerald-500' },
]

function IconThumbUp({ className }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M7 22V11h2a2 2 0 0 0 2-2V7a3 3 0 0 1 3-3h.5A2.5 2.5 0 0 1 17 6.5V10l2.2 2.2a2 2 0 0 1 .5 1.3V20a2 2 0 0 1-2 2H11a2 2 0 0 1-2-2v-1H7Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function IconThumbDown({ className }) {
  return (
    <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M17 2v11h-2a2 2 0 0 0-2 2v2a3 3 0 0 1-3 3h-.5A2.5 2.5 0 0 1 7 17.5V14L4.8 11.8a2 2 0 0 1-.5-1.3V4a2 2 0 0 1 2-2h6.5a2 2 0 0 1 2 2v1H17Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function IconCopy({ className }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M9 9h10v10H9V9Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}

function IconPencil({ className }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 20h9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function IconCheck({ className }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M20 6 9 17l-5-5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function getPrecedingUserContent(chat, assistantIdx) {
  for (let i = assistantIdx - 1; i >= 0; i--) {
    if (chat[i]?.role === 'user') return String(chat[i].content ?? '')
  }
  return ''
}

function userAskedForSql(text) {
  const tl = String(text || '').toLowerCase()
  return (
    /\b(requête|requete|query)\s*(sql)?\b/.test(tl) ||
    /\bsql\b/.test(tl) ||
    /\b(montre|affiche|donne|donne-moi)\b.{0,40}\b(sql|requête|requete)\b/.test(tl) ||
    /\bquelle est la requête\b/.test(tl)
  )
}

function extractSqlPayload(raw, { userQuestion = '' } = {}) {
  if (!userAskedForSql(userQuestion)) {
    const src = String(raw?.source || '')
    if (!src.startsWith('sql:') && src !== 'sql:kpi_catalog') return null
  }
  if (!raw || typeof raw !== 'object') return null
  // KPI catalog: list of {kpi, tsql}
  if (String(raw?.source || '') === 'sql:kpi_catalog' && Array.isArray(raw?.result)) {
    const blocks = raw.result
      .filter((r) => r && typeof r === 'object')
      .map((r) => {
        const label = String(r.kpi || '').trim()
        const text = String(r.tsql || '').trim()
        if (!label || !text) return null
        return { label, text }
      })
      .filter(Boolean)
    if (!blocks.length) return null
    const combined = blocks.map((b) => `${b.label}:\n${b.text}`).join('\n\n')
    return { kind: 'catalog', blocks, combined }
  }
  const sql = typeof raw.sql === 'string' ? raw.sql.trim() : ''
  const tsql = typeof raw.tsql === 'string' ? raw.tsql.trim() : ''
  const eaf = typeof raw?.sqls?.eaf === 'string' ? raw.sqls.eaf.trim() : ''
  const lf = typeof raw?.sqls?.lf === 'string' ? raw.sqls.lf.trim() : ''
  const teaf = typeof raw?.tsqls?.eaf === 'string' ? raw.tsqls.eaf.trim() : ''
  const tlf = typeof raw?.tsqls?.lf === 'string' ? raw.tsqls.lf.trim() : ''
  if (tsql || sql) {
    const blocks = []
    if (tsql) blocks.push({ label: 'T-SQL (Azure)', text: tsql })
    if (sql) blocks.push({ label: 'SQLite', text: sql })
    const combined = blocks.map((b) => `${b.label}:\n${b.text}`).join('\n\n')
    return { kind: 'single', blocks, combined }
  }
  const blocks = []
  if (teaf) blocks.push({ label: 'T-SQL EAF', text: teaf })
  if (tlf) blocks.push({ label: 'T-SQL LF', text: tlf })
  if (eaf) blocks.push({ label: 'SQLite EAF', text: eaf })
  if (lf) blocks.push({ label: 'SQLite LF', text: lf })
  if (!blocks.length) return null
  const combined = blocks.map((b) => `${b.label}:\n${b.text}`).join('\n\n')
  return { kind: 'multi', blocks, combined }
}

async function copyToClipboard(text) {
  const t = String(text || '').trim()
  if (!t) return false
  try {
    await navigator.clipboard.writeText(t)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = t
      ta.setAttribute('readonly', '')
      ta.style.position = 'absolute'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return Boolean(ok)
    } catch {
      return false
    }
  }
}

function formatMsgTime(createdAtSeconds) {
  const t = Number(createdAtSeconds)
  if (!Number.isFinite(t) || t <= 0) return ''
  const d = new Date(t * 1000)
  if (!Number.isFinite(d.getTime())) return ''
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function kpiRewritePrefix(res) {
  const kr = res?.kpi_rewrite
  if (!kr?.used || !kr.canonical_question) return ''
  const p = kr.provider ? ` (${kr.provider})` : ''
  return `[Interprétation : ${String(kr.canonical_question)}]${p}\n\n`
}

function withKpiInterpretation(text, res) {
  const interp = typeof res?.interpretation === 'string' ? res.interpretation.trim() : ''
  if (!interp) return text
  return `${text}\n\n---\n\n**Analyse**\n\n${interp}`
}

function isCompareResponse(raw) {
  if (!raw || typeof raw !== 'object' || raw.error) return false
  const src = String(raw.source || '')
  if (!src.includes('compare_periods')) return false
  return Boolean(raw.period_a?.range && raw.period_b?.range)
}

function formatAssistantCompact(res, { clientMode } = { clientMode: false }) {
  if (!res || typeof res !== 'object') return String(res ?? '')
  if (res?.error) return res?.message ? res.message : `Erreur: ${res.error}`
  const kp = kpiRewritePrefix(res)
  const w = (s) => (kp ? kp + s : s)
  if (res?.message && String(res.message).trim()) return w(res.message)
  if ((typeof res?.tsql === 'string' && res.tsql.trim()) || (typeof res?.sql === 'string' && res.sql.trim())) {
    const parts = []
    if (typeof res?.tsql === 'string' && res.tsql.trim()) parts.push(`T-SQL (Azure):\n${res.tsql.trim()}`)
    if (typeof res?.sql === 'string' && res.sql.trim()) parts.push(`SQLite:\n${res.sql.trim()}`)
    return w(`Requêtes SQL:\n\n${parts.join('\n\n')}`)
  }
  if (res?.sqls && typeof res.sqls === 'object') {
    const eaf = String(res.sqls?.eaf ?? '').trim()
    const lf = String(res.sqls?.lf ?? '').trim()
    const teaf = String(res.tsqls?.eaf ?? '').trim()
    const tlf = String(res.tsqls?.lf ?? '').trim()
    const parts = []
    if (teaf) parts.push(`T-SQL EAF:\n${teaf}`)
    if (tlf) parts.push(`T-SQL LF:\n${tlf}`)
    if (eaf) parts.push(`EAF:\n${eaf}`)
    if (lf) parts.push(`LF:\n${lf}`)
    if (parts.length) return w(`Requêtes SQL:\n\n${parts.join('\n\n')}`)
  }
  if (res?.notice) {
    if (clientMode && /LLM indisponible/i.test(String(res.notice))) {
      return w(
        "Assistant IA temporairement indisponible. Je t’affiche quand même le résultat via le moteur KPI.",
      )
    }
    return w(res.notice)
  }

  if (isCompareResponse(res)) {
    const metric = String(res.metric || 'valeur')
    const a = res.period_a || {}
    const b = res.period_b || {}
    const ra = String(a.range || '').trim()
    const rb = String(b.range || '').trim()
    const va = typeof a.value === 'number' ? a.value : null
    const vb = typeof b.value === 'number' ? b.value : null
    const delta = typeof res.delta === 'number' ? res.delta : null
    const pct = typeof res.delta_percent === 'number' ? res.delta_percent : null
    const fmt = (v) => {
      if (v == null) return '—'
      if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString('fr-FR') : v.toFixed(2)
      return String(v)
    }
    const sign = (v) => (typeof v === 'number' && v > 0 ? '+' : '')
    const lines = [
      `Comparaison (${metric})`,
      ra ? `- Période A (${ra}) : ${fmt(va)}` : null,
      rb ? `- Période B (${rb}) : ${fmt(vb)}` : null,
      delta != null ? `- Δ (B − A) : ${sign(delta)}${fmt(delta)}` : null,
      pct != null ? `- Δ % : ${sign(pct)}${pct.toFixed(1)} %` : null,
    ].filter(Boolean)
    return w(withKpiInterpretation(lines.join('\n'), res))
  }

  // Common KPI fields → readable text (client-friendly)
  if (typeof res?.TD_percent === 'number') {
    return w(withKpiInterpretation(`TD: ${res.TD_percent}%`, res))
  }
  if (typeof res?.TR_percent === 'number') {
    return w(withKpiInterpretation(`TR: ${res.TR_percent}%`, res))
  }
  if (typeof res?.MTBF_secondes === 'number') {
    return w(withKpiInterpretation(`MTBF: ${formatDurationSeconds(res.MTBF_secondes)}`, res))
  }
  if (typeof res?.MTTR_secondes === 'number') {
    return w(withKpiInterpretation(`MTTR: ${formatDurationSeconds(res.MTTR_secondes)}`, res))
  }
  if (typeof res?.Rendement_percent === 'number') {
    return w(withKpiInterpretation(`Rendement: ${res.Rendement_percent}%`, res))
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
      // underlying values are often Wh-like large integers
      const num = Number.isInteger(v) ? v.toLocaleString('fr-FR') : v.toLocaleString('fr-FR', { maximumFractionDigits: 2 })
      // If MWh is present, the electric components are in kWh.
      const isElec = typeof res?.Consommation_MWh === 'number'
      const suffix = isElec && (k === 'Consommation_Totale' || k === 'Consommation_EAF' || k === 'Consommation_LF') ? ' kWh' : ''
      return `${num}${suffix}`
    }
    return w(
      withKpiInterpretation(
        consoKeys.map((k) => `${k.replace('Consommation_', '')}: ${fmtConso(k, res[k])}`).join('\n'),
        res,
      ),
    )
  }

  if (typeof res?.result === 'number') {
    if (res.result === 1 && !res.nombre_arrivages && !res.tonnage_importe && !res.tonnage_total) {
      return w(
        res.message ||
          'Je n’ai pas identifié un indicateur précis. Reformule un KPI (ex. nombre des arrivages, tonnage importé fournisseur id 40).',
      )
    }
    return w(withKpiInterpretation(`Résultat: ${res.result}`, res))
  }
  if (Array.isArray(res?.result)) {
    const arr = res.result
    if (!arr.length) return w('Aucun résultat.')

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

      const isWidthOrThicknessTop =
        (keys.includes('largeur') || keys.includes('epaisseur') || keys.includes('épaisseur')) &&
        (keys.includes('production') || keys.includes('poids_brames') || keys.includes('poids'))

      if (isWidthOrThicknessTop) {
        const dimKey = keys.includes('largeur') ? 'largeur' : keys.includes('épaisseur') ? 'épaisseur' : 'epaisseur'
        const valKey = keys.includes('production') ? 'production' : keys.includes('poids_brames') ? 'poids_brames' : 'poids'
        const label = dimKey === 'largeur' ? 'Top largeurs' : 'Top épaisseurs'
        const unitHint = valKey === 'production' ? ' (poids total – unité brute)' : ''
        const preview = arr.slice(0, 6).map((row) => {
          const d = fmt(row?.[dimKey])
          const v = fmt(row?.[valKey])
          return `- ${d} → ${v}`
        })
        return w(withKpiInterpretation([`${label}${unitHint}`, ...preview].join('\n'), res))
      }

      const previewRows = (() => {
        if (!isSimplePeriodValue) return arr.slice(0, 5)
        // For monthly/day series, show first 4 + last (so late months like June aren't hidden).
        if (arr.length <= 5) return arr
        return [...arr.slice(0, 4), { period: '…', value: null }, arr[arr.length - 1]]
      })()

      const preview = previewRows.map((row) => {
        if (isSimplePeriodValue) {
          const p = row?.period === '…' ? '…' : fmt(row?.period)
          const v = row?.period === '…' ? '' : fmt(row?.value)
          return row?.period === '…' ? '…' : `${p}: ${v}`
        }
        const parts = keys.map((k) => `${k}: ${fmt(row?.[k])}`)
        return parts.join(' · ')
      })
      // Keep chat clean; extra rows are accessible via the "Voir les N lignes" button.
      return w(withKpiInterpretation(preview.join('\n'), res))
    }

    // Fallback: array of primitives
    const preview = arr.slice(0, 8).map((v) => `${fmt(v)}`)
    return w(withKpiInterpretation(preview.join('\n'), res))
  }

  // Fallback: show non-technical keys only.
  const hidden = new Set([
    'question',
    'source',
    'llm_status',
    'llm_reason',
    'llm_provider',
    'llm_sql',
    'kpi_rewrite',
    'interpretation',
  ])
  const keys = Object.keys(res).filter((k) => !hidden.has(k))
  if (!keys.length) return w('OK.')
  return w(keys.map((k) => `${k}: ${JSON.stringify(res[k])}`).join('\n'))
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

function mapHistoryToChat(msgs, { clientMode } = { clientMode: false }) {
  if (!Array.isArray(msgs) || !msgs.length) return []
  return msgs.map((m) => {
    const role = m.role === 'assistant' ? 'assistant' : 'user'
    const created_at = typeof m.created_at === 'number' ? m.created_at : Number(m.created_at || 0)
    if (role === 'assistant') {
      const parsed = parseAssistantHistoryMessage(m.content, { clientMode })
      return { role, content: parsed.content, meta: parsed.meta, created_at }
    }
    return { role, content: String(m.content ?? ''), created_at }
  })
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

function seriesPeriodKey(r0) {
  if (!r0 || typeof r0 !== 'object') return null
  if (Object.prototype.hasOwnProperty.call(r0, 'period')) return 'period'
  if (Object.prototype.hasOwnProperty.call(r0, 'periode')) return 'periode'
  return null
}

function seriesValueKey(r0) {
  if (!r0 || typeof r0 !== 'object') return null
  if (Object.prototype.hasOwnProperty.call(r0, 'value')) return 'value'
  if (Object.prototype.hasOwnProperty.call(r0, 'poids')) return 'poids'
  if (Object.prototype.hasOwnProperty.call(r0, 'nombre_arrivages')) return 'nombre_arrivages'
  if (Object.prototype.hasOwnProperty.call(r0, 'tonnage_total')) return 'tonnage_total'
  if (Object.prototype.hasOwnProperty.call(r0, 'tonnage')) return 'tonnage'
  if (Object.prototype.hasOwnProperty.call(r0, 'tonnage_importe')) return 'tonnage_importe'
  if (Object.prototype.hasOwnProperty.call(r0, 'tonnage_transfere')) return 'tonnage_transfere'
  if (Object.prototype.hasOwnProperty.call(r0, 'tonnage_decharge')) return 'tonnage_decharge'
  if (Object.prototype.hasOwnProperty.call(r0, 'tonnage_importe')) return 'tonnage_importe'
  return null
}

function isPeriodValueSeries(res) {
  const rows = res?.result
  if (!isTableRows(rows)) return false
  const r0 = rows[0]
  return Boolean(seriesPeriodKey(r0) && seriesValueKey(r0))
}

function isScalarSonasidKpi(res) {
  if (!res || typeof res !== 'object' || res.error) return false
  if (isTableRows(res.result)) return false
  const ql = String(res.question || '').toLowerCase()
  if (/\b(liste|détail|detail|quels|quelles)\b/.test(ql)) return false
  return (
    typeof res.nombre_arrivages === 'number' ||
    typeof res.nombre_navires === 'number' ||
    typeof res.tonnage_importe === 'number' ||
    typeof res.tonnage_total === 'number' ||
    (typeof res.result === 'number' && looksLikeKpiQuestion(String(res.question || '')))
  )
}

function wantsSonasidChartAugment(qLower) {
  const ql = String(qLower || '')
  if (/\bpar\s+(mois|jour|semaine|année|annee)\b/.test(ql)) return false
  if (/\b(liste|détail|detail|quels|quelles)\b/.test(ql)) return false
  if (!looksLikeKpiQuestion(ql)) return false
  if (/\b(donne|donner|affiche|afficher|sql|requête|requete)\b/.test(ql)) return false
  return true
}

function sonasidChartNote() {
  return 'Courbe : évolution par mois (même indicateur et filtres que le total).'
}

function shouldAugmentWithChart(res, q3) {
  const ql = String(q3 || '').toLowerCase()
  if (isScalarConsoElec(res) && wantsConsoElecAugment(ql)) return true
  if (isScalarSonasidKpi(res) && wantsSonasidChartAugment(ql)) return true
  return false
}

async function fetchChartAugmentation(res, q3, { baseUrl, sessionId, modelName, periodPreset, period }) {
  const ql = String(q3 || '').toLowerCase()
  if (isScalarConsoElec(res) && wantsConsoElecAugment(ql)) {
    const spec = consoAutoSeriesSpec(q3)
    const qSeries = buildConsoSeriesQuestion(q3)
    const aug = await apiChat(baseUrl, qSeries, sessionId, modelName, { periodPreset, period })
    if (isPeriodValueSeries(aug)) {
      return {
        ...stripScalarConsoElecFields(res),
        result: aug.result,
        _chart_note: spec.note,
      }
    }
    return null
  }
  if (isScalarSonasidKpi(res) && wantsSonasidChartAugment(ql)) {
    const qSeries = buildParMoisQuickQuestion(q3, { periodPreset, period })
    if (!qSeries) return null
    const aug = await apiChat(baseUrl, qSeries, sessionId, modelName, { periodPreset, period })
    if (isPeriodValueSeries(aug) || extractChartSpec(aug)) {
      return { ...res, result: aug.result, _chart_note: sonasidChartNote() }
    }
  }
  return null
}

function formatChatContent(res, { clientMode } = {}) {
  const compact = formatAssistantCompact(res, { clientMode })
  if (res?._chart_note && !String(compact).includes(String(res._chart_note).slice(0, 20))) {
    return `${compact}\n\n${res._chart_note}`
  }
  return compact
}

/** Affiche le chiffre tout de suite, charge la courbe en arrière-plan (évite écran blanc / freeze). */
function scheduleChartAugment(res, q3, ctx, setChatState) {
  if (!shouldAugmentWithChart(res, q3) || typeof setChatState !== 'function') return
  const { baseUrl, sessionId, modelName, periodPreset, period, clientMode } = ctx
  fetchChartAugmentation(res, q3, { baseUrl, sessionId, modelName, periodPreset, period })
    .then((aug) => {
      if (!aug) return
      setChatState((prev) => {
        const next = [...prev]
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === 'assistant') {
            next[i] = {
              ...next[i],
              content: formatChatContent(aug, { clientMode }),
              meta: { raw: aug },
            }
            break
          }
        }
        return next
      })
    })
    .catch(() => null)
}

function isScalarConsoElec(res) {
  if (!res || typeof res !== 'object' || res.error || res.message) return false
  if (Array.isArray(res.result)) return false
  return (
    typeof res.Consommation_Totale === 'number' ||
    typeof res.Consommation_MWh === 'number'
  )
}

function wantsConsoElecAugment(qLower) {
  const ql = qLower || ''
  const isConso = /consomm|conso/.test(ql)
  const isElec =
    /élec|elec|électrique|electricite|électricité/.test(ql) ||
    (/consommation\b/.test(ql) && !/oxyg|gpl|carbon|carbone|gaz|ferraille/.test(ql))
  if (!isConso || !isElec) return false
  return true
}

function consoRequestedBucket(qLower) {
  const ql = String(qLower || '')
  if (/\bpar\s+(jour|journée)\b/.test(ql)) return 'par jour'
  if (/\bpar\s+semaine\b/.test(ql)) return 'par semaine'
  if (/\bpar\s+mois\b/.test(ql)) return 'par mois'
  if (/\bpar\s+(an|année)\b/.test(ql)) return 'par année'
  return ''
}

function buildConsoSeriesQuestion(question) {
  const q = String(question || '').trim()
  if (!q) return q
  const ql = q.toLowerCase()
  const desired = consoRequestedBucket(ql) || consoAutoSeriesSpec(q).suffix
  const stripped = q.replace(/\bpar\s+(mois|jour|journée|semaine|an|année)\b/gi, '').replace(/\s+/g, ' ').trim()
  // Always end with the desired granularity (once).
  return desired ? `${stripped} ${desired}`.replace(/\s+/g, ' ').trim() : stripped
}

function consoAutoSeriesSpec(question) {
  const q = String(question || '')
  const m = q.match(/\bdu\s+(\d{4}-\d{2}-\d{2})\s+(?:au|a|à)\s+(\d{4}-\d{2}-\d{2})\b/i)
  if (m) {
    const a = new Date(`${m[1]}T00:00:00`)
    const b = new Date(`${m[2]}T00:00:00`)
    const days =
      Number.isFinite(a.getTime()) && Number.isFinite(b.getTime())
        ? Math.round((b.getTime() - a.getTime()) / 86400000)
        : 9999
    if (days <= 40) {
      return {
        suffix: 'par jour',
        note: 'Courbe : consommation par jour (même filtres / période que le total).',
      }
    }
  }
  return {
    suffix: 'par mois',
    note: 'Courbe : consommation par mois (même filtres / période que le total).',
  }
}

function stripScalarConsoElecFields(res) {
  if (!res || typeof res !== 'object') return res
  const next = { ...res }
  delete next.Consommation_Totale
  delete next.Consommation_MWh
  delete next.Consommation_EAF
  delete next.Consommation_LF
  return next
}

/** Déduit un libellé court pour l’axe Y selon la question / le type de réponse */
function chartYLabel(raw) {
  const q = String(raw?.question || '').toLowerCase()
  if (/consomm|conso/.test(q) && (/élec|elec|électrique/.test(q) || /consommation\b/.test(q))) return 'Électricité (unités source)'
  if (/arrivage/.test(q) && !/tonnage/.test(q)) return 'Nombre d\'arrivages'
  if (/tonnage/.test(q) && /import/.test(q)) return 'Tonnage importé (t)'
  if (/tonnage/.test(q) && /transf/.test(q)) return 'Tonnage transféré (t)'
  if (/tonnage/.test(q)) return 'Tonnage (t)'
  if (/navire/.test(q)) return 'Navires'
  if (/décharg|decharg/.test(q) && /tonnage/.test(q)) return 'Tonnage déchargé (t)'
  if (/restant|reste/.test(q)) return 'Tonnage restant (t)'
  if (/production/.test(q)) return 'Production'
  if (/oxyg/.test(q)) return 'Oxygène'
  if (/gpl|gaz/.test(q)) return 'GPL'
  if (/carbon|carbone/.test(q)) return 'Carbone'
  if (/rendement|td|tr|mtbf|mttr/.test(q)) return 'Valeur'
  return 'Valeur'
}

function _fillDailyGapsIfRange(raw, rows, { valKey }) {
  const q = String(raw?.question || '')
  const m = q.match(/\bdu\s+(\d{4}-\d{2}-\d{2})\s+(?:au|a|à)\s+(\d{4}-\d{2}-\d{2})\b/i)
  if (!m) return rows

  const start = new Date(`${m[1]}T00:00:00`)
  const end = new Date(`${m[2]}T00:00:00`)
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) return rows

  const days = Math.round((end.getTime() - start.getTime()) / 86400000)
  if (!(days >= 0 && days <= 120)) return rows

  // Only fill gaps for daily-looking periods (YYYY-MM-DD).
  const p0 = rows?.[0]?.period
  const p0s = String(p0 ?? '')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(p0s)) return rows

  const by = new Map(rows.map((r) => [String(r.period ?? ''), r]))
  const out = []
  for (let i = 0; i <= days; i++) {
    const d = new Date(start.getTime() + i * 86400000)
    const iso = d.toISOString().slice(0, 10)
    const existing = by.get(iso)
    if (existing) {
      out.push(existing)
    } else {
      const base = { period: iso, [valKey]: 0 }
      if (typeof rows?.[0]?.eaf === 'number') base.eaf = 0
      if (typeof rows?.[0]?.lf === 'number') base.lf = 0
      out.push(base)
    }
  }
  return out
}

/**
 * Extrait une spec pour Chart.js : ligne (period + value) ou barres (grade|categorie + value).
 */
function extractChartSpec(raw) {
  let rows = raw?.result
  if (!isTableRows(rows)) return null
  const r0 = rows[0]

  const pKey = seriesPeriodKey(r0)
  const vKey = seriesValueKey(r0)
  if (pKey && vKey) {
    rows = rows.map((r) => ({
      ...r,
      period: r.period ?? r.periode,
      value: r.value ?? r[vKey],
    }))
    rows = _fillDailyGapsIfRange(raw, rows, { valKey: 'value' })
    const labels = rows.map((r) => String(r.period ?? ''))
    const hasEafLf =
      rows.length > 0 &&
      rows.every((r) => typeof r.eaf === 'number' && typeof r.lf === 'number' && typeof r.value === 'number')
    const datasets = []
    if (hasEafLf) {
      datasets.push({
        label: 'EAF',
        data: rows.map((r) => Number(r.eaf) || 0),
        borderColor: 'rgba(59, 130, 246, 0.95)',
        backgroundColor: 'rgba(59, 130, 246, 0.12)',
        tension: 0.25,
        fill: false,
        pointRadius: 2,
      })
      datasets.push({
        label: 'LF',
        data: rows.map((r) => Number(r.lf) || 0),
        borderColor: 'rgba(168, 85, 247, 0.95)',
        backgroundColor: 'rgba(168, 85, 247, 0.1)',
        tension: 0.25,
        fill: false,
        pointRadius: 2,
      })
      datasets.push({
        label: 'Total',
        data: rows.map((r) => Number(r.value) || 0),
        borderColor: 'rgba(14, 165, 233, 0.95)',
        backgroundColor: 'rgba(14, 165, 233, 0.08)',
        tension: 0.2,
        fill: true,
        pointRadius: 3,
      })
    } else {
      datasets.push({
        label: chartYLabel(raw),
        data: rows.map((r) => Number(r.value) || 0),
        borderColor: 'rgba(59, 130, 246, 1)',
        backgroundColor: 'rgba(59, 130, 246, 0.14)',
        tension: 0.25,
        fill: true,
        pointRadius: 3,
      })
    }
    return { kind: 'line', labels, datasets }
  }

  if (r0.grade != null && r0.value != null) {
    return {
      kind: 'bar',
      labels: rows.map((r) => String(r.grade ?? '')),
      datasets: [
        {
          label: chartYLabel(raw),
          data: rows.map((r) => Number(r.value) || 0),
          backgroundColor: rows.map((_, i) =>
            i % 2 === 0 ? 'rgba(59, 130, 246, 0.65)' : 'rgba(168, 85, 247, 0.6)',
          ),
          borderRadius: 6,
        },
      ],
    }
  }

  const catKey = r0.categorie != null ? 'categorie' : null
  const valK = r0.value != null ? 'value' : r0.poids != null ? 'poids' : null
  if (catKey && valK) {
    return {
      kind: 'bar',
      labels: rows.map((r) => String(r[catKey] ?? '')),
      datasets: [
        {
          label: chartYLabel(raw),
          data: rows.map((r) => Number(r[valK]) || 0),
          backgroundColor: 'rgba(14, 165, 233, 0.55)',
          borderRadius: 6,
        },
      ],
    }
  }

  if (r0.qualite != null && r0.value != null && rows.length >= 1 && rows.length <= 40) {
    const labels = rows.map((r) => String(r.qualite ?? r.qualite_id ?? ''))
    return {
      kind: 'bar',
      labels,
      datasets: [
        {
          label: chartYLabel(raw),
          data: rows.map((r) => Number(r.value) || 0),
          backgroundColor: labels.map((_, i) =>
            i % 2 === 0 ? 'rgba(14, 165, 233, 0.6)' : 'rgba(245, 158, 11, 0.55)',
          ),
          borderRadius: 6,
        },
      ],
    }
  }

  if (r0.poids_net != null && rows.length >= 2 && rows.length <= 120) {
    const agg = new Map()
    for (const r of rows) {
      const label = String(r.qualite ?? r.qualite_id ?? '—')
      agg.set(label, (agg.get(label) || 0) + (Number(r.poids_net) || 0))
    }
    const labels = [...agg.keys()]
    if (labels.length >= 1 && labels.length <= 30) {
      return {
        kind: 'bar',
        labels,
        datasets: [
          {
            label: chartYLabel(raw),
            data: labels.map((lb) => agg.get(lb) || 0),
            backgroundColor: 'rgba(14, 165, 233, 0.55)',
            borderRadius: 6,
          },
        ],
      }
    }
  }

  return null
}

function ResultChart({ raw, theme }) {
  const spec = useMemo(() => extractChartSpec(raw), [raw])
  const isDark = theme === 'dark'

  const options = useMemo(() => {
    if (!spec) return {}
    const tick = isDark ? '#cbd5e1' : '#475569'
    const grid = isDark ? 'rgba(148,163,184,0.18)' : 'rgba(148,163,184,0.25)'
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: spec.kind === 'line' && spec.datasets?.length > 1,
          labels: { color: tick, boxWidth: 12 },
        },
        tooltip: {
          backgroundColor: isDark ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.98)',
          titleColor: isDark ? '#f1f5f9' : '#0f172a',
          bodyColor: isDark ? '#e2e8f0' : '#334155',
          borderColor: isDark ? 'rgba(71,85,105,0.6)' : 'rgba(203,213,225,0.9)',
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          ticks: { color: tick, maxRotation: 45, minRotation: 0 },
          grid: { color: grid },
        },
        y: {
          ticks: { color: tick },
          grid: { color: grid },
        },
      },
    }
  }, [isDark, spec])

  if (!spec) return null

  const data = { labels: spec.labels, datasets: spec.datasets }
  const h = spec.kind === 'line' ? 240 : 220

  return (
    <div
      className="mt-3 rounded-xl border border-slate-200/70 dark:border-slate-600/50 bg-white/50 dark:bg-slate-900/40 p-3"
      style={{ height: h }}
    >
      {spec.kind === 'line' ? (
        <Line data={data} options={options} />
      ) : (
        <Bar data={data} options={options} />
      )}
    </div>
  )
}

function MiniTable({ rows, maxHeight = 260 }) {
  if (!isTableRows(rows)) return null
  const cols = Object.keys(rows[0]).slice(0, 6)
  return (
    <div
      className="mt-2 overflow-auto rounded-xl border border-slate-200/70 dark:border-slate-600/50 bg-white/70 dark:bg-slate-800/45"
      style={{ maxHeight }}
    >
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-white/90 dark:bg-slate-800/80 backdrop-blur">
          <tr className="border-b border-slate-200/70 dark:border-slate-600/50">
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 font-medium text-slate-700 dark:text-slate-300">
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
                'border-b border-slate-200/50 dark:border-slate-600/40 last:border-b-0',
                i % 2 === 0 ? 'bg-white/60 dark:bg-slate-800/35' : 'bg-slate-50/60 dark:bg-slate-900/25',
                'hover:bg-blue-50/50 dark:hover:bg-slate-700/35 transition-colors',
              )}
            >
              {cols.map((c) => (
                <td key={c} className="px-3 py-2 text-slate-800 dark:text-slate-200 whitespace-nowrap">
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

async function apiChat(baseUrl, question, sessionId, modelName, { periodPreset, period } = {}) {
  const actorName = (localStorage.getItem('sonasid_actor_name') || '').trim()
  const r = await fetch(`${baseUrl}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      question,
      session_id: sessionId,
      model_name: modelName,
      actor_name: actorName || undefined,
      period_preset: periodPreset || undefined,
      period: period && period.start && period.end ? { start: period.start, end: period.end } : undefined,
    }),
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
  const r = await fetch(`${baseUrl}/conversations/${encodeURIComponent(sessionId)}`, { method: 'DELETE', credentials: 'include' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
}

async function apiPostFeedback(baseUrl, body) {
  const r = await fetch(`${baseUrl}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  })
  const json = await r.json().catch(() => null)
  if (!r.ok || !json?.ok) {
    const msg = json?.error || json?.detail || `HTTP ${r.status}`
    throw new Error(msg)
  }
  return json
}

async function apiChatRetry(baseUrl, body) {
  const r = await fetch(`${baseUrl}/chat/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  })
  const json = await r.json().catch(() => null)
  if (!r.ok) {
    const msg = json?.detail || json?.message || json?.error || `HTTP ${r.status}`
    throw new Error(msg)
  }
  return json
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

/**
 * True si le message ne fait qu’indiquer une fenêtre temporelle (formes courtes, alignées sur le backend).
 */
function isPeriodOnlyFollowup(text) {
  const s = String(text ?? '').trim().toLowerCase()
  if (!s) return false
  if (/^\d{4}$/.test(s)) return true
  if (/^\d{4}-\d{2}$/.test(s)) return true
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return true
  if (/^(?:du|de)\s+\d{4}-\d{2}-\d{2}\s+(?:au|a|à)\s+\d{4}-\d{2}-\d{2}$/.test(s)) return true
  if (/^(?:en|pour|sur)\s+\d{4}(?:-\d{2}(?:-\d{2})?)?$/.test(s)) return true
  if (/^(7j|30j|ytd|mtd)$/.test(s)) return true
  if (
    /^(ce mois|mois courant|cette semaine|aujourd'hui|aujourd’hui|hier|année courante|annee courante)$/.test(
      s,
    )
  )
    return true
  return false
}

function isDimensionFollowup(text) {
  const s = String(text ?? '').trim().toLowerCase()
  if (!s) return false
  if (/^par\s+(mois|jour|journée|semaine|an|année)$/.test(s)) return true
  if (/^top\s*\d+$/.test(s)) return true
  return false
}

/**
 * Enchaînements courts : période seule après need_period, autre période / granularité après un KPI réussi.
 */
function mergeConversationFollowup(prevChat, rawInput) {
  const q = String(rawInput ?? '').trim()
  if (!q) return q

  let lastAssistantIdx = -1
  for (let i = prevChat.length - 1; i >= 0; i--) {
    if (prevChat[i].role === 'assistant') {
      lastAssistantIdx = i
      break
    }
  }
  if (lastAssistantIdx < 0) return q

  const raw = prevChat[lastAssistantIdx]?.meta?.raw

  let prevUser = ''
  for (let j = lastAssistantIdx - 1; j >= 0; j--) {
    if (prevChat[j].role === 'user') {
      prevUser = String(prevChat[j].content ?? '').trim()
      break
    }
  }
  if (!prevUser) return q

  if (raw?.source === 'pipeline:need_period' && isPeriodOnlyFollowup(q)) {
    return `${prevUser} ${q}`.trim()
  }

  const kpiOk =
    raw &&
    raw.source !== 'pipeline:need_period' &&
    !raw.error &&
    (Array.isArray(raw.result) ||
      typeof raw.result === 'number' ||
      typeof raw.TD_percent === 'number' ||
      typeof raw.TR_percent === 'number' ||
      typeof raw.Rendement_percent === 'number' ||
      typeof raw.MTBF_secondes === 'number' ||
      typeof raw.MTTR_secondes === 'number' ||
      typeof raw.Consommation_Totale === 'number' ||
      typeof raw.Consommation_MWh === 'number')

  if (!kpiOk) return q

  if (isPeriodOnlyFollowup(q)) {
    const ql = q.toLowerCase()
    if (/^\d{4}$/.test(ql)) {
      const years = prevUser.match(/\b20\d{2}\b/g)
      if (years && years.length === 1) return prevUser.replace(/\b20\d{2}\b/, q)
    }
    if (/^\d{4}-\d{2}$/.test(ql)) {
      if (/\b20\d{2}-\d{2}\b/.test(prevUser)) return prevUser.replace(/\b20\d{2}-\d{2}\b/, q)
    }
    return `${prevUser} ${q}`.trim()
  }

  if (isDimensionFollowup(q)) {
    if (prevUser.toLowerCase().includes(q.toLowerCase())) return prevUser
    return `${prevUser} ${q}`.trim()
  }

  return q
}

function isSuccessfulKpiResponse(raw) {
  if (!raw || typeof raw !== 'object' || raw.error) return false
  const src = String(raw.source || '')
  if (src.includes('need_period')) return false
  if (src.startsWith('conversational:')) return false
  if (typeof raw.message === 'string' && raw.message.trim() && raw.result === 1) return false
  if (raw.result === 1 && !raw.nombre_arrivages && !raw.tonnage_importe && !raw.tonnage_total) {
    return false
  }
  return (
    isCompareResponse(raw) ||
    Array.isArray(raw.result) ||
    typeof raw.result === 'number' ||
    typeof raw.TD_percent === 'number' ||
    typeof raw.TR_percent === 'number' ||
    typeof raw.Rendement_percent === 'number' ||
    typeof raw.MTBF_secondes === 'number' ||
    typeof raw.MTTR_secondes === 'number' ||
    typeof raw.Consommation_Totale === 'number' ||
    typeof raw.Consommation_MWh === 'number'
  )
}

function truncateTopicLabel(s, maxLen) {
  const t = String(s || '').trim().replace(/\s+/g, ' ')
  if (!t) return ''
  if (t.length <= maxLen) return t
  return `${t.slice(0, Math.max(0, maxLen - 1))}…`
}

/** Dernier enchaînement KPI utile (question affichée + canonique API). */
function computeLastKpiContext(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role !== 'assistant' || !m.meta?.raw) continue
    if (!isSuccessfulKpiResponse(m.meta.raw)) continue
    const userBubble = getPrecedingUserContent(messages, i).trim()
    const apiQ = String(m.meta.raw.question || '').trim()
    const label = truncateTopicLabel(apiQ || userBubble, 76)
    if (!label) continue
    return { label, canonical: apiQ || userBubble }
  }
  return null
}

function buildParMoisQuickQuestion(q, { periodPreset, period } = {}) {
  const t = String(q || '').trim()
  if (!t) return null
  if (/\bpar\s+mois\b/i.test(t)) return null
  const base = `${t} par mois`
  return periodPreset && periodPreset !== 'none' ? applyPeriodToQuestion(base, { ...period, force: true }) : base
}

function buildParJourQuickQuestion(q, { periodPreset, period } = {}) {
  const t = String(q || '').trim()
  if (!t) return null
  if (/\bpar\s+jour\b/i.test(t) || /\bpar\s+journée\b/i.test(t)) return null
  const base = `${t} par jour`
  return periodPreset && periodPreset !== 'none' ? applyPeriodToQuestion(base, { ...period, force: true }) : base
}

function buildParSemaineQuickQuestion(q, { periodPreset, period } = {}) {
  const t = String(q || '').trim()
  if (!t) return null
  if (/\bpar\s+semaine\b/i.test(t)) return null
  const base = `${t} par semaine`
  return periodPreset && periodPreset !== 'none' ? applyPeriodToQuestion(base, { ...period, force: true }) : base
}

/** Une seule année 20xx dans la phrase → année ± 1. */
function buildYearShiftQuestion(q, delta) {
  const t = String(q || '').trim()
  const years = t.match(/\b(20\d{2})\b/g)
  if (!years || years.length !== 1) return null
  const y = parseInt(years[0], 10)
  const next = y + delta
  if (next < 1990 || next > 2100) return null
  if (delta > 0 && next > new Date().getFullYear() + 1) return null
  return t.replace(/\b20\d{2}\b/, String(next))
}

const KPI_ANALYSE_MARKER = '[Analyse KPI]'

function compactKpiRawForAnalysis(raw) {
  if (!raw || typeof raw !== 'object') return '{}'
  const out = {}
  if (raw.question) out.question = raw.question
  if (raw.source) out.source = raw.source
  if (raw.metric) out.metric = raw.metric
  if (raw.period_a && typeof raw.period_a === 'object') {
    out.period_a = {
      range: raw.period_a.range,
      value: raw.period_a.value,
    }
  }
  if (raw.period_b && typeof raw.period_b === 'object') {
    out.period_b = {
      range: raw.period_b.range,
      value: raw.period_b.value,
    }
  }
  if (typeof raw.delta === 'number') out.delta = raw.delta
  if (typeof raw.delta_percent === 'number') out.delta_percent = raw.delta_percent
  if (Array.isArray(raw.result)) {
    const rows = raw.result
    const max = 28
    if (rows.length <= max) {
      out.result = rows
    } else {
      out.result = [
        ...rows.slice(0, 14),
        { _note: `… ${rows.length - 28} lignes omises …` },
        ...rows.slice(-14),
      ]
    }
    out._rows_total = rows.length
  } else if (raw.result != null) {
    out.result = raw.result
  }
  for (const k of [
    'TD_percent',
    'TR_percent',
    'Rendement_percent',
    'MTBF_secondes',
    'MTTR_secondes',
    'Consommation_Totale',
    'Consommation_MWh',
  ]) {
    if (typeof raw[k] === 'number') out[k] = raw[k]
  }
  let s = JSON.stringify(out)
  const maxLen = 10000
  if (s.length > maxLen) s = `${s.slice(0, maxLen - 24)}…[tronqué]`
  return s
}

/** Demande d’interprétation LLM des chiffres déjà affichés (préfixe reconnu côté API). */
function buildAnalyzeKpiQuery(canonicalQ, raw) {
  const payload = compactKpiRawForAnalysis(raw)
  if (!payload || payload === '{}') return ''
  const ref = String(canonicalQ || '').trim()
  const lines = [
    KPI_ANALYSE_MARKER,
    ref ? `Référence (ne pas relancer de requête SQL) : ${ref}` : '',
    'Données JSON :',
    payload,
    '',
    'Tâche : analyse courte en français (tendances, évolution temporelle si série, valeurs marquantes, limites éventuelles des données).',
  ]
  return lines.filter(Boolean).join('\n')
}

function isAnalyseKpiPayload(text) {
  return String(text || '').trimStart().startsWith(KPI_ANALYSE_MARKER)
}

/** Libellés et requêtes pour les boutons sous une bulle KPI. */
function collectKpiQuickActions(canonicalQ, { periodPreset, period } = {}) {
  const q = String(canonicalQ || '').trim()
  if (!q) return []
  const out = []
  const prev = buildYearShiftQuestion(q, -1)
  if (prev) out.push({ id: 'y-1', label: 'Année −1', query: prev })
  const next = buildYearShiftQuestion(q, 1)
  if (next) out.push({ id: 'y+1', label: 'Année +1', query: next })
  const pm = buildParMoisQuickQuestion(q, { periodPreset, period })
  if (pm) out.push({ id: 'mois', label: 'Par mois', query: pm })
  const ps = buildParSemaineQuickQuestion(q, { periodPreset, period })
  if (ps) out.push({ id: 'semaine', label: 'Par semaine', query: ps })
  const pj = buildParJourQuickQuestion(q, { periodPreset, period })
  if (pj) out.push({ id: 'jour', label: 'Par jour', query: pj })
  out.push({ id: 'repeat', label: 'Répéter', query: q })
  return out
}

/** Reconstruit la question envoyée à l’API (grade / topN / période), comme dans Envoyer. */
function buildEffectiveApiQuestion(rawText, { grade, topN, periodPreset, period }) {
  const q2 = applyVarsToQuestion((rawText || '').trim(), {
    grade: (grade || '').trim(),
    topN: String(topN || '').trim(),
  })
  // Apply the selected period only for KPI-like questions; never for general chat.
  return periodPreset === 'none' || !looksLikeKpiQuestion(q2) ? q2 : applyPeriodToQuestion(q2, { ...period, force: false })
}

function looksLikeKpiQuestion(text) {
  const t = String(text || '').toLowerCase()
  if (!t.trim()) return false
  const keywords = [
    'kpi',
    'navire',
    'navires',
    'arrivage',
    'arrivages',
    'tonnage',
    'port',
    'booking',
    'accostage',
    'dechargement',
    'déchargement',
    'decharg',
    'fournisseur',
    'qualité',
    'qualite',
    'transfert',
    'transféré',
    'transfere',
    'commande',
  ]
  if (keywords.some((k) => t.includes(k))) return true
  if (t.includes('par mois') || t.includes('par semaine') || t.includes('par jour') || t.includes('top ')) return true
  return false
}

function buildWelcomeText(actorName) {
  return buildSonasidWelcomeText(actorName)
}

export default function ChatWorkspace() {
  const baseUrl = kpiApiBase()
  const [sessionId, setSessionId] = useState(() => getOrCreateCurrentSessionId())
  const [modelName, setModelName] = useState(() => getOrCreateModelForSession(sessionId))
  const [history, setHistory] = useState([])
  const [historyBusy, setHistoryBusy] = useState(false)

  const [chatInput, setChatInput] = useState('')
  const [sttSupported, setSttSupported] = useState(false)
  const [sttListening, setSttListening] = useState(false)
  const [sttErr, setSttErr] = useState('')
  const [chat, setChat] = useState(() => [])
  const [busy, setBusy] = useState(false)
  const [grade] = useState('')
  const [topN] = useState('5')
  const clientMode = true // livraison: UI 100% "client" (pas de mode debug)
  const [periodPreset, setPeriodPreset] = useState('none') // none | 7d | 30d | mtd | ytd | custom
  const [customStart, setCustomStart] = useState(() => addDaysIso(toIsoDate(new Date()), -29))
  const [customEnd, setCustomEnd] = useState(() => toIsoDate(new Date()))
  const [convSearch, setConvSearch] = useState('')
  const [yearPick, setYearPick] = useState('') // optional: e.g. "2025"
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('sonasid_theme')
    return saved === 'dark' ? 'dark' : 'light'
  })

  useLayoutEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') root.classList.add('dark')
    else root.classList.remove('dark')
  }, [theme])

  const [workspaceVisible, setWorkspaceVisible] = useState(() => {
    const v = localStorage.getItem('sonasid_workspace_open')
    return v !== '0'
  })
  function setWorkspaceOpen(open) {
    setWorkspaceVisible(open)
    localStorage.setItem('sonasid_workspace_open', open ? '1' : '0')
  }

  const [expandedRowsByMsg, setExpandedRowsByMsg] = useState(() => ({}))
  const [feedbackVote, setFeedbackVote] = useState({})
  const [feedbackStatus, setFeedbackStatus] = useState({})
  // Copy feedback for SQL blocks (keyed by `${msgIdx}:${label}`)
  const [copiedSqlByKey, setCopiedSqlByKey] = useState({})
  const [copiedMsgByIdx, setCopiedMsgByIdx] = useState({})
  const [editingUserIdx, setEditingUserIdx] = useState(null)
  const [editingDraft, setEditingDraft] = useState('')
  const [actorName, setActorName] = useState(() => (localStorage.getItem('sonasid_actor_name') || '').trim())
  const [authUser, setAuthUser] = useState(null) // {display_name,email,sub,...}
  const [accountInfo, setAccountInfo] = useState(null) // {allowed_years:[...], user:{...}}
  const [accountOpen, setAccountOpen] = useState(false)
  const accountRef = useRef(null)
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false)
  const [profileDraft, setProfileDraft] = useState({ phone: '', personal_email: '' })
  const [pwDraft, setPwDraft] = useState({ current: '', next: '' })
  const [accountBusy, setAccountBusy] = useState(false)
  const [accountErr, setAccountErr] = useState('')
  const [accountOk, setAccountOk] = useState('')
  // Ask for operator name on each app entry (prefilled if already known).
  const [actorModalOpen, setActorModalOpen] = useState(false)
  const [actorDraft, setActorDraft] = useState(() => (localStorage.getItem('sonasid_actor_name') || '').trim())
  const [actorRemember, setActorRemember] = useState(true)
  const actorInputRef = useRef(null)
  const chatScrollRef = useRef(null)
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true)
  const chatEndRef = useRef(null)
  const sttRef = useRef(null)
  const sttBaseRef = useRef('')
  const sttCooldownUntilRef = useRef(0)
  const modelPickerRef = useRef(null)
  const [modelPickerOpen, setModelPickerOpen] = useState(false)

  const isWelcomeOnly = Array.isArray(chat) && chat.length === 0
  function scrollToEnd({ behavior = 'auto' } = {}) {
    const el = chatScrollRef.current
    if (!el) return
    // Use scrollTop instead of scrollIntoView to avoid overscrolling glitches.
    try {
      el.scrollTo({ top: el.scrollHeight, behavior })
    } catch {
      el.scrollTop = el.scrollHeight
    }
  }

  useEffect(() => {
    if (!modelPickerOpen) return
    const onDoc = (e) => {
      if (modelPickerRef.current?.contains(e.target)) return
      setModelPickerOpen(false)
    }
    const onKey = (e) => {
      if (e.key === 'Escape') setModelPickerOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [modelPickerOpen])

  useEffect(() => {
    if (!accountOpen) return
    const onDoc = (e) => {
      if (accountRef.current?.contains?.(e.target)) return
      setAccountOpen(false)
    }
    const onKey = (e) => {
      if (e.key === 'Escape') setAccountOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [accountOpen])

  useEffect(() => {
    // If user is authenticated, force actorName from session and lock badge editing.
    ;(async () => {
      try {
        const r = await fetch(`${baseUrl}/auth/me`, { credentials: 'include' })
        const j = await r.json().catch(() => null)
        if (j?.authenticated && j?.user) {
          setAuthUser(j.user)
          const dn = String(j.user.display_name || j.user.email || '').trim()
          if (dn) {
            setActorName(dn)
            setActorDraft(dn)
            localStorage.setItem('sonasid_actor_name', dn)
            localStorage.setItem('sonasid_actor_locked', '1')
            setActorModalOpen(false)
          }
          try {
            const r2 = await fetch(`${baseUrl}/auth/account`, { credentials: 'include' })
            const j2 = await r2.json().catch(() => null)
            if (j2?.authenticated) setAccountInfo(j2)
          } catch {
            // ignore
          }
        } else {
          setAuthUser(null)
          setAccountInfo(null)
          localStorage.removeItem('sonasid_actor_locked')
        }
      } catch {
        // ignore
      }
    })()
  }, [baseUrl])

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    setSttSupported(Boolean(SR))
    return () => {
      try {
        sttRef.current?.stop?.()
      } catch {
        /* noop */
      }
      sttRef.current = null
    }
  }, [])

  function stopStt() {
    sttCooldownUntilRef.current = Date.now() + 350
    try {
      // `abort()` is more reliable than `stop()` when restarting quickly.
      sttRef.current?.abort?.()
    } catch {
      /* noop */
    }
    try {
      sttRef.current?.stop?.()
    } catch {
      /* noop */
    }
    sttRef.current = null
    setSttListening(false)
  }

  function startStt() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) {
      setSttErr('Speech-to-text non supporté sur ce navigateur.')
      return
    }
    if (busy) return
    // Avoid the "InvalidStateError" that often happens right after stop().
    const cd = sttCooldownUntilRef.current || 0
    if (Date.now() < cd) {
      setTimeout(() => startStt(), Math.max(0, cd - Date.now()))
      return
    }
    // If a previous instance still exists, hard-stop it first.
    if (sttRef.current) stopStt()
    setSttErr('')

    const rec = new SR()
    rec.lang = 'fr-FR'
    rec.continuous = true
    rec.interimResults = true
    sttBaseRef.current = String(chatInput || '')

    rec.onstart = () => setSttListening(true)
    rec.onerror = (e) => {
      const code = String(e?.error || '')
      if (code === 'not-allowed' || code === 'service-not-allowed') setSttErr('Autorisation micro refusée.')
      else if (code === 'no-speech') setSttErr('Aucune voix détectée.')
      else setSttErr(code ? `Erreur micro: ${code}` : 'Erreur micro.')
      stopStt()
    }
    rec.onend = () => {
      setSttListening(false)
      sttRef.current = null
    }
    rec.onresult = (ev) => {
      let interim = ''
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i]
        const t = String(r?.[0]?.transcript || '')
        if (!t) continue
        if (r.isFinal) {
          const cur = `${sttBaseRef.current}`.trim()
          const add = t.trim()
          const next = (cur ? `${cur} ${add}` : add).replace(/\s+/g, ' ').trim()
          sttBaseRef.current = next
          setChatInput(next)
        } else {
          interim += t
        }
      }
      if (interim) {
        const cur = `${sttBaseRef.current}`.trim()
        const add = interim.trim()
        const next = (cur ? `${cur} ${add}` : add).replace(/\s+/g, ' ').trim()
        setChatInput(next)
      }
    }

    sttRef.current = rec
    try {
      rec.start()
    } catch (e) {
      const msg = String(e?.name || e?.message || '')
      setSttErr(msg ? `Impossible de démarrer le micro (${msg}).` : 'Impossible de démarrer le micro.')
      stopStt()
    }
  }

  useEffect(() => {
    if (!accountSettingsOpen) return
    setAccountErr('')
    setAccountOk('')
    ;(async () => {
      try {
        const j = await apiJson(`${baseUrl}/auth/profile`)
        const p = j?.profile || {}
        setProfileDraft({ phone: String(p.phone || ''), personal_email: String(p.personal_email || '') })
      } catch (e) {
        setAccountErr(e?.message || String(e || 'Erreur'))
      }
    })()
  }, [accountSettingsOpen, baseUrl])

  useEffect(() => {
    if (!actorModalOpen) return
    const t = setTimeout(() => actorInputRef.current?.focus?.(), 50)
    const onKey = (e) => {
      if (e.key === 'Escape') {
        // allow closing, but keep badge editable via workspace
        setActorModalOpen(false)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(t)
      document.removeEventListener('keydown', onKey)
    }
  }, [actorModalOpen])

  useEffect(() => {
    // Open once on initial entry to prompt operator identification.
    const locked = localStorage.getItem('sonasid_actor_locked') === '1'
    if (locked) return
    const t = setTimeout(() => setActorModalOpen(true), 250)
    return () => clearTimeout(t)
  }, [])

  function _loadRecentActors() {
    try {
      const raw = localStorage.getItem('sonasid_actor_recent') || '[]'
      const arr = JSON.parse(raw)
      return Array.isArray(arr) ? arr.filter((x) => typeof x === 'string').slice(0, 8) : []
    } catch {
      return []
    }
  }

  function _saveActor(next) {
    const v = String(next || '').trim()
    setActorName(v)
    setActorDraft(v)
    if (actorRemember) {
      localStorage.setItem('sonasid_actor_name', v)
      // keep a small MRU list
      const recent = [v, ..._loadRecentActors().filter((x) => x !== v)].filter(Boolean).slice(0, 8)
      localStorage.setItem('sonasid_actor_recent', JSON.stringify(recent))
    }
  }

  function _isValidActor(v) {
    const s = String(v || '').trim()
    // Accept typical badge formats: OP12, ChefQuartA, Q1-OP_7, etc.
    return s.length >= 2 && s.length <= 32 && /^[a-zA-Z0-9 _.-]+$/.test(s)
  }

  function onChatScroll() {
    const el = chatScrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setShouldAutoScroll(distanceFromBottom < 80)
  }

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

  const lastKpiContext = useMemo(() => computeLastKpiContext(chat), [chat])

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

  useEffect(() => {
    localStorage.setItem('sonasid_current_session_id', sessionId)
    const m = getOrCreateModelForSession(sessionId)
    setModelName(m)
    setChat([])
    let cancelled = false
    ;(async () => {
      setHistoryBusy(true)
      try {
        const convs = await apiListConversations(baseUrl)
        if (!cancelled) setHistory(convs)
        const msgs = await apiGetHistory(baseUrl, sessionId)
        if (cancelled) return
        setFeedbackVote({})
        setFeedbackStatus({})
        setCopiedSqlByKey({})
        const mapped = mapHistoryToChat(msgs, { clientMode })
        if (mapped.length) {
          setChat(mapped)
          setShouldAutoScroll(true)
          requestAnimationFrame(() => requestAnimationFrame(() => scrollToEnd({ behavior: 'auto' })))
        } else {
          setChat([])
        }
      } catch {
        if (!cancelled) setChat([])
      } finally {
        if (!cancelled) setHistoryBusy(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [baseUrl, sessionId, clientMode])

  function loadConversation(sid) {
    if (!sid) return
    if (sid !== sessionId) {
      setSessionId(sid)
      return
    }
    ;(async () => {
      try {
        const msgs = await apiGetHistory(baseUrl, sid)
        setFeedbackVote({})
        setFeedbackStatus({})
        setCopiedSqlByKey({})
        const mapped = mapHistoryToChat(msgs, { clientMode })
        setChat(mapped.length ? mapped : [])
        if (mapped.length) {
          setShouldAutoScroll(true)
          requestAnimationFrame(() => requestAnimationFrame(() => scrollToEnd({ behavior: 'auto' })))
        }
      } catch {
        setChat([{ role: 'assistant', content: 'Impossible de charger l’historique.', created_at: Date.now() / 1000 }])
      }
    })()
  }

  async function createNewConversation() {
    setFeedbackVote({})
    setFeedbackStatus({})
    setCopiedSqlByKey({})
    const sid = newSessionId()
    setSessionId(sid)
    setChat([])
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

  async function submitFeedback(messageIndex, rating, userQuestion, assistantContent) {
    if (feedbackVote[messageIndex] === rating) return
    try {
      await apiPostFeedback(baseUrl, {
        session_id: sessionId,
        rating,
        user_question: userQuestion,
        assistant_content: assistantContent,
        model_name: modelName,
      })
      setFeedbackVote((prev) => ({ ...prev, [messageIndex]: rating }))
      setFeedbackStatus((prev) => ({ ...prev, [messageIndex]: 'ok' }))
    } catch {
      setFeedbackStatus((prev) => ({ ...prev, [messageIndex]: 'err' }))
    }
  }

  async function submitAutoCorrection(prevUser, assistantText) {
    if (busy) return
    const q3 = buildEffectiveApiQuestion(prevUser, { grade, topN, periodPreset, period })
    setBusy(true)
    try {
      let res = await apiChatRetry(baseUrl, {
        session_id: sessionId,
        model_name: modelName,
        user_question: q3,
        assistant_content: assistantText,
      })
      if (res?.error) {
        const msg = res.message || res.error
        setChat((prev) => [
          ...prev,
          { role: 'assistant', content: `Auto-correction : ${msg}` },
        ])
        if (shouldAutoScroll) requestAnimationFrame(() => scrollToEnd({ behavior: 'smooth' }))
        return
      }

      const content = formatChatContent(res, { clientMode })
      if (res.notice && !content.includes(String(res.notice).slice(0, 20))) {
        // notice already in formatAssistantCompact when sole field
      }

      setChat((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.notice && !content.includes(String(res.notice).slice(0, 20))
            ? `${content}\n\n${res.notice}`
            : content,
          meta: { raw: res },
          created_at: Date.now() / 1000,
        },
      ])
      scheduleChartAugment(res, q3, { baseUrl, sessionId, modelName, periodPreset, period, clientMode }, setChat)
      apiListConversations(baseUrl).then(setHistory).catch(() => null)
      if (shouldAutoScroll) requestAnimationFrame(() => scrollToEnd({ behavior: 'smooth' }))
    } catch (e) {
      setChat((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Erreur API /chat/retry: ${e?.message || String(e)}`,
          created_at: Date.now() / 1000,
        },
      ])
      if (shouldAutoScroll) requestAnimationFrame(() => scrollToEnd({ behavior: 'smooth' }))
    } finally {
      setBusy(false)
    }
  }

  async function regenerateFromEditedUser(idx) {
    if (busy) return
    if (typeof idx !== 'number' || idx < 0 || idx >= chat.length) return
    const cur = chat[idx]
    if (!cur || cur.role !== 'user') return
    const draft = String(editingDraft || '').trim()
    if (!draft) return

    // Update the user message + remove the immediate next assistant (if any)
    setChat((prev) => {
      const next = [...prev]
      const u = next[idx]
      next[idx] = { ...u, content: draft }
      if (next[idx + 1]?.role === 'assistant') next.splice(idx + 1, 1)
      return next
    })
    setEditingUserIdx(null)
    setEditingDraft('')

    setBusy(true)
    try {
      const q3 = buildEffectiveApiQuestion(draft, { grade, topN, periodPreset, period })
      let res = await apiChat(baseUrl, q3, sessionId, modelName, { periodPreset, period })

      const content = formatChatContent(res, { clientMode })

      setChat((prev) => {
        const next = [...prev]
        const insertAt = Math.min(idx + 1, next.length)
        next.splice(insertAt, 0, {
          role: 'assistant',
          content,
          meta: { raw: res },
          created_at: Date.now() / 1000,
        })
        return next
      })
      scheduleChartAugment(res, q3, { baseUrl, sessionId, modelName, periodPreset, period, clientMode }, setChat)
      apiListConversations(baseUrl).then(setHistory).catch(() => null)
      requestAnimationFrame(() => scrollToEnd({ behavior: 'smooth' }))
    } catch (e) {
      setChat((prev) => [
        ...prev,
        { role: 'assistant', content: `Erreur API /chat: ${e?.message || String(e)}`, created_at: Date.now() / 1000 },
      ])
      requestAnimationFrame(() => scrollToEnd({ behavior: 'smooth' }))
    } finally {
      setBusy(false)
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
    setChat((prev) => [...prev, { role: 'user', content: display || q, created_at: Date.now() / 1000 }])

    try {
      const analyseMode = isAnalyseKpiPayload(q)
      const qBase = analyseMode ? q : mergeConversationFollowup(chat, q)
      const q2 = applyVarsToQuestion(qBase, { grade: grade.trim(), topN: String(topN || '').trim() })
      // Apply the selected period only for KPI-like questions.
      const q3 =
        analyseMode || periodPreset === 'none' || !looksLikeKpiQuestion(q2)
          ? q2
          : applyPeriodToQuestion(q2, { ...period, force: false })
      let res = await apiChat(baseUrl, q3, sessionId, modelName, { periodPreset, period })

      const content = formatChatContent(res, { clientMode })

      setChat((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.notice && !content.includes(String(res.notice).slice(0, 20))
            ? `${content}\n\n${res.notice}`
            : content,
          meta: { raw: res },
        },
      ])
      scheduleChartAugment(res, q3, { baseUrl, sessionId, modelName, periodPreset, period, clientMode }, setChat)
      // refresh sidebar titles/order
      apiListConversations(baseUrl).then(setHistory).catch(() => null)
      if (shouldAutoScroll) requestAnimationFrame(() => scrollToEnd({ behavior: 'smooth' }))
    } catch (e) {
      setChat((prev) => [
        ...prev,
        { role: 'assistant', content: `Erreur API /chat: ${e?.message || String(e)}` },
      ])
      // best-effort timestamp for error bubbles
      setChat((prev) => {
        const last = prev[prev.length - 1]
        if (last && last.role === 'assistant' && last.created_at == null) {
          const next = [...prev]
          next[next.length - 1] = { ...last, created_at: Date.now() / 1000 }
          return next
        }
        return prev
      })
      if (shouldAutoScroll) requestAnimationFrame(() => scrollToEnd({ behavior: 'smooth' }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app-bg flex h-[100dvh] flex-col overflow-hidden">
      <div className="blob b1" />
      <div className="blob b2" />
      <div className="blob b3" />
      <div className="noise" />
      <SteelPlantBackground />
      <div
        className={clsx(
          'relative mx-auto flex w-full flex-1 min-h-0 flex-col px-2 py-3 transition-[max-width] duration-300 ease-out sm:px-3 sm:py-4',
          workspaceVisible ? 'max-w-7xl' : 'max-w-4xl lg:max-w-5xl',
        )}
      >
        {actorModalOpen ? (
          <div className="fixed right-4 top-4 z-50 w-[min(420px,calc(100vw-2rem))]">
            <div className="rounded-2xl border border-slate-200/70 bg-white/90 shadow-xl backdrop-blur dark:border-slate-700/50 dark:bg-slate-900/80">
              <div className="flex items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">Qui utilise l’assistant ?</div>
                  <div className="mt-0.5 text-xs text-slate-600 dark:text-slate-300">
                    Renseigne ton nom / badge (ex: <span className="font-mono">Nassima</span>, <span className="font-mono">OP12</span>).
                  </div>
                </div>
                <button
                  type="button"
                  className="shrink-0 rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100/70 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200 transition"
                  onClick={() => setActorModalOpen(false)}
                  title="Fermer"
                  aria-label="Fermer"
                >
                  ✕
                </button>
              </div>

              <div className="px-4 pb-4">
                <div className="mt-1">
                  <input
                    ref={actorInputRef}
                    value={actorDraft}
                    onChange={(e) => setActorDraft(e.target.value)}
                    placeholder="Ton nom / badge"
                    className={clsx(
                      'w-full rounded-xl px-3 py-2.5 text-sm',
                      'bg-white/70 dark:bg-slate-800/40 text-slate-900 dark:text-slate-100 placeholder:text-slate-400',
                      'border border-slate-200/80 dark:border-slate-700/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20',
                    )}
                    inputMode="text"
                    aria-label="Nom / badge opérateur"
                  />
                </div>

                {_loadRecentActors().length ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {_loadRecentActors().slice(0, 5).map((a) => (
                      <button
                        key={a}
                        type="button"
                        className="rounded-full border border-slate-200/70 dark:border-slate-700/50 bg-white/70 dark:bg-slate-800/30 px-3 py-1 text-xs text-slate-700 dark:text-slate-200 hover:bg-white/90 dark:hover:bg-slate-800/50 transition"
                        onClick={() => setActorDraft(a)}
                        title="Utiliser"
                      >
                        {a}
                      </button>
                    ))}
                  </div>
                ) : null}

                <div className="mt-3 flex items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                    <input
                      type="checkbox"
                      checked={actorRemember}
                      onChange={(e) => setActorRemember(e.target.checked)}
                    />
                    Mémoriser
                  </label>

                  <div className="flex items-center gap-2">
                    <button type="button" className="btn-ghost text-xs" onClick={() => setActorModalOpen(false)}>
                      Plus tard
                    </button>
                    <button
                      type="button"
                      className={clsx('btn-primary text-xs', !_isValidActor(actorDraft) && 'opacity-60 pointer-events-none')}
                      onClick={() => {
                        if (!_isValidActor(actorDraft)) return
                        _saveActor(actorDraft)
                        setActorModalOpen(false)
                      }}
                    >
                      Enregistrer
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        <header className="shrink-0 relative flex">
          <div className="absolute right-0 top-0 flex items-center gap-2">
          <button
            type="button"
            className={clsx(
              'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium',
              'border-slate-200/70 bg-white/70 text-slate-700 hover:bg-white/90',
              'dark:border-slate-600/50 dark:bg-slate-900/40 dark:text-slate-200 dark:hover:bg-slate-800/55',
              'transition-colors',
            )}
            onClick={() => {
              const locked = localStorage.getItem('sonasid_actor_locked') === '1'
              if (!locked) setActorModalOpen(true)
            }}
            title={localStorage.getItem('sonasid_actor_locked') === '1' ? 'Compte connecté' : 'Modifier l’opérateur'}
          >
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500/80" />
            <span className="font-mono">{actorName || 'Opérateur'}</span>
            {localStorage.getItem('sonasid_actor_locked') === '1' ? (
              <span className="text-slate-500 dark:text-slate-400">Connecté</span>
            ) : (
              <span className="text-slate-500 dark:text-slate-400">Modifier</span>
            )}
          </button>
          <div className="relative" ref={accountRef}>
            <button
              type="button"
              className={clsx(
                'inline-flex items-center justify-center rounded-full border px-3 py-1.5 text-xs font-semibold',
                'border-slate-200/70 bg-white/70 text-slate-700 hover:bg-white/90',
                'dark:border-slate-600/50 dark:bg-slate-900/40 dark:text-slate-200 dark:hover:bg-slate-800/55',
                'transition-colors',
              )}
              onClick={() => setAccountOpen((v) => !v)}
              title="Paramètres"
            >
              <IconGear className="text-slate-700 dark:text-slate-200" />
            </button>
            {accountOpen ? (
              <div
                className={clsx(
                  'absolute right-0 mt-2 w-[320px] max-w-[86vw] rounded-2xl border p-3 shadow-2xl z-50',
                  'border-slate-200/70 bg-white/90 backdrop-blur',
                  'dark:border-slate-600/50 dark:bg-slate-900/70',
                )}
              >
                <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">Mon compte</div>
                <div className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {authUser ? String(authUser.display_name || authUser.email || '—') : 'Non connecté'}
                </div>
                {authUser?.email ? (
                  <div className="mt-0.5 truncate text-xs text-slate-600 dark:text-slate-300">{String(authUser.email)}</div>
                ) : null}
                {authUser ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                    <span className="rounded-full border border-slate-200/70 bg-white/70 px-2 py-0.5 text-slate-700 dark:border-slate-600/50 dark:bg-slate-900/30 dark:text-slate-200">
                      {String(authUser.auth_provider || 'session')}
                    </span>
                    {Array.isArray(accountInfo?.allowed_years) && accountInfo.allowed_years.length ? (
                      <span className="rounded-full border border-amber-200/70 bg-amber-50/70 px-2 py-0.5 text-amber-800 dark:border-amber-400/25 dark:bg-amber-500/10 dark:text-amber-200">
                        Accès: {accountInfo.allowed_years.join(', ')}
                      </span>
                    ) : (
                      <span className="rounded-full border border-slate-200/70 bg-white/70 px-2 py-0.5 text-slate-700 dark:border-slate-600/50 dark:bg-slate-900/30 dark:text-slate-200">
                        Accès: —
                      </span>
                    )}
                  </div>
                ) : null}
                <div className="mt-3 flex items-center justify-end gap-2">
                  <button type="button" className="btn-ghost text-xs" onClick={() => setAccountOpen(false)}>
                    Fermer
                  </button>
                  {authUser ? (
                    <button
                      type="button"
                      className={clsx(
                        'inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold',
                        'border border-slate-200/70 bg-white/70 text-slate-700 hover:bg-white/90',
                        'dark:border-slate-600/50 dark:bg-slate-900/30 dark:text-slate-200 dark:hover:bg-slate-800/50',
                        'transition',
                      )}
                      onClick={() => {
                        setAccountOpen(false)
                        setAccountSettingsOpen(true)
                      }}
                      title="Gérer mon compte"
                    >
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-orange-500/80" />
                      Gérer mon compte
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="btn-primary text-xs"
                    onClick={async () => {
                      const baseUrl = (import.meta.env.VITE_API_BASE || `http://${window.location.hostname || 'localhost'}:8001`).replace(/\/$/, '')
                      try {
                        await fetch(`${baseUrl}/auth/logout`, { method: 'POST', credentials: 'include' })
                      } finally {
                        window.location.reload()
                      }
                    }}
                    title="Se déconnecter"
                  >
                    Se déconnecter
                  </button>
                </div>
              </div>
            ) : null}
          </div>
          </div>
          <div className="w-full mx-auto text-center">
            <div className="text-xs font-medium tracking-wide text-slate-500 dark:text-slate-300">Sonasid</div>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100 sm:text-3xl">
              AI Assistant
            </h1>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{SONASID_TAGLINE}</p>

            <div className={clsx('mt-3 flex flex-wrap items-center justify-center gap-2 text-xs')}>
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
              <span
                className={clsx(
                  'chip inline-flex items-center gap-1.5 font-medium',
                  theme === 'dark'
                    ? 'border-indigo-400/35 bg-indigo-500/15 text-indigo-100'
                    : 'border-slate-300/80 bg-slate-100/90 text-slate-800',
                )}
                title={theme === 'dark' ? 'Interface en mode sombre' : 'Interface en mode clair'}
              >
                {theme === 'dark' ? (
                  <>
                    <IconMoon className="shrink-0 text-indigo-200" />
                    Mode sombre
                  </>
                ) : (
                  <>
                    <IconSun className="shrink-0 text-amber-600" />
                    Mode clair
                  </>
                )}
              </span>
            </div>
          </div>
          <div className="hidden md:flex absolute left-0 top-0 items-center">
            <SonasidBrandLogo compact />
          </div>
        </header>

        {accountSettingsOpen ? (
          <div className="fixed inset-0 z-[60] flex items-center justify-center px-4">
            <div
              className="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px]"
              onClick={() => setAccountSettingsOpen(false)}
            />
            <div className="relative w-full max-w-2xl panel p-5 sm:p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">Paramètres du compte</div>
                  <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                    Informations personnelles et sécurité.
                  </div>
                </div>
                <button type="button" className="btn-ghost text-xs" onClick={() => setAccountSettingsOpen(false)}>
                  Fermer
                </button>
            </div>

              {accountErr ? (
                <div className="mt-4 rounded-xl border border-rose-200/70 bg-rose-50/70 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/25 dark:text-rose-200 whitespace-pre-wrap">
                  {accountErr}
                </div>
              ) : null}
              {accountOk ? (
                <div className="mt-4 rounded-xl border border-emerald-200/70 bg-emerald-50/70 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/25 dark:text-emerald-200 whitespace-pre-wrap">
                  {accountOk}
                </div>
              ) : null}

              <div className="mt-5 grid gap-5">
                <div className="rounded-2xl border border-slate-200/70 bg-white/55 p-4 dark:border-slate-700/55 dark:bg-slate-900/20">
                  <div className="text-xs font-semibold text-slate-900 dark:text-slate-100">Profil</div>
                  <div className="mt-3 grid sm:grid-cols-2 gap-3">
                    <label className="block">
                      <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">Téléphone</div>
                      <input
                        value={profileDraft.phone}
                        onChange={(e) => setProfileDraft((p) => ({ ...p, phone: e.target.value }))}
                        className="mt-1 w-full rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-orange-500/25 dark:border-slate-600/50 dark:bg-slate-900/30 dark:text-slate-100"
                        placeholder="Ex: +212 6 00 00 00 00"
                      />
                    </label>
                    <label className="block sm:col-span-2">
                      <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">Email personnel</div>
                      <input
                        value={profileDraft.personal_email}
                        onChange={(e) => setProfileDraft((p) => ({ ...p, personal_email: e.target.value }))}
                        className="mt-1 w-full rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-orange-500/25 dark:border-slate-600/50 dark:bg-slate-900/30 dark:text-slate-100"
                        placeholder="ex: prenom.nom@gmail.com"
                      />
                    </label>
                  </div>
                  <div className="mt-4 flex justify-end gap-2">
                    <button
                      type="button"
                      className={clsx(
                        'rounded-xl px-4 py-2 text-xs font-semibold text-white',
                        'bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500',
                        'shadow-[0_12px_28px_-18px_rgba(249,115,22,0.85)]',
                        'hover:from-amber-400 hover:via-orange-400 hover:to-rose-400',
                        'active:scale-[0.99] transition',
                        'focus:outline-none focus:ring-2 focus:ring-orange-500/25',
                        accountBusy && 'opacity-70 pointer-events-none',
                      )}
                      onClick={async () => {
                        setAccountBusy(true)
                        setAccountErr('')
                        setAccountOk('')
                        try {
                          await apiJson(`${baseUrl}/auth/profile`, {
                            method: 'POST',
                            body: JSON.stringify({ phone: profileDraft.phone, personal_email: profileDraft.personal_email }),
                          })
                          setAccountOk('Profil enregistré.')
                        } catch (e) {
                          setAccountErr(e?.message || String(e || 'Erreur'))
                        } finally {
                          setAccountBusy(false)
                        }
                      }}
                    >
                      Enregistrer
                    </button>
                  </div>
                </div>

                {authUser?.auth_provider === 'local_excel' ? (
                  <div className="rounded-2xl border border-slate-200/70 bg-white/55 p-4 dark:border-slate-700/55 dark:bg-slate-900/20">
                    <div className="text-xs font-semibold text-slate-900 dark:text-slate-100">Sécurité</div>
                    <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                      Modifier ton code de connexion.
                    </div>
                    <div className="mt-3 grid sm:grid-cols-2 gap-3">
                      <label className="block">
                        <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">Code actuel</div>
                        <input
                          type="password"
                          value={pwDraft.current}
                          onChange={(e) => setPwDraft((p) => ({ ...p, current: e.target.value }))}
                          className="mt-1 w-full rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-orange-500/25 dark:border-slate-600/50 dark:bg-slate-900/30 dark:text-slate-100"
                        />
                      </label>
                      <label className="block">
                        <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">Nouveau code</div>
                        <input
                          type="password"
                          value={pwDraft.next}
                          onChange={(e) => setPwDraft((p) => ({ ...p, next: e.target.value }))}
                          className="mt-1 w-full rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-sm text-slate-900 outline-none focus:ring-2 focus:ring-orange-500/25 dark:border-slate-600/50 dark:bg-slate-900/30 dark:text-slate-100"
                        />
                      </label>
                    </div>
                    <div className="mt-4 flex justify-end gap-2">
                      <button
                        type="button"
                        className={clsx(
                          'rounded-xl px-4 py-2 text-xs font-semibold text-white',
                          'bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500',
                          'shadow-[0_12px_28px_-18px_rgba(249,115,22,0.85)]',
                          'hover:from-amber-400 hover:via-orange-400 hover:to-rose-400',
                          'active:scale-[0.99] transition',
                          'focus:outline-none focus:ring-2 focus:ring-orange-500/25',
                          (!pwDraft.current || !pwDraft.next || accountBusy) && 'opacity-70 pointer-events-none',
                        )}
                        onClick={async () => {
                          setAccountBusy(true)
                          setAccountErr('')
                          setAccountOk('')
                          try {
                            await apiJson(`${baseUrl}/auth/change_password`, {
                              method: 'POST',
                              body: JSON.stringify({ current_password: pwDraft.current, new_password: pwDraft.next }),
                            })
                            setPwDraft({ current: '', next: '' })
                            setAccountOk('Code modifié.')
                          } catch (e) {
                            setAccountErr(e?.message || String(e || 'Erreur'))
                          } finally {
                            setAccountBusy(false)
                          }
                        }}
                      >
                        Changer le code
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}

        <section className="mt-4 flex min-h-0 flex-1 overflow-hidden">
          {workspaceVisible ? (
            <div className="fixed inset-0 z-40 lg:static lg:z-auto lg:inset-auto pointer-events-none">
              <div
                className="absolute inset-0 bg-slate-900/25 backdrop-blur-[2px] lg:hidden"
              />
              <aside
                id="workspace-sidebar"
                className={clsx(
                  'panel pointer-events-auto absolute left-3 top-3 bottom-3 w-[320px] max-w-[85vw] flex flex-col min-h-0 overflow-hidden',
                  'shadow-2xl lg:shadow-none',
                  'lg:static lg:h-full lg:w-[340px] lg:max-w-none',
                )}
              >
            <div className="border-b border-slate-200 dark:border-slate-600/50 px-4 py-3">
              <div className="text-sm font-medium text-slate-900 dark:text-slate-100">Workspace</div>
              <div className="text-xs text-slate-600 dark:text-slate-300">Modèle, période & conversations</div>
            </div>

            <div className="p-4 space-y-4 flex-1 min-h-0 overflow-y-auto">
              <div className="rounded-2xl border border-slate-200/60 dark:border-slate-600/45 bg-white/45 dark:bg-slate-900/25 p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-slate-700 dark:text-slate-300">Paramètres</div>
                  </div>
                </div>

                <div className="mt-3 grid gap-4">
                  <div>
                    <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">Modèle</div>
                    <div className="mt-1 grid grid-cols-3 gap-1 rounded-xl border border-slate-200/70 dark:border-slate-600/50 bg-white/60 dark:bg-slate-800/35 p-1">
                      <button
                        type="button"
                        className={clsx(
                          'min-w-0 rounded-lg px-3 py-2 text-xs font-medium transition-all duration-200 flex items-center justify-center gap-2',
                          modelName === 'trinity'
                            ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                            : 'text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
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
                            ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                            : 'text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
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
                            ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                            : 'text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
                        )}
                        onClick={() => onChangeModel('ollama')}
                        title="Local via Ollama (llama3.1:8b)"
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500/80" />
                        Llama3.1
                      </button>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] font-medium text-slate-600 dark:text-slate-300">
                      <span className="inline-flex items-center gap-1">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500 dark:bg-blue-400" /> Cloud
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500 dark:bg-emerald-400" /> Local
                      </span>
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">Période</div>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="flex-1 min-w-0">
                        <input
                          value={yearPick}
                          onChange={(e) => setYearPick(e.target.value.replace(/[^\d]/g, '').slice(0, 4))}
                          placeholder={`Année (ex: ${new Date().getFullYear()})`}
                          className={clsx(
                            'w-full rounded-xl px-3 py-2 text-xs',
                            'bg-white/60 dark:bg-slate-800/35 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500',
                            'border border-slate-200/60 dark:border-slate-600/45 focus:outline-none focus:ring-2 focus:ring-blue-500/15',
                            'transition-all duration-200',
                          )}
                          inputMode="numeric"
                        />
                      </div>
                      <button
                        type="button"
                        className="rounded-xl border border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 px-3 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-white/80 dark:hover:bg-slate-700/45 transition-all duration-200"
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
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900 dark:text-slate-100 dark:border-blue-400/35 dark:bg-blue-500/15'
                            : 'border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
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
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900 dark:text-slate-100 dark:border-blue-400/35 dark:bg-blue-500/15'
                            : 'border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
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
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900 dark:text-slate-100 dark:border-blue-400/35 dark:bg-blue-500/15'
                            : 'border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
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
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900 dark:text-slate-100 dark:border-blue-400/35 dark:bg-blue-500/15'
                            : 'border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
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
                            ? 'border-blue-500/20 bg-blue-500/5 text-slate-900 dark:text-slate-100 dark:border-blue-400/35 dark:bg-blue-500/15'
                            : 'border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
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
                          ? 'border-blue-500/20 bg-blue-500/5 text-slate-900 dark:text-slate-100 dark:border-blue-400/35 dark:bg-blue-500/15'
                          : 'border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 text-slate-600 dark:text-slate-400 hover:bg-white/80 dark:hover:bg-slate-700/45',
                      )}
                      onClick={() => setPeriodPreset('custom')}
                    >
                      Personnalisé…
                    </button>
                    {periodPreset === 'custom' ? (
                      <div className="mt-2 grid grid-cols-2 gap-2">
                        <input
                          type="date"
                          className="w-full rounded-xl border border-slate-200/80 dark:border-slate-600/55 bg-white/70 dark:bg-slate-800/45 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/20 transition-all duration-200"
                          value={customStart}
                          onChange={(e) => setCustomStart(e.target.value)}
                          aria-label="Début"
                        />
                        <input
                          type="date"
                          className="w-full rounded-xl border border-slate-200/80 dark:border-slate-600/55 bg-white/70 dark:bg-slate-800/45 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/20 transition-all duration-200"
                          value={customEnd}
                          onChange={(e) => setCustomEnd(e.target.value)}
                          aria-label="Fin"
                        />
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200/60 dark:border-slate-600/45 bg-white/45 dark:bg-slate-900/25 p-4 shadow-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs font-medium text-slate-700 dark:text-slate-300">Conversations</div>
                    <div className="mt-0.5 text-[11px] font-medium text-slate-600 dark:text-slate-300">
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
                      'bg-white/60 dark:bg-slate-800/35 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500',
                      'border border-slate-200/60 dark:border-slate-600/45 focus:outline-none focus:ring-2 focus:ring-blue-500/15',
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
                          ? 'border-blue-500/25 bg-blue-500/5 dark:border-blue-400/35 dark:bg-blue-500/15'
                          : 'border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 hover:bg-white/80 dark:hover:bg-slate-700/45 hover:border-slate-300/60 dark:hover:border-slate-500/50',
                      )}
                    >
                      <button
                        type="button"
                        className="w-full text-left"
                        onClick={() => loadConversation(h.session_id)}
                        title={h.session_id}
                      >
                        <div className="text-xs font-medium text-slate-900 dark:text-slate-100 line-clamp-2">{h.title || h.session_id}</div>
                        {!clientMode ? (
                          <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 font-mono">{h.session_id}</div>
                        ) : null}
                      </button>
                      <div className="mt-2 flex justify-end">
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-slate-500 dark:text-slate-400 hover:text-rose-700 hover:bg-rose-50/60 dark:hover:text-rose-400 dark:hover:bg-rose-950/40 transition-all duration-200"
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
                    <div className="rounded-xl border border-slate-200/60 dark:border-slate-600/45 bg-white/60 dark:bg-slate-800/35 p-3 text-xs text-slate-600 dark:text-slate-400">
                      Aucune conversation pour l’instant.
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </aside>
            </div>
          ) : null}

          <div
            className={clsx(
              'panel flex min-h-0 flex-1 flex-col overflow-hidden',
            )}
          >
            <div className="flex items-center justify-between gap-2 border-b border-slate-200 dark:border-slate-600/50 px-3 py-2.5 sm:px-4 sm:py-3">
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <button
                  type="button"
                  className={clsx(
                    'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition-colors',
                    'border-slate-200/90 bg-white/80 text-slate-700 shadow-sm hover:bg-slate-50',
                    'dark:border-slate-600/60 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:bg-slate-700/70',
                  )}
                  onClick={() => setWorkspaceOpen(!workspaceVisible)}
                  title={workspaceVisible ? 'Masquer le panneau Workspace' : 'Afficher le panneau Workspace'}
                  aria-expanded={workspaceVisible}
                  aria-controls="workspace-sidebar"
                >
                  <IconSidebar className="shrink-0" />
                </button>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-900 dark:text-slate-100">Chat</div>
                  <div className="hidden text-xs text-slate-600 dark:text-slate-300 sm:block">
                    {SONASID_CHAT_SUBTITLE}
              </div>
                </div>
              </div>
              <div className="flex flex-shrink-0 flex-wrap items-center justify-end gap-2 text-xs">
                <button
                  type="button"
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-[11px] font-semibold transition-colors',
                    theme === 'dark'
                      ? 'border-amber-400/45 bg-amber-500/15 text-amber-50 hover:bg-amber-500/25'
                      : 'border-slate-300 bg-white text-slate-800 shadow-sm hover:bg-slate-50',
                  )}
                  onClick={() => {
                    const next = theme === 'dark' ? 'light' : 'dark'
                    setTheme(next)
                    localStorage.setItem('sonasid_theme', next)
                  }}
                  aria-label={theme === 'dark' ? 'Activer le mode clair' : 'Activer le mode sombre'}
                >
                  {theme === 'dark' ? (
                    <>
                      <IconSun className="shrink-0 text-amber-200" />
                      Passer en clair
                    </>
                  ) : (
                    <>
                      <IconMoon className="shrink-0 text-slate-600" />
                      Passer en sombre
                    </>
                  )}
                </button>
                <span
                  className={clsx(
                    'font-medium',
                    busy ? 'text-blue-600 dark:text-blue-400' : 'text-emerald-700 dark:text-emerald-400',
                  )}
                >
                  {busy ? 'appel…' : 'prêt'}
                </span>
              </div>
            </div>

            <div
              ref={chatScrollRef}
              onScroll={onChatScroll}
              className="flex-1 min-h-0 overflow-y-auto px-3 py-3 sm:px-4 sm:py-4 scroll-smooth"
            >
              <div className="mx-auto w-full max-w-2xl sm:max-w-3xl lg:max-w-4xl xl:max-w-5xl">
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
                      <span className="font-medium text-slate-700 dark:text-slate-200">Exemples :</span>{' '}
                      {SONASID_WELCOME_HINT}
                    </div>
                  </div>
                ) : null}
                {lastKpiContext ? (
                  <div
                    role="status"
                    className="rounded-2xl border border-slate-200/70 bg-gradient-to-r from-white/80 to-slate-50/50 px-3 py-2.5 text-xs shadow-sm dark:border-slate-600/45 dark:from-slate-900/40 dark:to-slate-900/25 dark:text-slate-200"
                  >
                    <span className="font-semibold uppercase tracking-wide text-[10px] text-slate-500 dark:text-slate-400">
                      Dernier sujet
                    </span>
                    <div className="mt-1 font-medium leading-snug text-slate-800 dark:text-slate-100">
                      {lastKpiContext.label}
                    </div>
                  </div>
                ) : null}
                {chat.map((m, idx) => (
                  <div
                    key={idx}
                    className={clsx(
                      'fade-in group flex flex-col',
                      m.role === 'user' ? 'items-end' : 'items-start',
                    )}
                  >
                    <div
                      className={clsx(
                        'max-w-[92%] w-fit relative',
                        m.role === 'user' ? 'bubble-user' : 'bubble-ai',
                      )}
                    >
                    <div className="min-w-0">
                      <div className="min-w-0">
                        {m.role === 'user' && editingUserIdx === idx ? (
                          <div className="space-y-2">
                            <textarea
                              value={editingDraft}
                              onChange={(e) => setEditingDraft(e.target.value)}
                              className="w-full rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-sm text-slate-900 dark:border-slate-600/40 dark:bg-slate-900/25 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500/20"
                              rows={3}
                            />
                            <div className="flex items-center justify-end gap-2">
                              <button
                                type="button"
                                className="btn-ghost text-xs"
                                onClick={() => {
                                  setEditingUserIdx(null)
                                  setEditingDraft('')
                                }}
                              >
                                Annuler
                              </button>
                              <button
                                type="button"
                                className={clsx('btn-primary text-xs', busy && 'opacity-60 pointer-events-none')}
                                onClick={() => regenerateFromEditedUser(idx)}
                              >
                                Regénérer
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            {m.role !== 'user' && m?.meta?.raw && extractSqlPayload(m.meta.raw, { userQuestion: getPrecedingUserContent(chat, idx) }) ? (
                              (() => {
                                const userQ = getPrecedingUserContent(chat, idx)
                                const payload = extractSqlPayload(m.meta.raw, { userQuestion: userQ })
                                if (!payload) return <ChatMarkdown content={m.content} />
                                const raw = m.meta.raw
                                const err = raw?.error
                                const friendly =
                                  typeof raw?.message === 'string' && raw.message.trim()
                                    ? raw.message.trim()
                                    : typeof m.content === 'string' && m.content.trim()
                                      ? m.content.trim()
                                      : ''
                                const isDbError =
                                  String(raw?.source || '') === 'pipeline:db_error' ||
                                  err === 'DB_FIREWALL'
                                return (
                                  <div>
                                    {friendly ? (
                                      <ChatMarkdown content={friendly} />
                                    ) : null}
                                    {err && !friendly ? (
                                      <div className="mt-2 rounded-xl border border-rose-200/70 bg-rose-50/70 px-3 py-2 text-xs text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/25 dark:text-rose-200 whitespace-pre-wrap">
                                        {String(err)}
                                      </div>
                                    ) : null}
                                    <details
                                      className={clsx('mt-3', isDbError && 'opacity-90')}
                                      open={!isDbError}
                                    >
                                      <summary className="cursor-pointer text-[11px] font-medium text-slate-600 dark:text-slate-300">
                                        {isDbError
                                          ? 'Requête T-SQL générée (non exécutée — connexion bloquée)'
                                          : payload.kind === 'catalog'
                                            ? `Requêtes T‑SQL (Azure) — tous les KPIs (${payload.blocks.length})`
                                            : `Requête${payload.kind === 'multi' ? 's' : ''} SQL`}
                                      </summary>
                                    <div className={clsx('mt-2', payload.kind === 'catalog' ? 'space-y-1.5' : 'space-y-2')}>
                                      {payload.blocks.map((b) => {
                                        const key = `${idx}:${b.label}`
                                        const copied = Boolean(copiedSqlByKey[key])
                                        const CopyBtn = (
                                          <button
                                            type="button"
                                            className="btn-ghost text-xs"
                                            onClick={async () => {
                                              const ok = await copyToClipboard(b.text)
                                              if (!ok) return
                                              setCopiedSqlByKey((prev) => ({ ...prev, [key]: true }))
                                              setTimeout(() => {
                                                setCopiedSqlByKey((prev) => {
                                                  const next = { ...prev }
                                                  delete next[key]
                                                  return next
                                                })
                                              }, 1200)
                                            }}
                                          >
                                            Copier
                                          </button>
                                        )

                                        if (payload.kind === 'catalog') {
                                          return (
                                            <details
                                              key={b.label}
                                              className="rounded-xl border border-slate-200/70 bg-white/50 px-3 py-2 dark:border-slate-600/40 dark:bg-slate-900/20"
                                            >
                                              <summary className="cursor-pointer list-none">
                                                <div className="flex items-center justify-between gap-2">
                                                  <div className="text-[12px] font-medium text-slate-700 dark:text-slate-200">
                                                    {b.label}
                                                  </div>
                                                  <div className="flex items-center gap-2">
                                                    {copied ? (
                                                      <span className="text-[11px] text-emerald-600 dark:text-emerald-400">Copié.</span>
                                                    ) : null}
                                                    {CopyBtn}
                                                  </div>
                                                </div>
                                              </summary>
                                              <pre className="mt-2 rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-[12px] leading-relaxed text-slate-800 shadow-sm dark:border-slate-600/40 dark:bg-slate-900/25 dark:text-slate-100 overflow-x-auto">
                                                {b.text}
                                              </pre>
                                            </details>
                                          )
                                        }

                                        return (
                                          <div key={b.label}>
                                            <div className="mb-1 flex items-center justify-between gap-2">
                                              <div className="text-[11px] text-slate-500 dark:text-slate-400">{b.label}</div>
                                              <div className="flex items-center gap-2">
                                                {copied ? (
                                                  <span className="text-[11px] text-emerald-600 dark:text-emerald-400">Copié.</span>
                                                ) : null}
                                                {CopyBtn}
                                              </div>
                                            </div>
                                            <pre className="rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-[12px] leading-relaxed text-slate-800 shadow-sm dark:border-slate-600/40 dark:bg-slate-900/25 dark:text-slate-100 overflow-x-auto">
                                              {b.text}
                                            </pre>
                                          </div>
                                        )
                                      })}
                                    </div>
                                    </details>
                                  </div>
                                )
                              })()
                            ) : (
                    <ChatMarkdown content={m.content} />
                            )}
                          </>
                        )}
                      </div>

                    </div>
                    {m.role !== 'user' && m?.meta?.raw && extractChartSpec(m.meta.raw) ? (
                      <ResultChart raw={m.meta.raw} theme={theme} />
                    ) : null}
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
                                  <div className="text-[11px] text-slate-500 dark:text-slate-400">
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
                    {m.role === 'assistant' &&
                    m?.meta?.raw &&
                    isSuccessfulKpiResponse(m.meta.raw) &&
                    idx > 0
                      ? (() => {
                          const baseQ =
                            String(m.meta.raw.question || '').trim() ||
                            getPrecedingUserContent(chat, idx).trim()
                          const analyseQ = buildAnalyzeKpiQuery(baseQ, m.meta.raw)
                          const actions = [
                            ...(analyseQ
                              ? [{ id: 'analyse', label: 'Analyser', query: analyseQ }]
                              : []),
                            ...collectKpiQuickActions(baseQ, { periodPreset, period }),
                          ]
                          if (!actions.length) return null
                          return (
                            <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-slate-200/50 pt-2 dark:border-slate-600/35">
                              <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                                Poursuivre
                              </span>
                              {actions.map((a) => (
                                <button
                                  key={`${idx}-qa-${a.id}`}
                                  type="button"
                                  disabled={busy}
                                  className={clsx(
                                    'rounded-full border px-3 py-1 text-[11px] font-medium transition-colors',
                                    'border-slate-200/90 bg-white/90 text-slate-700 hover:border-blue-300/60 hover:bg-blue-50/50',
                                    'dark:border-slate-600/55 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:border-blue-500/40 dark:hover:bg-slate-800',
                                    busy && 'pointer-events-none opacity-50',
                                    a.id === 'analyse' &&
                                      'border-violet-200/90 hover:border-violet-400/50 hover:bg-violet-50/40 dark:border-violet-500/30 dark:hover:bg-violet-950/25',
                                  )}
                                  onClick={() =>
                                    a.id === 'analyse'
                                      ? sendChat({
                                          question: a.query,
                                          display: 'Analyser ce résultat',
                                        })
                                      : sendChat(a.query)
                                  }
                                >
                                  {a.label}
                                </button>
                              ))}
                            </div>
                          )
                        })()
                      : null}
                    {m.role === 'assistant' && idx > 0
                      ? (() => {
                          const prevUser = getPrecedingUserContent(chat, idx)
                          const assistantText = String(m.content || '').trim()
                          if (!prevUser.trim() || assistantText.length < 6) return null
                          const v = feedbackVote[idx]
                          const st = feedbackStatus[idx]
                          return (
                            <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-slate-200/60 dark:border-slate-600/40 pt-2">
                              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                                Cette réponse est-elle utile ?
                              </span>
                              <button
                                type="button"
                                className={clsx(
                                  'inline-flex items-center justify-center rounded-lg p-1.5 transition-colors',
                                  v === 1
                                    ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
                                    : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200',
                                )}
                                aria-label="Utile"
                                title="Utile"
                                onClick={() => submitFeedback(idx, 1, prevUser, assistantText)}
                              >
                                <IconThumbUp className="shrink-0" />
                              </button>
                              <button
                                type="button"
                                className={clsx(
                                  'inline-flex items-center justify-center rounded-lg p-1.5 transition-colors',
                                  v === -1
                                    ? 'bg-rose-500/20 text-rose-700 dark:text-rose-300'
                                    : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200',
                                )}
                                aria-label="Pas utile"
                                title="Pas utile"
                                onClick={() => submitFeedback(idx, -1, prevUser, assistantText)}
                              >
                                <IconThumbDown className="shrink-0" />
                              </button>
                              {st === 'ok' ? (
                                <span className="text-[11px] text-emerald-600 dark:text-emerald-400">
                                  Merci, enregistré.
                                </span>
                              ) : null}
                              {st === 'err' ? (
                                <span className="text-[11px] text-rose-600 dark:text-rose-400">
                                  Envoi impossible (API).
                                </span>
                              ) : null}
                              {v === -1 ? (
                                <button
                                  type="button"
                                  className="btn-ghost text-xs"
                                  disabled={busy}
                                  title="Relance une passe avec consigne de correction (sans fine-tune du modèle)"
                                  onClick={() => submitAutoCorrection(prevUser, assistantText)}
                                >
                                  Réessayer (auto-correction)
                                </button>
                              ) : null}
                            </div>
                          )
                        })()
                      : null}
                    {m?.created_at ? (
                      <div
                        className={clsx(
                          'mt-1 text-[10px] text-right select-none',
                          m.role === 'user'
                            ? 'text-white/75 drop-shadow-[0_1px_1px_rgba(0,0,0,0.25)]'
                            : 'text-slate-500/80 dark:text-slate-300/70',
                        )}
                      >
                        {formatMsgTime(m.created_at)}
                      </div>
                    ) : null}
                    </div>

                    {/* ChatGPT-like actions: below the bubble, only on hover */}
                    {editingUserIdx !== idx ? (
                      <div
                        className={clsx(
                          'mt-1 flex items-center gap-1',
                          'opacity-0 group-hover:opacity-100 transition-opacity duration-150',
                          'focus-within:opacity-100',
                        )}
                      >
                        <button
                          type="button"
                          className={clsx(
                            'rounded-md p-1.5',
                            'text-slate-600 dark:text-slate-300',
                            'hover:bg-slate-200/60 dark:hover:bg-slate-700/40',
                          )}
                          onClick={async () => {
                            const ok = await copyToClipboard(m.content)
                            if (!ok) return
                            setCopiedMsgByIdx((prev) => ({ ...prev, [idx]: true }))
                            setTimeout(() => {
                              setCopiedMsgByIdx((prev) => {
                                const next = { ...prev }
                                delete next[idx]
                                return next
                              })
                            }, 900)
                          }}
                          title="Copier"
                          aria-label="Copier le message"
                        >
                          {copiedMsgByIdx[idx] ? (
                            <IconCheck className="text-emerald-600 dark:text-emerald-400" />
                          ) : (
                            <IconCopy className="text-slate-600 dark:text-slate-300" />
                          )}
                        </button>
                        {m.role === 'user' ? (
                          <button
                            type="button"
                            className={clsx(
                              'rounded-md p-1.5',
                              'text-slate-600 dark:text-slate-300',
                              'hover:bg-slate-200/60 dark:hover:bg-slate-700/40',
                            )}
                            onClick={() => {
                              setEditingUserIdx(idx)
                              setEditingDraft(String(m.content || ''))
                            }}
                            title="Modifier"
                            aria-label="Modifier la question"
                          >
                            <IconPencil className="text-slate-600 dark:text-slate-300" />
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ))}
                {busy ? (
                  <div className="max-w-[92%] bubble-ai animate-pulse">
                    <div className="flex items-center gap-2 text-slate-600 dark:text-slate-400">
                      <span className="inline-block h-2 w-2 rounded-full bg-blue-500/70" />
                      <span className="inline-block h-2 w-2 rounded-full bg-fuchsia-500/60" />
                      <span className="inline-block h-2 w-2 rounded-full bg-slate-400/50" />
                      <span className="ml-1 text-xs text-slate-500 dark:text-slate-400">en train d’écrire…</span>
                    </div>
                  </div>
                ) : null}
                <div ref={chatEndRef} />
                </div>
              </div>
            </div>

            <form
              className={clsx(
                'flex items-stretch gap-2 border-t border-slate-200 dark:border-slate-600/50',
                workspaceVisible ? 'p-3' : 'p-4 sm:p-5',
              )}
              onSubmit={(e) => {
                e.preventDefault()
                sendChat(chatInput)
              }}
            >
              <div className="mx-auto w-full max-w-2xl sm:max-w-3xl lg:max-w-4xl xl:max-w-5xl flex items-stretch gap-2">
                <div className="relative min-w-0 flex-1" ref={modelPickerRef}>
                  <div
                    className={clsx(
                      'flex min-h-[48px] w-full items-center gap-0.5 border transition-all duration-200',
                      'border-slate-200/90 bg-white/80 text-slate-900 dark:border-slate-600/55 dark:bg-slate-800/55 dark:text-slate-100',
                      'focus-within:border-blue-400/40 focus-within:ring-2 focus-within:ring-blue-500/20 dark:focus-within:border-blue-500/30',
                      workspaceVisible
                        ? 'rounded-xl px-1 py-1 shadow-sm'
                        : 'rounded-full px-1.5 py-1.5 shadow-md shadow-slate-900/6 dark:shadow-black/25',
                    )}
                  >
                    <button
                      type="button"
                      className={clsx(
                        'flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors',
                        'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700/70',
                        modelPickerOpen && 'bg-slate-100 dark:bg-slate-700/60',
                      )}
                      onClick={() => setModelPickerOpen((o) => !o)}
                      aria-expanded={modelPickerOpen}
                      aria-haspopup="listbox"
                      aria-label="Choisir le modèle"
                      title="Modèle : Trinity, Flash ou Llama3.1 (local)"
                    >
                      <IconPlus className="shrink-0" />
                    </button>
                    <input
                      className={clsx(
                        'min-w-0 flex-1 bg-transparent py-2.5 text-sm outline-none',
                        'placeholder:text-slate-400 dark:placeholder:text-slate-500',
                        workspaceVisible ? 'pr-3' : 'pr-2',
                      )}
                      placeholder={SONASID_CHAT_PLACEHOLDER}
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      aria-label="Message"
                    />
                    <button
                      type="button"
                      className={clsx(
                        'flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors',
                        sttSupported
                          ? sttListening
                            ? 'bg-rose-500/15 text-rose-700 dark:bg-rose-500/25 dark:text-rose-200'
                            : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700/70'
                          : 'opacity-40 text-slate-400 cursor-not-allowed',
                      )}
                      onClick={() => {
                        if (!sttSupported) return
                        if (sttListening) stopStt()
                        else startStt()
                      }}
                      disabled={!sttSupported || busy}
                      aria-pressed={sttListening}
                      aria-label={sttListening ? 'Arrêter la dictée' : 'Dicter le message'}
                      title={sttListening ? 'Arrêter la dictée' : 'Dicter (speech-to-text)'}
                    >
                      <IconMic className={clsx('shrink-0', sttListening ? 'animate-pulse' : '')} />
                    </button>
                  </div>
                  {sttErr ? (
                    <div className="mt-1 text-[11px] font-medium text-rose-600 dark:text-rose-300">
                      {sttErr}
                    </div>
                  ) : null}
                  {modelPickerOpen ? (
                    <div
                      role="listbox"
                      aria-label="Modèles disponibles"
                      className={clsx(
                        'absolute bottom-full left-0 z-30 mb-2 w-[min(100%,280px)] overflow-hidden rounded-2xl border py-1 shadow-xl',
                        'border-slate-200/90 bg-white/95 backdrop-blur-md dark:border-slate-600/60 dark:bg-slate-900/95',
                      )}
                    >
                      <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                        Modèle pour ce chat
                      </div>
                      {CHAT_MODEL_OPTIONS.map((opt) => (
                        <button
                          key={opt.id}
                          type="button"
                          role="option"
                          aria-selected={modelName === opt.id}
                          className={clsx(
                            'flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors',
                            modelName === opt.id
                              ? 'bg-blue-500/10 dark:bg-blue-500/20'
                              : 'hover:bg-slate-50 dark:hover:bg-slate-800/80',
                          )}
                          onClick={() => {
                            onChangeModel(opt.id)
                            setModelPickerOpen(false)
                          }}
                        >
                          <span
                            className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', opt.dot)}
                            aria-hidden
                          />
                          <span>
                            <span className="block text-sm font-medium text-slate-900 dark:text-slate-100">
                              {opt.label}
                            </span>
                            <span className="mt-0.5 block text-[11px] text-slate-500 dark:text-slate-400">
                              {opt.hint}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
                <button
                  type="submit"
                  className={clsx(
                    'btn-primary shrink-0 self-center',
                    busy ? 'opacity-60' : '',
                    !workspaceVisible && 'rounded-full px-5 py-3',
                  )}
                  disabled={busy}
                >
                Envoyer
              </button>
              </div>
            </form>
          </div>
        </section>
      </div>
    </div>
  )
}

