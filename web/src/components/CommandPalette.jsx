import { useEffect, useMemo, useRef, useState } from 'react'
import { IconGauge, IconLayers, IconMessage, IconSparkle, IconTable } from './Icons'

/**
 * Ctrl/Cmd+K. Jumps between views and fires a suggested question straight into
 * the assistant, so keyboard users never touch the sidebar.
 */

const VIEW_ICONS = {
  chat: IconMessage,
  dashboard: IconGauge,
  explorer: IconTable,
  retrieval: IconLayers,
}

export default function CommandPalette({ open, onClose, dataset, onNavigate, onAsk }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const input = useRef(null)

  const commands = useMemo(() => {
    const items = [
      { id: 'chat', label: 'Go to Assistant', group: 'view', run: () => onNavigate('chat') },
      { id: 'dashboard', label: 'Go to Dashboard', group: 'view', run: () => onNavigate('dashboard') },
      { id: 'explorer', label: 'Go to Data explorer', group: 'view', run: () => onNavigate('explorer') },
      { id: 'retrieval', label: 'Go to Retrieval layer', group: 'view', run: () => onNavigate('retrieval') },
    ]
    for (const question of dataset?.profile?.suggestedQuestions || []) {
      items.push({ id: `q:${question}`, label: question, group: 'ask', run: () => onAsk(question) })
    }
    return items
  }, [dataset, onNavigate, onAsk])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const base = needle
      ? commands.filter((item) => item.label.toLowerCase().includes(needle))
      : commands
    // Anything typed can be sent to the assistant verbatim
    if (needle.length > 3 && dataset) {
      return [
        { id: 'ask-raw', label: `Ask: “${query.trim()}”`, group: 'ask', run: () => onAsk(query.trim()) },
        ...base,
      ]
    }
    return base
  }, [query, commands, dataset, onAsk])

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(0)
      setTimeout(() => input.current?.focus(), 30)
    }
  }, [open])

  useEffect(() => setCursor(0), [query])

  if (!open) return null

  const run = (item) => {
    onClose()
    item.run()
  }

  const onKeyDown = (event) => {
    if (event.key === 'Escape') return onClose()
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((c) => Math.min(c + 1, filtered.length - 1))
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    }
    if (event.key === 'Enter' && filtered[cursor]) {
      event.preventDefault()
      run(filtered[cursor])
    }
  }

  return (
    <div className="palette-scrim" onClick={onClose}>
      <div className="palette" onClick={(event) => event.stopPropagation()} role="dialog">
        <input
          ref={input}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={dataset ? 'Jump to a view, or type a question…' : 'Jump to a view…'}
          aria-label="Command palette"
        />
        <div className="palette-list">
          {filtered.length === 0 && (
            <div className="tiny muted" style={{ padding: '14px 12px' }}>
              Nothing matches.
            </div>
          )}
          {filtered.map((item, index) => {
            const Icon = item.group === 'view' ? VIEW_ICONS[item.id] || IconMessage : IconSparkle
            return (
              <button
                key={item.id}
                className="palette-item"
                data-active={index === cursor}
                onMouseEnter={() => setCursor(index)}
                onClick={() => run(item)}
              >
                <Icon size={15} />
                <span style={{ flex: 1 }}>{item.label}</span>
                {index === cursor && <span className="kbd">↵</span>}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
