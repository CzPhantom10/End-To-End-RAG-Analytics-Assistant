import { useEffect } from 'react'
import { IconClose, IconShield } from './Icons'
import { Chip } from './Primitives'

/**
 * The trust surface. Instead of burying provenance in an inline accordion,
 * evidence gets its own slide-over so the answer stays readable and the
 * audit trail is one click away at full width.
 */

function Row({ label, children }) {
  return (
    <div className="evidence-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

export default function EvidenceDrawer({ turn, onClose }) {
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  if (!turn) return null

  const evidence = turn.evidence || {}
  const plan = turn.result?.plan || {}
  const context = turn.context || []
  const columns = (evidence.columns_used || []).filter(Boolean)
  const filters = evidence.filters || ['none']
  const notes = evidence.notes || turn.result?.notes || []

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Evidence for this answer">
        <header className="drawer-head">
          <div className="row">
            <IconShield size={17} />
            <strong style={{ fontSize: 14 }}>Evidence</strong>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close evidence">
            <IconClose />
          </button>
        </header>

        <div className="drawer-body">
          <p className="tiny muted" style={{ marginTop: 0, marginBottom: 18 }}>
            Every figure in this answer came from the operation below, executed with pandas on
            your data. The model chose the operation and wrote the prose; it did not produce the
            numbers.
          </p>

          <section className="evidence-group">
            <h4>Computation</h4>
            <dl style={{ margin: 0 }}>
              <Row label="Dataset">{evidence.dataset || '—'}</Row>
              <Row label="Operation">{evidence.operation || '—'}</Row>
              <Row label="Plan">{evidence.planDescription || evidence.plan_description || '—'}</Row>
              <Row label="Columns">
                {columns.length ? (
                  <span className="chip-row">
                    {columns.map((column) => (
                      <Chip key={column} tone="accent">
                        {column}
                      </Chip>
                    ))}
                  </span>
                ) : (
                  '—'
                )}
              </Row>
              <Row label="Filters">
                {Array.isArray(filters) ? filters.join(', ') : String(filters)}
              </Row>
              <Row label="Date range">{evidence.date_range || 'not applicable'}</Row>
              <Row label="Rows used">
                {(evidence.rows_after_filters ?? 0).toLocaleString()} of{' '}
                {(evidence.rows_in_dataset ?? 0).toLocaleString()}
              </Row>
            </dl>
          </section>

          <section className="evidence-group">
            <h4>Analysis plan (JSON)</h4>
            <pre
              className="mono"
              style={{
                background: 'var(--bg-sunken)',
                border: '1px solid var(--line-soft)',
                borderRadius: 8,
                padding: 12,
                overflowX: 'auto',
                margin: 0,
                fontSize: 11.5,
                lineHeight: 1.55,
              }}
            >
              {JSON.stringify(
                Object.fromEntries(
                  Object.entries(plan).filter(
                    ([, value]) =>
                      value !== null &&
                      value !== '' &&
                      !(Array.isArray(value) && value.length === 0),
                  ),
                ),
                null,
                2,
              )}
            </pre>
            <p className="tiny muted" style={{ marginBottom: 0 }}>
              This plan was validated against the real schema before it ran. No model-generated
              code is executed.
            </p>
          </section>

          {notes.length > 0 && (
            <section className="evidence-group">
              <h4>Notes</h4>
              <ul className="tiny" style={{ margin: 0, paddingLeft: 18, color: 'var(--warn)' }}>
                {notes.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul>
            </section>
          )}

          <section className="evidence-group">
            <h4>Retrieved context · {context.length} chunks</h4>
            {context.length === 0 && <p className="tiny muted">Nothing was retrieved.</p>}
            {context.map((chunk, index) => (
              <div className="retrieved" key={index}>
                <div className="retrieved-head">
                  <Chip tone="accent">{chunk.label}</Chip>
                  <span className="row tiny muted" style={{ gap: 6 }}>
                    <span className="meter" title={`similarity ${chunk.score}`}>
                      <i style={{ width: `${Math.max(4, Math.min(1, chunk.score) * 100)}%` }} />
                    </span>
                    {chunk.score.toFixed(3)}
                  </span>
                </div>
                <p className="retrieved-text">
                  {chunk.text.length > 520 ? `${chunk.text.slice(0, 520)}…` : chunk.text}
                </p>
              </div>
            ))}
          </section>

          <section className="evidence-group" style={{ marginBottom: 0 }}>
            <h4>Provenance</h4>
            <dl style={{ margin: 0 }}>
              <Row label="Planner">
                {turn.planner === 'llm' ? 'Language model' : 'Rule-based fallback'}
              </Row>
              <Row label="Narrator">
                {turn.narrator === 'llm' ? 'Language model' : 'Deterministic template'}
              </Row>
              <Row label="Model">{turn.model || '—'}</Row>
              <Row label="Retrieval">{context[0]?.source === 'chroma' ? 'ChromaDB' : 'Keyword index'}</Row>
            </dl>
          </section>
        </div>
      </aside>
    </>
  )
}
