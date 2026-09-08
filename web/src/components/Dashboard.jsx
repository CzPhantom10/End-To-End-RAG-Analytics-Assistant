import { useEffect, useState } from 'react'
import { api } from '../api'
import Chart from './Chart'
import { Callout, Chip, Empty, Markdown, Spinner } from './Primitives'
import { IconAlert, IconRefresh, IconSparkle } from './Icons'

export default function Dashboard({ dataset, filters, filterSpecs }) {
  const [overview, setOverview] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [summarising, setSummarising] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .overview(dataset.id, filterSpecs)
      .then((data) => !cancelled && setOverview(data))
      .catch((exc) => !cancelled && setError(exc.message))
      .finally(() => !cancelled && setLoading(false))
    // The summary is regenerated on demand, not on every filter tweak
    setSummary(null)
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.id, JSON.stringify(filterSpecs)])

  const generateSummary = () => {
    setSummarising(true)
    api
      .summary(dataset.id, filterSpecs)
      .then(setSummary)
      .catch((exc) => setError(exc.message))
      .finally(() => setSummarising(false))
  }

  if (loading) {
    return (
      <div className="empty">
        <Spinner /> <span style={{ marginLeft: 8 }}>Computing the dashboard…</span>
      </div>
    )
  }

  if (error) return <Callout tone="danger">{error}</Callout>
  if (!overview) return <Empty>Nothing to show.</Empty>

  return (
    <div className="pad">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <h2 className="section-title">Dataset overview</h2>
          <p className="section-sub" style={{ marginBottom: 0 }}>
            {overview.rowsInView.toLocaleString()} of {overview.rowsTotal.toLocaleString()} rows in
            view
            {overview.filtersApplied.length > 0 && ` · ${overview.filtersApplied.join(', ')}`}
          </p>
        </div>
      </div>

      {overview.filterWarnings?.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Callout tone="warn">{overview.filterWarnings.join(' ')}</Callout>
        </div>
      )}

      <div className="kpi-grid" style={{ marginBottom: 26 }}>
        {overview.kpis.map((kpi) => (
          <div className="kpi" key={kpi.label}>
            <div className="kpi-label">{kpi.label}</div>
            <div className="kpi-value">{kpi.display}</div>
          </div>
        ))}
      </div>

      {/* ---- Executive summary ---- */}
      <section className="card" style={{ marginBottom: 26 }}>
        <div className="card-head">
          <span className="card-title row" style={{ gap: 8 }}>
            <IconSparkle size={15} style={{ color: 'var(--accent)' }} />
            Executive summary
          </span>
          <button
            className="btn btn-sm"
            onClick={generateSummary}
            disabled={summarising}
          >
            {summarising ? <Spinner /> : <IconRefresh size={13} />}
            {summary ? 'Regenerate' : 'Generate'}
          </button>
        </div>
        <div className="card-pad">
          {!summary && !summarising && (
            <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>
              Computes the headline facts from the filtered data, then has the model turn them
              into a short brief. It can only cite figures that were computed first.
            </p>
          )}
          {summarising && (
            <p className="row muted" style={{ margin: 0 }}>
              <Spinner /> Computing facts and writing the brief…
            </p>
          )}
          {summary && (
            <>
              <Markdown text={summary.summary} />
              <details className="fold" style={{ marginTop: 14 }}>
                <summary>The {summary.facts.length} computed facts it was given</summary>
                <div className="fold-body">
                  <ul className="tiny muted" style={{ margin: 0, paddingLeft: 18 }}>
                    {summary.facts.map((fact, index) => (
                      <li key={index} style={{ marginBottom: 4 }}>
                        {fact}
                      </li>
                    ))}
                  </ul>
                </div>
              </details>
            </>
          )}
        </div>
      </section>

      {/* ---- Anomalies ---- */}
      {overview.anomalies.length > 0 && (
        <section className="card" style={{ marginBottom: 26 }}>
          <div className="card-head">
            <span className="card-title row" style={{ gap: 8 }}>
              <IconAlert size={15} style={{ color: 'var(--warn)' }} />
              Anomalous periods
            </span>
            <span className="tiny muted">
              Monthly {overview.anomalyMetric} beyond 2 standard deviations
            </span>
          </div>
          <div className="card-pad">
            <div className="chip-row">
              {overview.anomalies.map((row) => (
                <Chip key={row.period} tone={row.z_score > 0 ? 'ok' : 'danger'}>
                  {row.period} · {row.direction} · z={row.z_score}
                </Chip>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* ---- Charts ---- */}
      <h3 className="section-title">Automatic charts</h3>
      <p className="section-sub">
        Chosen from the column roles the profiler detected — no configuration required.
      </p>
      <div className="grid grid-2">
        {overview.charts.map((chart) => (
          <div className="card" key={chart.key}>
            <Chart figure={chart.figure} height={330} />
          </div>
        ))}
      </div>
      {overview.charts.length === 0 && <Empty>No chartable columns in this dataset.</Empty>}
    </div>
  )
}
