import { useEffect, useState } from 'react'
import { api } from '../api'
import {
  Callout,
  Chip,
  DataTable,
  Empty,
  RoleChip,
  Spinner,
  downloadCsv,
  toast,
} from './Primitives'
import { IconDownload } from './Icons'

const VIEWS = [
  { key: 'clean', label: 'Cleaned data' },
  { key: 'raw', label: 'Raw upload' },
  { key: 'schema', label: 'Column profile' },
  { key: 'quality', label: 'Data quality' },
]

function ColumnProfileTable({ profile }) {
  return (
    <div className="table-wrap" style={{ maxHeight: 620 }}>
      <table className="data">
        <thead>
          <tr>
            <th>Column</th>
            <th>Role</th>
            <th>Type</th>
            <th className="num">Unique</th>
            <th className="num">Missing</th>
            <th className="num">Min</th>
            <th className="num">Max</th>
            <th className="num">Mean</th>
            <th>Example</th>
          </tr>
        </thead>
        <tbody>
          {profile.columnProfiles.map((column) => (
            <tr key={column.name}>
              <td style={{ fontWeight: 550 }}>{column.name}</td>
              <td>
                <RoleChip role={column.role} />
              </td>
              <td className="mono muted">{column.dtype}</td>
              <td className="num">{column.unique.toLocaleString()}</td>
              <td className="num">
                {column.missingPct > 0 ? (
                  <span style={{ color: 'var(--danger)' }}>{column.missingPct}%</span>
                ) : (
                  '—'
                )}
              </td>
              <td className="num">{column.min?.toLocaleString?.() ?? '—'}</td>
              <td className="num">{column.max?.toLocaleString?.() ?? '—'}</td>
              <td className="num">
                {column.mean != null
                  ? column.mean.toLocaleString(undefined, { maximumFractionDigits: 2 })
                  : '—'}
              </td>
              <td className="muted" title={column.sampleValues.join(', ')}>
                {column.sampleValues[0] ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Explorer({ dataset, filterSpecs }) {
  const [view, setView] = useState('clean')
  const [table, setTable] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (view !== 'clean' && view !== 'raw') return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .rows(dataset.id, {
        source: view,
        limit: 200,
        offset: 0,
        filters: view === 'clean' ? filterSpecs : undefined,
      })
      .then((data) => !cancelled && setTable(data))
      .catch((exc) => !cancelled && setError(exc.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.id, view, JSON.stringify(filterSpecs)])

  const exportCsv = async () => {
    try {
      const data = await api.exportCsv(dataset.id, filterSpecs)
      downloadCsv(data.filename, data.csv)
      toast('Filtered data downloaded')
    } catch (exc) {
      toast(exc.message, 'error')
    }
  }

  const profile = dataset.profile
  const cleaning = dataset.cleaning
  const missingColumns = profile.columnProfiles.filter((c) => c.missing > 0)

  return (
    <div className="pad">
      <h2 className="section-title">Data explorer</h2>
      <p className="section-sub">
        Inspect what was uploaded, what cleaning changed, and how each column was classified.
      </p>

      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
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
        {view === 'clean' && (
          <button className="btn btn-sm" onClick={exportCsv}>
            <IconDownload size={13} /> Export CSV
          </button>
        )}
      </div>

      {error && <Callout tone="danger">{error}</Callout>}

      {(view === 'clean' || view === 'raw') && (
        <div className="card">
          {loading ? (
            <div className="empty">
              <Spinner />
            </div>
          ) : (
            <>
              <div className="card-head">
                <span className="card-title">
                  {view === 'raw' ? 'Exactly as uploaded' : 'After cleaning and filters'}
                </span>
                <span className="tiny muted">
                  {(table?.total ?? 0).toLocaleString()} rows · {table?.columns?.length ?? 0}{' '}
                  columns
                </span>
              </div>
              <DataTable table={table} />
            </>
          )}
        </div>
      )}

      {view === 'schema' && (
        <div className="card">
          <div className="card-head">
            <span className="card-title">Column profile</span>
            <span className="tiny muted">
              Roles drive the whole system: metrics get aggregated, dimensions grouped by, dates
              drive trends, identifiers are never summed.
            </span>
          </div>
          <ColumnProfileTable profile={profile} />
        </div>
      )}

      {view === 'quality' && (
        <div className="grid grid-2">
          <div className="card">
            <div className="card-head">
              <span className="card-title">What cleaning changed</span>
            </div>
            <div className="card-pad">
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13.5 }}>
                {cleaning.changes.map((change, index) => (
                  <li key={index} style={{ marginBottom: 5 }}>
                    {change}
                  </li>
                ))}
              </ul>
              <div className="row wrap" style={{ marginTop: 14, gap: 6 }}>
                <Chip tone="accent">
                  {cleaning.original_rows.toLocaleString()} → {cleaning.final_rows.toLocaleString()}{' '}
                  rows
                </Chip>
                <Chip tone="accent">
                  {cleaning.original_columns} → {cleaning.final_columns} columns
                </Chip>
                {cleaning.duplicates_removed > 0 && (
                  <Chip tone="warn">{cleaning.duplicates_removed} duplicates removed</Chip>
                )}
              </div>
              {cleaning.warnings.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  {cleaning.warnings.map((warning, index) => (
                    <Callout tone="warn" key={index}>
                      {warning}
                    </Callout>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <span className="card-title">Missing values</span>
              <span className="tiny muted">{profile.missingPct}% of all cells</span>
            </div>
            <div className="card-pad">
              {missingColumns.length === 0 ? (
                <Empty>No missing values anywhere in this dataset.</Empty>
              ) : (
                <div className="stack" style={{ gap: 9 }}>
                  {missingColumns
                    .sort((a, b) => b.missingPct - a.missingPct)
                    .map((column) => (
                      <div key={column.name}>
                        <div
                          className="row tiny"
                          style={{ justifyContent: 'space-between', marginBottom: 3 }}
                        >
                          <span>{column.name}</span>
                          <span className="muted">
                            {column.missing.toLocaleString()} · {column.missingPct}%
                          </span>
                        </div>
                        <div
                          style={{
                            height: 5,
                            background: 'var(--bg-inset)',
                            borderRadius: 99,
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              width: `${Math.min(100, column.missingPct)}%`,
                              height: '100%',
                              background: 'var(--danger)',
                              borderRadius: 99,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
