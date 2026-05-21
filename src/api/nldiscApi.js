const API_BASE_URL = (import.meta.env.VITE_NLDISC_API_BASE_URL || 'http://127.0.0.1:5000/api').replace(/\/+$/, '')

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
    ...options,
  })

  const payload = await response.json().catch(() => null)
  if (!response.ok || payload?.status === 'error') {
    const message = payload?.error?.message || `Request failed with status ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.code = payload?.error?.code || 'request_failed'
    throw error
  }
  return payload?.data
}

export async function listDatalakes() {
  const data = await request('/datalakes')
  return data?.datalakes || []
}

export async function getDatalakeSummary(name) {
  return request(`/datalakes/${encodeURIComponent(name)}/summary`)
}

export async function preprocessDatalake(name, params, { force = false } = {}) {
  return request('/preprocess', {
    method: 'POST',
    body: JSON.stringify({
      datalake: name,
      params,
      force,
    }),
  })
}

export async function getPreprocessArtifacts(name) {
  return request(`/preprocess/${encodeURIComponent(name)}/artifacts`)
}

export async function getSampleQueries(name) {
  const data = await request(`/sample-queries?datalake=${encodeURIComponent(name)}`)
  return data?.queries || []
}

export async function generateQueryTables({ datalake, nlQuery, suggestionCount = 4, annTopk = 25 }) {
  return request('/query-tables', {
    method: 'POST',
    body: JSON.stringify({
      datalake,
      natural_language_query: nlQuery,
      desired_suggestion_count: suggestionCount,
      ann_topk: annTopk,
    }),
  })
}

export async function resubmitQueryTables({
  datalake,
  nlQuery,
  editedRows,
  priorSelectedTableName,
  suggestionCount = 4,
  annTopk = 25,
}) {
  return request('/query-tables/resubmit', {
    method: 'POST',
    body: JSON.stringify({
      datalake,
      natural_language_query: nlQuery,
      edited_query_table_rows: editedRows,
      prior_selected_table_name: priorSelectedTableName,
      desired_suggestion_count: suggestionCount,
      ann_topk: annTopk,
    }),
  })
}

export async function joinSearch({ datalake, nlQuery, confirmedRows, topK = 5, dedupThreshold = 0.8 }) {
  return request('/join-search', {
    method: 'POST',
    body: JSON.stringify({
      datalake,
      natural_language_query: nlQuery,
      confirmed_query_table_rows: confirmedRows,
      top_k: topK,
      dedup_threshold: dedupThreshold,
    }),
  })
}

export async function getJoinPathMetadata(pathId, datalake) {
  return request(`/join-paths/${encodeURIComponent(pathId)}?datalake=${encodeURIComponent(datalake)}`)
}

export async function getJoinPathSql(pathId, datalake) {
  return request(`/join-paths/${encodeURIComponent(pathId)}/sql?datalake=${encodeURIComponent(datalake)}`)
}

export async function materializeJoinPath(pathId, datalake, limit = 50, projection) {
  const queryColumns = projection?.queryColumns
  const querySemanticTypes = projection?.querySemanticTypes
  if (Array.isArray(queryColumns) && queryColumns.length) {
    return request(`/join-paths/${encodeURIComponent(pathId)}/materialize`, {
      method: 'POST',
      body: JSON.stringify({
        datalake,
        limit,
        query_columns: queryColumns,
        query_semantic_types: querySemanticTypes || {},
      }),
    })
  }
  return request(
    `/join-paths/${encodeURIComponent(pathId)}/materialize?datalake=${encodeURIComponent(datalake)}&limit=${encodeURIComponent(limit)}`,
  )
}

export async function getJoinPathCsv(pathId, datalake, projection) {
  const queryColumns = projection?.queryColumns
  const querySemanticTypes = projection?.querySemanticTypes
  const useProjection = Array.isArray(queryColumns) && queryColumns.length > 0

  const response = await fetch(
    `${API_BASE_URL}/join-paths/${encodeURIComponent(pathId)}/csv${useProjection ? '' : `?datalake=${encodeURIComponent(datalake)}`}`,
    useProjection
      ? {
          method: 'POST',
          headers: { Accept: 'text/csv', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            datalake,
            query_columns: queryColumns,
            query_semantic_types: querySemanticTypes || {},
          }),
        }
      : { headers: { Accept: 'text/csv' } },
  )
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const message = payload?.error?.message || `Request failed with status ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.code = payload?.error?.code || 'request_failed'
    throw error
  }
  return response.text()
}
