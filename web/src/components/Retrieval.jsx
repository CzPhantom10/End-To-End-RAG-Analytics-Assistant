import { useEffect, useState } from 'react'
import { api } from '../api'
import { Callout, Chip, Empty, Spinner } from './Primitives'
import { IconLayers, IconSearch } from './Icons'

/**
 * Makes the RAG layer inspectable. The vector store holds descriptions of the
 * dataset - never its rows - and this view lets you query it directly and see
 * exactly what the planner reads.
 */

export default function Retrieval({ dataset }) {
  const [docs, setDocs] = useState(null)
  const [query, setQuery] = useState('Which column measures profitability?')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    api
      .documents(dataset.id)
      .then((data) => !cancelled && setDocs(data))
      .catch((exc) => !cancelled && setError(exc.message))
    return () => {
      cancelled = true
    }
  }, [dataset.id])

  const search = async (event) => {
    event?.preventDefault()
    if (!query.trim()) return
    setSearching(true)
    setError(null)
    try {
      const data = await api.retrieve(dataset.id, query.trim(), 5)
      setResults(data.chunks)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setSearching(false)
    }
  }

  useEffect(() => {
    search()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.id])

  if (error && !docs) return <Callout tone="danger">{error}</Callout>
  if (!docs) {
    return (
      <div className="empty">
        <Spinner />
      </div>
    )
  }

  const store = docs.vectorStore
  const chroma = store.backend === 'chroma'

  return (
    <div className="pad">
      <h2 className="section-title">Retrieval layer</h2>
      <p className="section-sub">
        The vector store holds a data dictionary, one card per column, statistical summaries,
        business definitions and the cleaning log — never the raw rows. This is what the planner
        reads before choosing an analysis.
      </p>

      <div className="kpi-grid" style={{ marginBottom: 24 }}>
        <div className="kpi">
          <div className="kpi-label">Backend</div>
          <div className="kpi-value" style={{ fontSize: 19 }}>
            {chroma ? 'ChromaDB' : 'Keyword index'}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Embedding model</div>
          <div className="kpi-value" style={{ fontSize: 19 }}>
            {chroma ? 'MiniLM-L6-v2' : 'TF-IDF'}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Indexed chunks</div>
          <div className="kpi-value">{store.chunks}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Document kinds</div>
          <div className="kpi-value">{Object.keys(docs.counts).length}</div>
        </div>
      </div>

      {!chroma && store.error && (
        <div style={{ marginBottom: 20 }}>
          <Callout tone="warn">
            ChromaDB is unavailable, so retrieval fell back to a keyword index. Reason:{' '}
            <span className="mono">{store.error}</span>
          </Callout>
        </div>
      )}

      {/* ---- Live query ---- */}
      <section className="card" style={{ marginBottom: 24 }}>
        <div className="card-head">
          <span className="card-title row" style={{ gap: 8 }}>
            <IconSearch size={15} style={{ color: 'var(--accent)' }} />
            Query the vector store
          </span>
        </div>
        <div className="card-pad">
          <form className="row" onSubmit={search} style={{ marginBottom: 14 }}>
            <input
              className="field"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ask the index something…"
            />
            <button className="btn btn-primary" type="submit" disabled={searching}>
              {searching ? <Spinner /> : <IconSearch size={14} />} Search
            </button>
          </form>

          {results.length === 0 && !searching && <Empty>No chunks matched.</Empty>}

          <div className="stack" style={{ gap: 10 }}>
            {results.map((chunk, index) => (
              <div className="retrieved" key={index}>
                <div className="retrieved-head">
                  <span className="row" style={{ gap: 7 }}>
                    <Chip tone="accent">{chunk.label}</Chip>
                    <span className="tiny muted">#{index + 1}</span>
                  </span>
                  <span className="row tiny muted" style={{ gap: 7 }}>
                    <span className="meter">
                      <i style={{ width: `${Math.max(4, Math.min(1, chunk.score) * 100)}%` }} />
                    </span>
                    similarity {chunk.score.toFixed(3)}
                  </span>
                </div>
                <p className="retrieved-text">{chunk.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---- Corpus ---- */}
      <section className="card">
        <div className="card-head">
          <span className="card-title row" style={{ gap: 8 }}>
            <IconLayers size={15} style={{ color: 'var(--accent)' }} />
            Indexed corpus
          </span>
          <span className="chip-row">
            {Object.entries(docs.counts).map(([kind, count]) => (
              <Chip key={kind} tone="accent">
                {kind} · {count}
              </Chip>
            ))}
          </span>
        </div>
        <div className="card-pad">
          <div className="stack" style={{ gap: 8 }}>
            {docs.documents.map((document) => (
              <details className="fold" key={document.id}>
                <summary>
                  <Chip tone="accent">{document.kind}</Chip>
                  <span className="mono tiny muted" style={{ flex: 1 }}>
                    {document.column || document.id.split('::').slice(1).join('::')}
                  </span>
                  <span className="tiny muted">{document.text.length} chars</span>
                </summary>
                <div className="fold-body">
                  <p className="retrieved-text" style={{ margin: 0 }}>
                    {document.text}
                  </p>
                </div>
              </details>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
