import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import CommandPalette from './components/CommandPalette'
import Conversation from './components/Conversation'
import Dashboard from './components/Dashboard'
import EvidenceDrawer from './components/EvidenceDrawer'
import Explorer from './components/Explorer'
import Rail from './components/Rail'
import Retrieval from './components/Retrieval'
import { Callout, ToastHost, toast } from './components/Primitives'
import {
  IconGauge,
  IconLayers,
  IconMessage,
  IconPanel,
  IconSearch,
  IconTable,
} from './components/Icons'

const VIEWS = [
  { key: 'chat', label: 'Assistant', Icon: IconMessage },
  { key: 'dashboard', label: 'Dashboard', Icon: IconGauge },
  { key: 'explorer', label: 'Explorer', Icon: IconTable },
  { key: 'retrieval', label: 'Retrieval', Icon: IconLayers },
]

const EMPTY_FILTERS = { categories: {}, dateRange: null }

/** UI filter state -> the filter specs the analysis engine understands. */
function toFilterSpecs(filters, filterOptions) {
  const specs = []
  for (const [column, values] of Object.entries(filters.categories || {})) {
    if (values?.length) specs.push({ column, op: 'in', value: values })
  }
  if (filters.dateRange && filterOptions?.date) {
    const [start, end] = filters.dateRange
    if (start !== filterOptions.date.min || end !== filterOptions.date.max) {
      specs.push({ column: filterOptions.date.column, op: 'between', value: [start, end] })
    }
  }
  return specs
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [dataset, setDataset] = useState(null)
  const [filterOptions, setFilterOptions] = useState(null)
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [view, setView] = useState('chat')
  const [turns, setTurns] = useState([])
  const [busy, setBusy] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [evidenceTurn, setEvidenceTurn] = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [fatal, setFatal] = useState(null)
  const [theme, setTheme] = useState(
    () => localStorage.getItem('lumen-theme') || 'light',
  )

  const turnId = useRef(0)

  /* ---- theme ---- */
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('lumen-theme', theme)
  }, [theme])

  /* ---- health ---- */
  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((exc) => setFatal(exc.message))
  }, [])

  /* ---- keyboard ---- */
  useEffect(() => {
    const onKey = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
      if ((event.metaKey || event.ctrlKey) && event.key === '\\') {
        event.preventDefault()
        setCollapsed((value) => !value)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const filterSpecs = useMemo(
    () => toFilterSpecs(filters, filterOptions),
    [filters, filterOptions],
  )

  const adoptDataset = useCallback(async (payload) => {
    setDataset(payload)
    setTurns([])
    setFilters(EMPTY_FILTERS)
    setView('chat')
    try {
      setFilterOptions(await api.filters(payload.id))
    } catch {
      setFilterOptions(null)
    }
    toast(`${payload.name} ready · ${payload.rows.toLocaleString()} rows`)
  }, [])

  const loadSample = async (name) => {
    setLoading(true)
    try {
      adoptDataset(await api.loadSample(name))
    } catch (exc) {
      toast(exc.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  const upload = async (file) => {
    setLoading(true)
    try {
      let sheet
      if (/\.xlsx?$/i.test(file.name)) {
        const { sheets } = await api.sheets(file)
        if (sheets.length > 1) {
          const picked = window.prompt(
            `This workbook has several sheets:\n\n${sheets.join('\n')}\n\nWhich one?`,
            sheets[0],
          )
          if (picked === null) {
            setLoading(false)
            return
          }
          sheet = picked
        }
      }
      adoptDataset(await api.upload(file, sheet))
    } catch (exc) {
      toast(exc.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  const addPdf = async (file) => {
    if (!dataset) return toast('Load a dataset first', 'error')
    toast(`Indexing ${file.name}…`)
    try {
      const result = await api.addPdf(dataset.id, file)
      if (result.chunksAdded) {
        toast(`Indexed ${result.chunksAdded} chunks from ${file.name}`)
      } else {
        toast('No extractable text in that PDF', 'error')
      }
    } catch (exc) {
      toast(exc.message, 'error')
    }
  }

  const reset = () => {
    setDataset(null)
    setTurns([])
    setFilterOptions(null)
    setFilters(EMPTY_FILTERS)
    setView('chat')
  }

  const ask = useCallback(
    async (question) => {
      if (!dataset || busy) return
      setView('chat')
      setPendingQuestion(question)
      setBusy(true)
      const started = performance.now()

      const history = turns.slice(-3).flatMap((turn) => [
        { role: 'user', content: turn.question },
        { role: 'assistant', content: turn.narrative || '' },
      ])

      try {
        const response = await api.ask(dataset.id, {
          question,
          history,
          filters: filterSpecs,
        })
        setTurns((current) => [
          ...current,
          {
            id: ++turnId.current,
            question,
            elapsed: (performance.now() - started) / 1000,
            ...response,
          },
        ])
      } catch (exc) {
        setTurns((current) => [
          ...current,
          { id: ++turnId.current, question, error: exc.message },
        ])
      } finally {
        setBusy(false)
        setPendingQuestion('')
      }
    },
    [dataset, busy, turns, filterSpecs],
  )

  /* ---- render ---- */

  if (fatal) {
    return (
      <div style={{ maxWidth: 560, margin: '18vh auto', padding: 24 }}>
        <Callout tone="danger">
          <strong>Cannot reach the backend.</strong>
          <div style={{ marginTop: 6 }}>{fatal}</div>
          <div style={{ marginTop: 10 }} className="tiny">
            Start it with <span className="mono">python -m server</span> from the project folder.
          </div>
        </Callout>
      </div>
    )
  }

  const filterHint = filterSpecs.length
    ? `${filterSpecs.length} filter${filterSpecs.length > 1 ? 's' : ''} applied to every answer`
    : dataset
      ? `Computed over all ${dataset.profile.rows.toLocaleString()} rows`
      : ''

  return (
    <div className="shell">
      <Rail
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
        dataset={dataset}
        filterOptions={filterOptions}
        filters={filters}
        onFiltersChange={setFilters}
        onLoadSample={loadSample}
        onUpload={upload}
        onAddPdf={addPdf}
        onReset={reset}
        loading={loading}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
        health={health}
      />

      <main className="main">
        <header className="topbar">
          {collapsed && (
            <button
              className="icon-btn"
              onClick={() => setCollapsed(false)}
              aria-label="Open sidebar"
            >
              <IconPanel size={16} />
            </button>
          )}

          <div className="topbar-title">
            {dataset ? (
              <>
                {VIEWS.find((v) => v.key === view)?.label}
                <small>{dataset.name}</small>
              </>
            ) : (
              <>
                Lumen<small>natural-language analytics</small>
              </>
            )}
          </div>

          <div className="topbar-spacer" />

          {dataset && (
            <div className="segmented" role="tablist">
              {VIEWS.map((item) => (
                <button
                  key={item.key}
                  role="tab"
                  aria-selected={view === item.key}
                  onClick={() => setView(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}

          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setPaletteOpen(true)}
            title="Command palette"
          >
            <IconSearch size={13} />
            <span className="kbd">⌘K</span>
          </button>
        </header>

        {!dataset ? (
          <div className="scroll-area">
            <div className="welcome">
              <h1>Ask your data a question.</h1>
              <p>
                Upload a spreadsheet and ask in plain English. The model plans the analysis,
                pandas computes it, and every answer arrives with the evidence that produced it.
              </p>
              <div className="suggestions" style={{ gridTemplateColumns: '1fr' }}>
                <div className="card card-pad" style={{ textAlign: 'left' }}>
                  <ol
                    style={{
                      margin: 0,
                      paddingLeft: 20,
                      fontSize: 13.5,
                      lineHeight: 1.85,
                      color: 'var(--ink-soft)',
                    }}
                  >
                    <li>
                      <strong>Ingest</strong> — the file is parsed, validated and cleaned, and
                      every change is logged.
                    </li>
                    <li>
                      <strong>Profile</strong> — each column becomes a metric, dimension, date,
                      identifier or text.
                    </li>
                    <li>
                      <strong>Index</strong> — a data dictionary, column cards and business
                      definitions go into ChromaDB.
                    </li>
                    <li>
                      <strong>Retrieve &amp; plan</strong> — your question pulls the relevant
                      context; the model returns a JSON plan.
                    </li>
                    <li>
                      <strong>Compute</strong> — pandas executes that plan. Every number comes
                      from this step.
                    </li>
                    <li>
                      <strong>Explain</strong> — the model writes the answer and the evidence
                      trail shows its working.
                    </li>
                  </ol>
                </div>
              </div>
              <p className="tiny muted" style={{ marginTop: 22 }}>
                Use the sidebar to upload a file, or load the Superstore example to see it
                working.
              </p>
            </div>
          </div>
        ) : view === 'chat' ? (
          <Conversation
            dataset={dataset}
            turns={turns}
            busy={busy}
            pendingQuestion={pendingQuestion}
            onAsk={ask}
            onEvidence={setEvidenceTurn}
            filterHint={filterHint}
          />
        ) : (
          <div className="scroll-area">
            {view === 'dashboard' && (
              <Dashboard dataset={dataset} filters={filters} filterSpecs={filterSpecs} />
            )}
            {view === 'explorer' && <Explorer dataset={dataset} filterSpecs={filterSpecs} />}
            {view === 'retrieval' && <Retrieval dataset={dataset} />}
          </div>
        )}
      </main>

      {evidenceTurn && (
        <EvidenceDrawer turn={evidenceTurn} onClose={() => setEvidenceTurn(null)} />
      )}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        dataset={dataset}
        onNavigate={setView}
        onAsk={ask}
      />

      <ToastHost />
    </div>
  )
}
