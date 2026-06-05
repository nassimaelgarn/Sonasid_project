import React from 'react'

function renderInline(text) {
  const s = String(text ?? '')
  if (!s) return null
  const parts = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g
  let last = 0
  let m
  let k = 0
  while ((m = re.exec(s)) !== null) {
    if (m.index > last) parts.push(<span key={`t-${k++}`}>{s.slice(last, m.index)}</span>)
    const tok = m[0]
    if (tok.startsWith('**')) {
      parts.push(
        <strong key={`b-${k++}`} className="font-semibold text-slate-900 dark:text-slate-50">
          {tok.slice(2, -2)}
        </strong>,
      )
    } else if (tok.startsWith('`')) {
      parts.push(
        <code
          key={`c-${k++}`}
          className="rounded bg-slate-100/90 px-1 py-0.5 font-mono text-[0.85em] text-slate-800 dark:bg-slate-800/80 dark:text-slate-100"
        >
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (tok.startsWith('*')) {
      parts.push(<em key={`i-${k++}`}>{tok.slice(1, -1)}</em>)
    }
    last = m.index + tok.length
  }
  if (last < s.length) parts.push(<span key={`t-${k++}`}>{s.slice(last)}</span>)
  return parts.length ? parts : s
}

function parseBlocks(text) {
  const lines = String(text ?? '').split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    const hm = trimmed.match(/^(#{1,3})\s+(.+)$/)
    if (hm) {
      blocks.push({ type: 'heading', level: hm[1].length, text: hm[2] })
      i += 1
      continue
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push({ type: 'hr' })
      i += 1
      continue
    }

    if (trimmed.startsWith('```')) {
      const lang = trimmed.slice(3).trim()
      const codeLines = []
      i += 1
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i])
        i += 1
      }
      if (i < lines.length) i += 1
      blocks.push({ type: 'code', lang, text: codeLines.join('\n') })
      continue
    }

    if (/^[-*•]\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ''))
        i += 1
      }
      blocks.push({ type: 'ul', items })
      continue
    }

    const para = [line]
    i += 1
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().match(/^#{1,3}\s/) &&
      !/^[-*•]\s+/.test(lines[i].trim()) &&
      !lines[i].trim().startsWith('```')
    ) {
      para.push(lines[i])
      i += 1
    }
    blocks.push({ type: 'p', text: para.join('\n') })
  }
  return blocks
}

export function ChatMarkdown({ content, className = '' }) {
  const blocks = parseBlocks(content)
  if (!blocks.length) {
    return <div className={className}>{String(content ?? '')}</div>
  }

  return (
    <div className={`chat-md space-y-2 text-[13px] leading-relaxed text-slate-800 dark:text-slate-100 ${className}`}>
      {blocks.map((b, idx) => {
        if (b.type === 'heading') {
          const Tag = b.level <= 2 ? 'h2' : 'h3'
          const cls =
            b.level <= 2
              ? 'text-[15px] font-bold tracking-tight text-slate-900 dark:text-white mt-1 mb-1.5'
              : 'text-[14px] font-semibold text-slate-900 dark:text-slate-50 mt-2.5 mb-1 border-b border-slate-200/60 pb-1 dark:border-slate-600/40'
          return (
            <Tag key={idx} className={cls}>
              {renderInline(b.text)}
            </Tag>
          )
        }
        if (b.type === 'hr') {
          return <hr key={idx} className="my-2 border-slate-200/70 dark:border-slate-600/45" />
        }
        if (b.type === 'ul') {
          return (
            <ul key={idx} className="ml-1 list-none space-y-1">
              {b.items.map((item, j) => (
                <li key={j} className="flex gap-2">
                  <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-orange-500/80" aria-hidden />
                  <span className="min-w-0 flex-1">{renderInline(item)}</span>
                </li>
              ))}
            </ul>
          )
        }
        if (b.type === 'code') {
          return (
            <pre
              key={idx}
              className="overflow-x-auto rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-800 shadow-sm dark:border-slate-600/40 dark:bg-slate-900/30 dark:text-slate-100"
            >
              {b.text}
            </pre>
          )
        }
        return (
          <p key={idx} className="whitespace-pre-wrap">
            {renderInline(b.text)}
          </p>
        )
      })}
    </div>
  )
}
