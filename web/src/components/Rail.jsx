import { useRef, useState } from 'react'
import {
  IconBars,
  IconDatabase,
  IconFile,
  IconFilter,
  IconMoon,
  IconPanel,
  IconPlus,
  IconSun,
  IconUpload,
} from './Icons'
import { Chip, Spinner, toast } from './Primitives'

/**
 * Left rail: dataset source, live schema at a glance, and the filters that
 * every other view respects.
 */

function SchemaSummary({ profile }) {
  const groups = [
    { role: 'metric', label: 'Metrics', items: profile.metrics },
    { role: 'dimension', label: 'Dimensions', items: profile.dimensions },
    { role: 'date', label: 'Dates', items: profile.dates },
    { role: 'identifier', label: 'Identifiers', items: profile.identifiers },
  ].filter((group) => group.items.length)

  return (
    <div className="stack" style={{ gap: 12 }}>
      {groups.map((group) => (
        <div key={group.role}>
          <div className="tiny muted" style={{ marginBottom: 5 }}>
            {group.label} · {group.items.length}
          </div>
          <div className="chip-row">
            {group.items.slice(0, 6).map((name) => (
              <Chip key={name} tone={group.role} title={name}>
                {name}
              </Chip>
            ))}
            {group.items.length > 6 && (
              <span className="tiny muted">+{group.items.length - 6}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Rail({
  collapsed,
  onToggle,
  dataset,
  filterOptions,
  filters,
  onFiltersChange,
  onLoadSample,
  onUpload,
  onAddPdf,
  onReset,
  loading,
  theme,
  onToggleTheme,
  health,
}) {
  const fileInput = useRef(null)
  const pdfInput = useRef(null)
  const [dragging, setDragging] = useState(false)

  const setCategory = (column, values) => {
    const next = { ...filters.categories }
    if (values.length) next[column] = values
    else delete next[column]
    onFiltersChange({ ...filters, categories: next })
  }

  const handleFiles = (fileList) => {
    const file = fileList?.[0]
    if (!file) return
    const name = file.name.toLowerCase()
    if (name.endsWith('.pdf')) {
      onAddPdf(file)
    } else {
      onUpload(file)
    }
  }

  const activeFilterCount =
    Object.keys(filters.categories || {}).length + (filters.dateRange ? 1 : 0)

  return (
    <aside className="rail" data-collapsed={collapsed}>
      <div className="rail-head">
        <div className="mark">
          <IconBars size={16} style={{ color: '#fff' }} />
        </div>
        {!collapsed && (
          <>
            <div className="wordmark">
              Lumen
              <span>Analytics</span>
            </div>
            <button className="icon-btn" onClick={onToggle} aria-label="Collapse sidebar">
              <IconPanel size={16} />
            </button>
          </>
        )}
      </div>

      {collapsed ? (
        <div className="rail-body" style={{ padding: '12px 0', textAlign: 'center' }}>
          <button className="icon-btn" onClick={onToggle} aria-label="Expand sidebar">
            <IconPanel size={16} />
          </button>
        </div>
      ) : (
        <div className="rail-body">
          {/* ---- Source ---- */}
          <div className="rail-section">
            <div className="rail-label">Dataset</div>

            {dataset ? (
              <div className="card card-pad" style={{ padding: 13 }}>
                <div className="row" style={{ gap: 9, marginBottom: 7 }}>
                  <IconDatabase size={15} style={{ color: 'var(--accent)' }} />
                  <strong
                    style={{
                      fontSize: 13.5,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={dataset.filename}
                  >
                    {dataset.name}
                  </strong>
                </div>
                <div className="tiny muted">
                  {dataset.profile.rows.toLocaleString()} rows · {dataset.profile.columns} columns
                </div>
                {dataset.profile.primaryMetric && (
                  <div className="tiny muted" style={{ marginTop: 3 }}>
                    Headline metric: <strong>{dataset.profile.primaryMetric}</strong>
                  </div>
                )}
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ marginTop: 9, width: '100%' }}
                  onClick={onReset}
                >
                  <IconPlus size={13} /> Change dataset
                </button>
              </div>
            ) : (
              <div className="stack">
                <div
                  className="dropzone"
                  data-active={dragging}
                  onClick={() => fileInput.current?.click()}
                  onDragOver={(event) => {
                    event.preventDefault()
                    setDragging(true)
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault()
                    setDragging(false)
                    handleFiles(event.dataTransfer.files)
                  }}
                >
                  {loading ? (
                    <span className="row" style={{ justifyContent: 'center' }}>
                      <Spinner /> Processing…
                    </span>
                  ) : (
                    <>
                      <IconUpload size={18} />
                      <div style={{ marginTop: 6 }}>Drop a CSV or Excel file</div>
                      <div className="tiny">or click to browse</div>
                    </>
                  )}
                </div>
                <button
                  className="btn btn-block"
                  onClick={() => onLoadSample('superstore')}
                  disabled={loading}
                >
                  Try the Superstore example
                </button>
                {health?.samples?.includes('supermarket') && (
                  <button
                    className="btn btn-ghost btn-block btn-sm"
                    onClick={() => onLoadSample('supermarket')}
                    disabled={loading}
                  >
                    Or the supermarket dataset
                  </button>
                )}
              </div>
            )}

            <input
              ref={fileInput}
              type="file"
              accept=".csv,.tsv,.txt,.xlsx,.xls"
              hidden
              onChange={(event) => {
                handleFiles(event.target.files)
                event.target.value = ''
              }}
            />
          </div>

          {/* ---- Schema ---- */}
          {dataset && (
            <div className="rail-section">
              <div className="rail-label">Schema</div>
              <SchemaSummary profile={dataset.profile} />
            </div>
          )}

          {/* ---- Filters ---- */}
          {dataset && filterOptions && (
            <div className="rail-section">
              <div className="rail-label">
                <span className="row" style={{ gap: 6 }}>
                  <IconFilter size={12} /> Filters
                </span>
                {activeFilterCount > 0 && (
                  <button
                    className="btn btn-ghost btn-sm"
                    style={{ padding: '1px 7px', fontSize: 11 }}
                    onClick={() => onFiltersChange({ categories: {}, dateRange: null })}
                  >
                    Clear
                  </button>
                )}
              </div>

              <div className="stack" style={{ gap: 12 }}>
                {filterOptions.date && (
                  <div>
                    <label className="field-label">{filterOptions.date.column}</label>
                    <div className="row" style={{ gap: 6 }}>
                      <input
                        type="date"
                        className="field"
                        value={filters.dateRange?.[0] || filterOptions.date.min}
                        min={filterOptions.date.min}
                        max={filterOptions.date.max}
                        onChange={(event) =>
                          onFiltersChange({
                            ...filters,
                            dateRange: [
                              event.target.value,
                              filters.dateRange?.[1] || filterOptions.date.max,
                            ],
                          })
                        }
                      />
                      <input
                        type="date"
                        className="field"
                        value={filters.dateRange?.[1] || filterOptions.date.max}
                        min={filterOptions.date.min}
                        max={filterOptions.date.max}
                        onChange={(event) =>
                          onFiltersChange({
                            ...filters,
                            dateRange: [
                              filters.dateRange?.[0] || filterOptions.date.min,
                              event.target.value,
                            ],
                          })
                        }
                      />
                    </div>
                  </div>
                )}

                {filterOptions.categorical.map((option) => {
                  const selected = filters.categories?.[option.column] || []
                  return (
                    <div key={option.column}>
                      <label className="field-label">
                        {option.column}
                        {selected.length > 0 && (
                          <span className="muted"> · {selected.length} selected</span>
                        )}
                      </label>
                      <select
                        className="field"
                        multiple
                        size={Math.min(option.values.length, 4)}
                        value={selected}
                        onChange={(event) =>
                          setCategory(
                            option.column,
                            Array.from(event.target.selectedOptions).map((o) => o.value),
                          )
                        }
                      >
                        {option.values.map((value) => (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        ))}
                      </select>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ---- Extra context ---- */}
          {dataset && (
            <div className="rail-section">
              <div className="rail-label">Extra context</div>
              <button
                className="btn btn-ghost btn-block btn-sm"
                onClick={() => pdfInput.current?.click()}
              >
                <IconFile size={13} /> Add a PDF report
              </button>
              <div className="tiny muted" style={{ marginTop: 6, paddingLeft: 4 }}>
                Indexed into the same vector store the assistant retrieves from.
              </div>
              <input
                ref={pdfInput}
                type="file"
                accept=".pdf"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) onAddPdf(file)
                  event.target.value = ''
                }}
              />
            </div>
          )}
        </div>
      )}

      <div className="rail-foot">
        <button
          className="icon-btn"
          onClick={onToggleTheme}
          aria-label="Toggle colour scheme"
          title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}
        >
          {theme === 'dark' ? <IconSun size={15} /> : <IconMoon size={15} />}
        </button>
        {!collapsed && (
          <span
            className="tiny muted"
            style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}
            title={health?.model}
          >
            {health?.llmConfigured ? health.model : 'No API key — rule planner'}
          </span>
        )}
        {!collapsed && (
          <span
            className={`chip chip-${health?.llmConfigured ? 'ok' : 'warn'}`}
            title={health?.llmConfigured ? 'Groq connected' : 'Add GROQ_API_KEY to .env'}
          >
            {health?.llmConfigured ? 'live' : 'local'}
          </span>
        )}
      </div>
    </aside>
  )
}
