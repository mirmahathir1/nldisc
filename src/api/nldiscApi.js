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
