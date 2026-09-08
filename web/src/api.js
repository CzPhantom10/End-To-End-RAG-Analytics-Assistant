/**
 * Thin wrapper over the FastAPI backend.
 * Every call funnels through request() so error handling is uniform.
 */

const BASE = '/api'

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, { method = 'GET', body, form, signal } = {}) {
  const options = { method, signal, headers: {} }

  if (form) {
    options.body = form // browser sets the multipart boundary
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(`${BASE}${path}`, options)
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError('Cannot reach the analytics server. Is it still running?', 0)
  }

  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = { detail: text }
    }
  }

  if (!response.ok) {
    const detail =
      (payload && (payload.detail || payload.message)) || `Request failed (${response.status})`
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), response.status)
  }
  return payload
}

export const api = {
  health: () => request('/health'),
  models: () => request('/models'),

  loadSample: (name) => request(`/datasets/sample/${name}`, { method: 'POST' }),

  upload: (file, sheet) => {
    const form = new FormData()
    form.append('file', file)
    const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : ''
    return request(`/datasets/upload${query}`, { method: 'POST', form })
  },

  sheets: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/datasets/sheets', { method: 'POST', form })
  },

  dataset: (id) => request(`/datasets/${id}`),
  removeDataset: (id) => request(`/datasets/${id}`, { method: 'DELETE' }),

  addPdf: (id, file) => {
    const form = new FormData()
    form.append('file', file)
    return request(`/datasets/${id}/context/pdf`, { method: 'POST', form })
  },

  filters: (id) => request(`/datasets/${id}/filters`),
  rows: (id, body) => request(`/datasets/${id}/rows`, { method: 'POST', body }),
  exportCsv: (id, filters) =>
    request(`/datasets/${id}/export`, { method: 'POST', body: { filters } }),

  overview: (id, filters) =>
    request(`/datasets/${id}/overview`, { method: 'POST', body: { filters } }),
  summary: (id, filters) =>
    request(`/datasets/${id}/summary`, { method: 'POST', body: { filters } }),

  ask: (id, body, signal) => request(`/datasets/${id}/ask`, { method: 'POST', body, signal }),

  retrieve: (id, query, limit = 5) =>
    request(`/datasets/${id}/retrieve`, { method: 'POST', body: { query, limit } }),
  documents: (id) => request(`/datasets/${id}/documents`),
}

export { ApiError }
