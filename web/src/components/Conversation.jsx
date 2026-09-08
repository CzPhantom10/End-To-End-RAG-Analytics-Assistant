import { useEffect, useRef, useState } from 'react'
import Chart from './Chart'
import Pipeline from './Pipeline'
import {
  Callout,
  Chip,
  DataTable,
  Fold,
  Markdown,
  downloadCsv,
  tableToCsv,
  toast,
} from './Primitives'
import {
  IconBars,
  IconCopy,
  IconDownload,
  IconRefresh,
  IconSend,
  IconShield,
  IconSparkle,
} from './Icons'

/* ------------------------------------------------------------------ */

function Answer({ turn, onEvidence, onReask }) {
  const result = turn.result
  const table = result?.table

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(turn.narrative || '')
      toast('Answer copied')
    } catch {
      toast('Could not copy to clipboard', 'error')
    }
  }

  const download = () => {
    if (!table) return
    downloadCsv('analysis-result.csv', tableToCsv(table))
    toast('Result downloaded')
  }

  return (
    <div className="answer">
      <div className="avatar">
        <IconBars size={15} style={{ color: '#fff' }} />
      </div>

      <div className="answer-body">
        {turn.error ? (
          <Callout tone="danger">{turn.error}</Callout>
        ) : (
          <>
            <Markdown text={turn.narrative} />

            {/* A single headline number reads better as a figure than a chart */}
            {result?.chartType === 'kpi' && result.scalarFormatted && (
              <div className="kpi" style={{ maxWidth: 260 }}>
                <div className="kpi-label">{result.valueColumn || 'Result'}</div>
                <div className="kpi-value">{result.scalarFormatted}</div>
              </div>
            )}

            {turn.figure && (
              <div className="card">
                <Chart figure={turn.figure} height={360} />
              </div>
            )}

            {table && table.rows.length > 0 && result?.chartType !== 'kpi' && (
              <Fold
                label={`Result data · ${table.total.toLocaleString()} ${
                  table.total === 1 ? 'row' : 'rows'
                }`}
                defaultOpen={table.total <= 8}
              >
                <DataTable table={table} />
              </Fold>
            )}
          </>
        )}

        <div className="turn-actions">
          <button className="btn btn-ghost btn-sm" onClick={onEvidence} disabled={!!turn.error}>
            <IconShield size={13} /> Evidence
          </button>
          <button className="btn btn-ghost btn-sm" onClick={copy} disabled={!turn.narrative}>
            <IconCopy size={13} /> Copy
          </button>
          {table && table.rows.length > 0 && (
            <button className="btn btn-ghost btn-sm" onClick={download}>
              <IconDownload size={13} /> CSV
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={onReask}>
            <IconRefresh size={13} /> Ask again
          </button>
        </div>

        {!turn.error && (
          <div className="meta-line">
            <Chip tone={turn.planner === 'llm' ? 'ok' : 'warn'}>
              {turn.planner === 'llm' ? 'LLM plan' : 'Rule plan'}
            </Chip>
            <span>pandas computed</span>
            {turn.model && <span className="dot-sep">{turn.model}</span>}
            {turn.elapsed != null && <span className="dot-sep">{turn.elapsed.toFixed(1)}s</span>}
          </div>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */

function Welcome({ dataset, onPick }) {
  const profile = dataset.profile
  const suggestions = (profile.suggestedQuestions || []).slice(0, 6)

  return (
    <div className="welcome">
      <h1>What would you like to know?</h1>
      <p>
        Ask about <strong>{dataset.name}</strong> in plain English. Answers are computed with
        pandas over all {profile.rows.toLocaleString()} rows — never guessed by the model.
      </p>
      <div className="suggestions">
        {suggestions.map((question) => (
          <button key={question} className="suggestion" onClick={() => onPick(question)}>
            <IconSparkle size={15} />
            <span>{question}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */

function Composer({ onSend, busy, hint }) {
  const [value, setValue] = useState('')
  const field = useRef(null)

  const resize = () => {
    const node = field.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, 190)}px`
  }

  useEffect(resize, [value])

  const submit = () => {
    const question = value.trim()
    if (!question || busy) return
    onSend(question)
    setValue('')
  }

  return (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
          ref={field}
          rows={1}
          value={value}
          placeholder="Ask about your data…"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          disabled={busy}
        />
        <div className="composer-bar">
          <span className="composer-hint">{hint}</span>
          <span className="tiny muted">
            <span className="kbd">Enter</span> to send
          </span>
          <button
            className="send"
            onClick={submit}
            disabled={busy || !value.trim()}
            aria-label="Send question"
          >
            <IconSend size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */

export default function Conversation({
  dataset,
  turns,
  busy,
  onAsk,
  onEvidence,
  pendingQuestion,
  filterHint,
}) {
  const bottom = useRef(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, busy])

  return (
    <>
      <div className="scroll-area">
        {turns.length === 0 && !busy ? (
          <Welcome dataset={dataset} onPick={onAsk} />
        ) : (
          <div className="thread">
            {turns.map((turn, index) => (
              <div className="turn" key={turn.id}>
                <div className="turn-user">
                  <div className="bubble-user">{turn.question}</div>
                </div>
                <Answer
                  turn={turn}
                  onEvidence={() => onEvidence(turn)}
                  onReask={() => onAsk(turn.question)}
                />
                {index < turns.length - 1 && <span />}
              </div>
            ))}

            {busy && (
              <div className="turn">
                <div className="turn-user">
                  <div className="bubble-user">{pendingQuestion}</div>
                </div>
                <div className="answer">
                  <div className="avatar">
                    <IconBars size={15} style={{ color: '#fff' }} />
                  </div>
                  <div className="answer-body">
                    <Pipeline />
                  </div>
                </div>
              </div>
            )}
            <div ref={bottom} />
          </div>
        )}
      </div>

      <Composer onSend={onAsk} busy={busy} hint={filterHint} />
    </>
  )
}
