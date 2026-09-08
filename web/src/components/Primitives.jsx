import { useEffect, useRef, useState } from 'react'
import { IconAlert, IconChevron } from './Icons'

/* -------------------------------------------------------------------------
   Markdown - the narrator emits a small, known subset, so a focused renderer
   beats pulling in a full markdown library.
   ------------------------------------------------------------------------- */

function renderInline(text, keyBase) {
  // **bold** and `code`, in one pass
  const parts = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let cursor = 0
  let match
  let index = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index))
    const token = match[0]
    if (token.startsWith('**')) {
      parts.push(<strong key={`${keyBase}-b${index++}`}>{token.slice(2, -2)}</strong>)
    } else {
      parts.push(<code key={`${keyBase}-c${index++}`}>{token.slice(1, -1)}</code>)
    }
    cursor = match.index + token.length
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts
}

export function Markdown({ text }) {
  if (!text) return null

  const lines = String(text).replace(/\r/g, '').split('\n')
  const blocks = []
  let list = []
  let paragraph = []

  const flushList = () => {
    if (!list.length) return
    blocks.push(
      <ul key={`ul-${blocks.length}`}>
        {list.map((item, i) => (
          <li key={i}>{renderInline(item, `li-${blocks.length}-${i}`)}</li>
        ))}
      </ul>,
    )
    list = []
  }

  const flushParagraph = () => {
    if (!paragraph.length) return
    const joined = paragraph.join(' ').trim()
    if (joined) {
      // The narrator's "Insight:" line is the interpretation, set apart on purpose
      const insight = joined.match(/^\**insight\**\s*:?\s*(.*)$/i)
      if (insight) {
        blocks.push(
          <div className="insight" key={`in-${blocks.length}`}>
            {renderInline(insight[1], `in-${blocks.length}`)}
          </div>,
        )
      } else {
        blocks.push(<p key={`p-${blocks.length}`}>{renderInline(joined, `p-${blocks.length}`)}</p>)
      }
    }
    paragraph = []
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/)
    if (bullet) {
      flushParagraph()
      list.push(bullet[1])
      continue
    }
    if (!line.trim()) {
      flushParagraph()
      flushList()
      continue
    }
    flushList()
    paragraph.push(line.trim())
  }
  flushParagraph()
  flushList()

  return <div className="prose">{blocks}</div>
}

/* -------------------------------------------------------------------------
   Data table
   ------------------------------------------------------------------------- */

export function DataTable({ table, maxRows = 200 }) {
  if (!table || !table.columns?.length) return null
  const rows = table.rows.slice(0, maxRows)

  const format = (value, type) => {
    if (value === null || value === undefined || value === '') return null
    if (type === 'number' && typeof value === 'number') {
      if (Number.isInteger(value)) return value.toLocaleString()
      return value.toLocaleString(undefined, { maximumFractionDigits: 3 })
    }
    if (type === 'date') return String(value).slice(0, 10)
    return String(value)
  }

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {table.columns.map((column) => (
              <th key={column.key} className={column.type === 'number' ? 'num' : undefined}>
                {column.key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {table.columns.map((column) => {
                const value = format(row[column.key], column.type)
                return (
                  <td
                    key={column.key}
                    className={[
                      column.type === 'number' ? 'num' : '',
                      value === null ? 'null' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    title={value ?? ''}
                  >
                    {value ?? '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {table.total > rows.length && (
        <div className="tiny muted" style={{ padding: '8px 12px' }}>
          Showing {rows.length.toLocaleString()} of {table.total.toLocaleString()} rows
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------
   Small pieces
   ------------------------------------------------------------------------- */

export function Chip({ tone = 'accent', children, title }) {
  return (
    <span className={`chip chip-${tone}`} title={title}>
      {children}
    </span>
  )
}

export function RoleChip({ role, children }) {
  const tone = ['metric', 'dimension', 'date', 'identifier', 'text'].includes(role)
    ? role
    : 'accent'
  return <Chip tone={tone}>{children ?? role}</Chip>
}

export function Callout({ tone = 'info', children }) {
  return (
    <div className={`callout callout-${tone}`}>
      <IconAlert size={15} />
      <div>{children}</div>
    </div>
  )
}

export function Fold({ label, children, defaultOpen = false, right }) {
  return (
    <details className="fold" open={defaultOpen}>
      <summary>
        <IconChevron size={13} className="caret" />
        <span style={{ flex: 1 }}>{label}</span>
        {right}
      </summary>
      <div className="fold-body">{children}</div>
    </details>
  )
}

export function Spinner() {
  return <span className="spinner" />
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}

/* -------------------------------------------------------------------------
   Toasts
   ------------------------------------------------------------------------- */

let pushToast = () => {}

export function toast(message, tone = 'info') {
  pushToast(message, tone)
}

export function ToastHost() {
  const [items, setItems] = useState([])
  const counter = useRef(0)

  useEffect(() => {
    pushToast = (message, tone) => {
      const id = ++counter.current
      setItems((current) => [...current, { id, message, tone }])
      setTimeout(() => setItems((current) => current.filter((t) => t.id !== id)), 3600)
    }
    return () => {
      pushToast = () => {}
    }
  }, [])

  if (!items.length) return null
  return (
    <div className="toasts">
      {items.map((item) => (
        <div className="toast" key={item.id} data-tone={item.tone} role="status">
          {item.message}
        </div>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------------------
   Helpers
   ------------------------------------------------------------------------- */

export function downloadCsv(filename, csv) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function tableToCsv(table) {
  if (!table?.columns?.length) return ''
  const escape = (value) => {
    if (value === null || value === undefined) return ''
    const text = String(value)
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const header = table.columns.map((c) => escape(c.key)).join(',')
  const body = table.rows.map((row) => table.columns.map((c) => escape(row[c.key])).join(','))
  return [header, ...body].join('\n')
}
