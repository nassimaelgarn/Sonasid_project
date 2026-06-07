/**
 * Export dashboard / tableaux Sonasid — Excel (.xlsx) et PDF.
 */
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import * as XLSX from 'xlsx'

function slugify(text) {
  return String(text || 'export')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
    .toLowerCase() || 'export'
}

function sanitizeSheetName(name) {
  const s = String(name || 'Feuille')
    .replace(/[:\\/?*[\]]/g, ' ')
    .trim()
    .slice(0, 31)
  return s || 'Feuille'
}

function formatFrNum(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value ?? '')
  if (Math.abs(n - Math.round(n)) < 1e-6) return String(Math.round(n))
  return n.toLocaleString('fr-FR', { maximumFractionDigits: 2 })
}

function rowsToColumns(rows) {
  if (!Array.isArray(rows) || !rows.length) return []
  const keys = new Set()
  for (const r of rows) {
    if (r && typeof r === 'object') Object.keys(r).forEach((k) => keys.add(k))
  }
  return [...keys]
}

/** Export lignes JSON → .xlsx */
export function exportRowsExcel(rows, { filename = 'tableau-sonasid.xlsx', sheetName = 'Données' } = {}) {
  if (!Array.isArray(rows) || !rows.length) return false
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), sanitizeSheetName(sheetName))
  XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`)
  return true
}

/** Export lignes JSON → PDF (table) */
export function exportRowsPdf(rows, { title = 'Tableau Sonasid', filename = 'tableau-sonasid.pdf' } = {}) {
  if (!Array.isArray(rows) || !rows.length) return false
  const cols = rowsToColumns(rows)
  const doc = new jsPDF({ orientation: cols.length > 5 ? 'landscape' : 'portrait' })
  doc.setFontSize(13)
  doc.text(title, 14, 16)
  autoTable(doc, {
    startY: 22,
    head: [cols],
    body: rows.map((r) => cols.map((c) => formatFrNum(r?.[c]))),
    styles: { fontSize: 8, cellPadding: 2 },
    headStyles: { fillColor: [232, 97, 50] },
  })
  doc.save(filename.endsWith('.pdf') ? filename : `${filename}.pdf`)
  return true
}

/** Export dashboard (cartes KPI + séries graphiques) → Excel multi-feuilles */
export function exportDashboardExcel(dashboard, { question = '', message = '' } = {}) {
  if (!dashboard || typeof dashboard !== 'object') return false
  const kpis = Array.isArray(dashboard.kpis) ? dashboard.kpis : []
  const charts = Array.isArray(dashboard.charts) ? dashboard.charts : []
  if (!kpis.length && !charts.length) return false

  const wb = XLSX.utils.book_new()
  const metaRows = [
    { champ: 'Titre', valeur: dashboard.title || '' },
    { champ: 'Question', valeur: question || '' },
  ]
  if (message) metaRows.push({ champ: 'Résumé', valeur: String(message).slice(0, 2000) })
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(metaRows), 'Info')

  if (kpis.length) {
    XLSX.utils.book_append_sheet(
      wb,
      XLSX.utils.json_to_sheet(
        kpis.map((k) => ({
          Indicateur: k.label ?? '',
          Année: k.year ?? '',
          Valeur: k.value ?? '',
          Unité: k.unit ?? '',
        })),
      ),
      'KPIs',
    )
  }

  for (let i = 0; i < charts.length; i += 1) {
    const ch = charts[i]
    const series = Array.isArray(ch.result) ? ch.result : []
    if (!series.length) continue
    XLSX.utils.book_append_sheet(
      wb,
      XLSX.utils.json_to_sheet(series),
      sanitizeSheetName(ch.title || `Graphique ${i + 1}`),
    )
  }

  const base = slugify(dashboard.title || question || 'dashboard')
  XLSX.writeFile(wb, `sonasid-${base}.xlsx`)
  return true
}

/** Export dashboard → PDF */
export function exportDashboardPdf(dashboard, { question = '', message = '' } = {}) {
  if (!dashboard || typeof dashboard !== 'object') return false
  const kpis = Array.isArray(dashboard.kpis) ? dashboard.kpis : []
  const charts = Array.isArray(dashboard.charts) ? dashboard.charts : []
  if (!kpis.length && !charts.length) return false

  const doc = new jsPDF()
  let y = 14
  doc.setFontSize(14)
  doc.setTextColor(51, 51, 54)
  doc.text(dashboard.title || 'Dashboard port & arrivages — Sonasid', 14, y)
  y += 8
  doc.setFontSize(9)
  doc.setTextColor(100, 116, 139)
  if (question) {
    const qLines = doc.splitTextToSize(`Question : ${question}`, 180)
    doc.text(qLines, 14, y)
    y += qLines.length * 5 + 4
  }

  if (kpis.length) {
    autoTable(doc, {
      startY: y,
      head: [['Indicateur', 'Année', 'Valeur', 'Unité']],
      body: kpis.map((k) => [
        String(k.label ?? ''),
        String(k.year ?? ''),
        formatFrNum(k.value),
        String(k.unit ?? ''),
      ]),
      styles: { fontSize: 9 },
      headStyles: { fillColor: [232, 97, 50] },
    })
    y = doc.lastAutoTable.finalY + 10
  }

  for (const ch of charts) {
    const series = Array.isArray(ch.result) ? ch.result : []
    if (!series.length) continue
    if (y > 250) {
      doc.addPage()
      y = 16
    }
    doc.setFontSize(11)
    doc.setTextColor(51, 51, 54)
    doc.text(String(ch.title || 'Série'), 14, y)
    y += 6
    const cols = rowsToColumns(series)
    autoTable(doc, {
      startY: y,
      head: [cols],
      body: series.slice(0, 24).map((r) => cols.map((c) => formatFrNum(r?.[c]))),
      styles: { fontSize: 8 },
      headStyles: { fillColor: [100, 116, 139] },
    })
    y = doc.lastAutoTable.finalY + 10
  }

  if (message && y < 240) {
    doc.setFontSize(9)
    doc.setTextColor(71, 85, 105)
    const excerpt = String(message).replace(/\*\*/g, '').slice(0, 1200)
    const lines = doc.splitTextToSize(excerpt, 180)
    doc.text(lines.slice(0, 12), 14, y)
  }

  const base = slugify(dashboard.title || question || 'dashboard')
  doc.save(`sonasid-${base}.pdf`)
  return true
}

/** Boutons réutilisables — classes Tailwind alignées UI Sonasid */
export const exportBtnClass =
  'inline-flex items-center gap-1 rounded-lg border border-slate-200/80 bg-white/80 px-2.5 py-1 text-[11px] font-medium text-slate-700 shadow-sm transition hover:bg-orange-50 hover:border-orange-200/80 dark:border-slate-600/50 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:bg-slate-700/60'
