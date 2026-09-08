import { useEffect, useMemo, useRef } from 'react'

/* Plotly is ~4.5 MB, so it is fetched on demand the first time a chart renders
   rather than blocking the initial app shell. The promise is cached. */
let plotlyPromise = null
const loadPlotly = () => {
  if (!plotlyPromise) plotlyPromise = import('plotly.js-dist-min').then((m) => m.default || m)
  return plotlyPromise
}

/**
 * Renders a Plotly figure produced by the Python backend.
 *
 * The backend decides the chart type from the analysis that was actually run,
 * so this component only re-themes the figure to match the current light/dark
 * palette and keeps it responsive.
 */

function readTokens() {
  const styles = getComputedStyle(document.documentElement)
  const get = (name, fallback) => (styles.getPropertyValue(name) || fallback).trim()
  return {
    ink: get('--ink', '#1b1d1c'),
    inkFaint: get('--ink-faint', '#7d847f'),
    line: get('--line', '#ddd8cd'),
    lineSoft: get('--line-soft', '#e9e5db'),
    surface: get('--bg-raised', '#fffefb'),
  }
}

export default function Chart({ figure, height = 340, onReady }) {
  const holder = useRef(null)

  // Re-render whenever the figure or the theme changes
  const theme = useMemo(
    () => document.documentElement.getAttribute('data-theme') || 'light',
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [figure],
  )

  useEffect(() => {
    const node = holder.current
    if (!node || !figure) return

    let cancelled = false
    let plotly = null

    const draw = () => {
      if (cancelled || !holder.current || !plotly) return
      const t = readTokens()

      const axis = {
        gridcolor: t.lineSoft,
        zerolinecolor: t.line,
        linecolor: t.line,
        tickfont: { color: t.inkFaint, size: 11.5 },
        titlefont: { color: t.inkFaint, size: 12 },
        automargin: true,
      }

      const layout = {
        ...figure.layout,
        height,
        // Both dimensions are explicit so the plot exactly fills its card
        width: holder.current.clientWidth || undefined,
        autosize: false,
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: {
          family: 'Inter, ui-sans-serif, system-ui, sans-serif',
          size: 12.5,
          color: t.ink,
        },
        margin: { l: 8, r: 14, t: figure.layout?.title?.text ? 40 : 12, b: 8 },
        title: figure.layout?.title
          ? {
              ...figure.layout.title,
              font: { size: 13.5, color: t.ink, weight: 600 },
              x: 0,
              xanchor: 'left',
              pad: { l: 6, t: 4 },
            }
          : undefined,
        xaxis: { ...(figure.layout?.xaxis || {}), ...axis },
        yaxis: { ...(figure.layout?.yaxis || {}), ...axis },
        legend: {
          ...(figure.layout?.legend || {}),
          bgcolor: 'rgba(0,0,0,0)',
          font: { color: t.inkFaint, size: 11.5 },
          orientation: 'h',
          y: -0.16,
          x: 0,
        },
        hoverlabel: {
          bgcolor: t.surface,
          bordercolor: t.line,
          font: { color: t.ink, size: 12.5, family: 'Inter, sans-serif' },
        },
      }

      plotly
        .react(node, figure.data, layout, {
          displayModeBar: false,
          // Sizing is handled by the ResizeObserver above
          responsive: false,
          scrollZoom: false,
        })
        .then(() => {
          if (!cancelled && onReady) onReady()
        })
    }

    loadPlotly().then((module) => {
      if (cancelled) return
      plotly = module
      draw()
    })

    // Keep the chart sized to its container. Width only - the height is fixed
    // by the wrapper, so re-reading it here cannot collapse the plot.
    let lastWidth = 0
    const observer = new ResizeObserver(() => {
      if (!holder.current || !plotly) return
      const width = holder.current.clientWidth
      if (width && width !== lastWidth) {
        lastWidth = width
        plotly.relayout(holder.current, { width, height })
      }
    })
    observer.observe(node)

    // Redraw when the colour scheme flips
    const themeWatcher = new MutationObserver(draw)
    themeWatcher.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })

    return () => {
      cancelled = true
      observer.disconnect()
      themeWatcher.disconnect()
      if (node && plotly) plotly.purge(node)
    }
  }, [figure, height, theme, onReady])

  if (!figure) return null
  // The height must be explicit: Plotly's responsive resize reads the
  // container box, and an auto height would collapse to nothing.
  return <div ref={holder} className="chart-frame" style={{ width: '100%', height }} />
}
