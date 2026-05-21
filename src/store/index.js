import { createStore } from 'vuex'

import {
  generateQueryTables as apiGenerateQueryTables,
  getDatalakeSummary,
  getJoinPathCsv,
  getJoinPathMetadata,
  getJoinPathSql,
  getSampleQueries,
  joinSearch as apiJoinSearch,
  listDatalakes,
  materializeJoinPath,
  preprocessDatalake,
  resubmitQueryTables as apiResubmitQueryTables,
} from '../api/nldiscApi'

function defaultParams() {
  return {
    semantic_type_similarity_threshold: 0.75,
    semantic_joinability_threshold: 0.75,
    equi_joinability_threshold: 0.9,
    max_join_path_length: 5,
    top_k_paths: 5,
    ann_topk: 25,
    query_table_suggestion_count: 4,
  }
}

function normalizeQueryTables(rawTables) {
  return (Array.isArray(rawTables) ? rawTables : [])
    .filter((qt) => qt && typeof qt === 'object')
    .map((qt) => ({
      name: String(qt.name ?? 'Query Table'),
      columns: Array.isArray(qt.columns) ? qt.columns : [],
      semantic_types: qt.semantic_types || {},
      rows: (Array.isArray(qt.rows) ? qt.rows : [])
        .filter((row) => row && typeof row === 'object')
        .map((row) => ({ ...row })),
    }))
}

function preprocessSignature(dataLake, params) {
  const entries = Object.entries(dataLake || {}).sort(([a], [b]) => a.localeCompare(b))
  const lakeSig = entries
    .map(([k, v]) => `${k}:${Array.isArray(v) ? v.length : 0}x${v?.[0] ? Object.keys(v[0]).length : 0}`)
    .join('|')
  const pSig = [
    params?.semantic_type_similarity_threshold,
    params?.semantic_joinability_threshold,
    params?.equi_joinability_threshold,
    params?.max_join_path_length,
  ].join('|')
  return `${lakeSig}::${pSig}`
}

function dataLakeFromSummary(summary) {
  return Object.fromEntries((summary?.tables || []).map((table) => [table.name, table.sample_rows || []]))
}

function resetPipelineState(state) {
  state.preprocessed = false
  state.semanticIndex = null
  state.joinEdges = null
  state.joinPathIndex = null
  state.tableDescriptions = {}
  state.rowCounts = {}
  state.preprocessStatus = null
  state.queryTables = null
  state.selectedQtName = null
  state.editedQueryTables = {}
  state.confirmedQtRows = null
  state.confirmedQtSemanticTypes = {}
  state.predicates = []
  state.requiredTables = []
  state.topPaths = null
  state.selectedPathId = null
  state.selectedPathTables = null
  state.selectedPathSql = ''
  state.materializedRows = null
  state.materializedCsv = ''
  state.materializedProjection = null
  state.queryTablesSeed = null
  state.queryTablesPredSig = null
  state.preprocessExpandedPaths = new Set()
  state.preprocessRowCounts = {}
}

function ensureSelectedQueryTable(state) {
  if (!state.queryTables?.length) return
  const names = state.queryTables.map((q) => q.name)
  if (!state.selectedQtName || !names.includes(state.selectedQtName)) state.selectedQtName = names[0]
  if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
  for (const qt of state.queryTables) {
    if (!Object.prototype.hasOwnProperty.call(state.editedQueryTables, qt.name)) {
      state.editedQueryTables[qt.name] = (qt.rows || []).map((r) => ({ ...r }))
    }
  }
}

export default createStore({
  state: () => ({
    stage: 1,

    // Stage 1
    uploadedFiles: [],
    availableDatalakes: [],
    dataLakeName: '',
    dataLakeSummary: null,
    dataLake: null,
    dataLakeLoading: false,
    preprocessLoading: false,
    backendError: '',

    // Stage 2
    params: defaultParams(),
    preprocessed: false,
    semanticIndex: null,
    joinEdges: null,
    joinPathIndex: null, // array of {path_id,tables,tables_list,length,score}
    tableDescriptions: {},
    rowCounts: {},
    preprocessStatus: null,
    preprocessExpandedPaths: new Set(),
    preprocessRowCounts: {}, // key: `${sig}::${pathId}` -> count

    // Stage 3
    nlQuery: '',
    sampleQueries: [], // [{label, query}] for the selected data lake
    queryTables: null, // [{name, rows}]
    selectedQtName: null,
    editedQueryTables: {}, // name -> edited rows
    confirmedQtRows: null,
    confirmedQtSemanticTypes: {}, // column name -> semantic type text (from confirmed query table)
    predicates: [],
    queryTablesSeed: null,
    queryTablesPredSig: null,

    // Stage 4
    requiredTables: [],
    topPaths: null,
    selectedPathId: null,
    selectedPathTables: null,
    selectedPathSql: '',
    materializedRows: null,
    materializedCsv: '',
    materializedProjection: null, // { query_columns, selected_columns, column_mapping }
  }),

  getters: {
    stageLabels: () => [
      'Upload data lake',
      'Preprocess & build indexes',
      'Query & Disambiguate',
      'Join paths, SQL & download',
    ],
    selectedQueryTable: (state) =>
      state.queryTables?.find((q) => q.name === state.selectedQtName) || (state.queryTables?.[0] ?? null),
    editedRowsFor: (state) => (name) => {
      if (!name) return []
      const m = state.editedQueryTables || {}
      if (Object.prototype.hasOwnProperty.call(m, name)) return m[name] || []
      const fallback = state.queryTables?.find((q) => q.name === name)
      return fallback?.rows ? fallback.rows.map((r) => ({ ...r })) : []
    },
    selectedEditedRows: (state, getters) => getters.editedRowsFor(state.selectedQtName),
    canGoStage2: (state) => Boolean(state.dataLakeName && state.dataLake),
    canGoStage3: (state) => Boolean(state.dataLakeName && state.dataLake && state.preprocessed),
    canGoStage4: (state) => Boolean(state.dataLakeName && state.dataLake && state.preprocessed && state.confirmedQtRows),
  },

  mutations: {
    setStage(state, stage) {
      state.stage = stage
    },

    setUploadedFiles(state, files) {
      state.uploadedFiles = files || []
    },

    setBackendError(state, message) {
      state.backendError = message || ''
    },

    setDatalakeLoading(state, loading) {
      state.dataLakeLoading = Boolean(loading)
    },

    setPreprocessLoading(state, loading) {
      state.preprocessLoading = Boolean(loading)
    },

    setAvailableDatalakes(state, datalakes) {
      state.availableDatalakes = datalakes || []
    },

    setPendingDatalake(state, name) {
      state.dataLakeName = name || ''
      state.dataLakeSummary = null
      state.dataLake = null
      resetPipelineState(state)
    },

    setSelectedDatalakeSummary(state, { name, summary }) {
      state.dataLakeName = name || ''
      state.dataLakeSummary = summary || null
      state.dataLake = dataLakeFromSummary(summary)
      state.uploadedFiles = []
      resetPipelineState(state)
    },

    setParams(state, params) {
      const previous = JSON.stringify(state.params)
      state.params = { ...state.params, ...(params || {}) }
      if (state.preprocessed && previous !== JSON.stringify(state.params)) {
        resetPipelineState(state)
      }
    },

    setPreprocessedArtifacts(state, { semanticIndex, joinEdges, joinPathIndex, tableDescriptions, rowCounts, preprocessStatus }) {
      state.semanticIndex = semanticIndex
      state.joinEdges = joinEdges
      state.joinPathIndex = joinPathIndex
      state.tableDescriptions = tableDescriptions || {}
      state.rowCounts = rowCounts || {}
      state.preprocessStatus = preprocessStatus || null
      state.preprocessed = true
      // Reset later stages
      state.queryTables = null
      state.selectedQtName = null
      state.editedQueryTables = {}
      state.confirmedQtRows = null
      state.confirmedQtSemanticTypes = {}
      state.predicates = []
      state.requiredTables = []
      state.topPaths = null
      state.selectedPathId = null
      state.selectedPathTables = null
      state.selectedPathSql = ''
      state.materializedRows = null
      state.materializedCsv = ''
      state.materializedProjection = null
      state.queryTablesSeed = null
      state.queryTablesPredSig = null
    },

    togglePreprocessExpandedPath(state, pathId) {
      const next = new Set(state.preprocessExpandedPaths)
      if (next.has(pathId)) next.delete(pathId)
      else next.add(pathId)
      state.preprocessExpandedPaths = next
    },

    setPreprocessRowCount(state, { key, count }) {
      state.preprocessRowCounts = { ...state.preprocessRowCounts, [key]: count }
    },

    setNlQuery(state, q) {
      state.nlQuery = q
    },

    setSampleQueries(state, queries) {
      state.sampleQueries = Array.isArray(queries) ? queries : []
    },

    setQueryTables(state, { qts, seed, predSig }) {
      state.queryTables = qts
      state.queryTablesSeed = seed
      state.queryTablesPredSig = predSig
      state.editedQueryTables = {}
      ensureSelectedQueryTable(state)
      state.confirmedQtRows = null
      state.confirmedQtSemanticTypes = {}
      state.requiredTables = []
      state.topPaths = null
      state.selectedPathId = null
      state.selectedPathTables = null
      state.selectedPathSql = ''
      state.materializedRows = null
      state.materializedCsv = ''
      state.materializedProjection = null
    },

    setSelectedQtName(state, name) {
      state.selectedQtName = name
      ensureSelectedQueryTable(state)
    },

    setEditedQueryTableRows(state, { name, rows }) {
      if (!name) return
      if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
      state.editedQueryTables = { ...state.editedQueryTables, [name]: Array.isArray(rows) ? rows : [] }
    },

    updateEditedQueryTableCell(state, { name, rowIndex, col, value }) {
      if (!name || !col) return
      if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
      const curRows = state.editedQueryTables[name] || []
      if (!Array.isArray(curRows)) return
      if (rowIndex < 0 || rowIndex >= curRows.length) return
      const row = { ...(curRows[rowIndex] || {}) }
      row[col] = value
      const next = curRows.slice()
      next[rowIndex] = row
      state.editedQueryTables = { ...state.editedQueryTables, [name]: next }
    },

    addEditedQueryTableRow(state, { name, template }) {
      if (!name) return
      if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
      const curRows = Array.isArray(state.editedQueryTables[name]) ? state.editedQueryTables[name] : []
      const row = { ...(template || {}) }
      state.editedQueryTables = { ...state.editedQueryTables, [name]: [...curRows, row] }
    },

    deleteEditedQueryTableRow(state, { name, rowIndex }) {
      if (!name) return
      if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
      const curRows = Array.isArray(state.editedQueryTables[name]) ? state.editedQueryTables[name] : []
      const next = curRows.slice()
      next.splice(rowIndex, 1)
      state.editedQueryTables = { ...state.editedQueryTables, [name]: next }
    },

    addEditedQueryTableColumn(state, { name, col, defaultValue = '' }) {
      const cname = String(col || '').trim()
      if (!name || !cname) return
      if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
      const curRows = Array.isArray(state.editedQueryTables[name]) ? state.editedQueryTables[name] : []

      // If there are no rows, create a single empty row so the column is visible.
      const base = curRows.length ? curRows : [{}]
      const next = base.map((r) => {
        const out = { ...(r || {}) }
        if (!(cname in out)) out[cname] = defaultValue
        return out
      })
      state.editedQueryTables = { ...state.editedQueryTables, [name]: next }
    },

    renameEditedQueryTableColumn(state, { name, oldCol, newCol }) {
      const from = String(oldCol || '').trim()
      const to = String(newCol || '').trim()
      if (!name || !from || !to || from === to) return
      if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
      const curRows = Array.isArray(state.editedQueryTables[name]) ? state.editedQueryTables[name] : []
      const base = curRows.length ? curRows : [{}]

      const next = base.map((r) => {
        const out = { ...(r || {}) }
        if (Object.prototype.hasOwnProperty.call(out, from)) {
          // If destination already exists, prefer keeping existing destination value.
          if (!Object.prototype.hasOwnProperty.call(out, to)) out[to] = out[from]
          delete out[from]
        }
        return out
      })
      state.editedQueryTables = { ...state.editedQueryTables, [name]: next }
    },

    removeEditedQueryTableColumn(state, { name, col }) {
      const cname = String(col || '').trim()
      if (!name || !cname) return
      if (!state.editedQueryTables || typeof state.editedQueryTables !== 'object') state.editedQueryTables = {}
      const curRows = Array.isArray(state.editedQueryTables[name]) ? state.editedQueryTables[name] : []
      const base = curRows.length ? curRows : [{}]
      const next = base.map((r) => {
        const out = { ...(r || {}) }
        if (Object.prototype.hasOwnProperty.call(out, cname)) delete out[cname]
        return out
      })
      state.editedQueryTables = { ...state.editedQueryTables, [name]: next }
    },

    setPredicates(state, preds) {
      state.predicates = preds || []
    },

    confirmEditedQueryTable(state) {
      const name = state.selectedQtName
      const rows = (state.editedQueryTables || {})[name] || []
      if (rows?.length) {
        state.confirmedQtRows = rows.map((r) => ({ ...r }))
        const selected = (state.queryTables || []).find((q) => q?.name === name)
        const sem = (selected && selected.semantic_types) || {}
        state.confirmedQtSemanticTypes = { ...sem }
        state.requiredTables = []
        state.topPaths = null
        state.selectedPathId = null
        state.selectedPathTables = null
        state.selectedPathSql = ''
        state.materializedRows = null
        state.materializedCsv = ''
        state.materializedProjection = null
      }
    },

    resetDisambiguation(state) {
      state.queryTables = null
      state.selectedQtName = null
      state.editedQueryTables = {}
      state.confirmedQtRows = null
      state.confirmedQtSemanticTypes = {}
      state.predicates = []
      state.requiredTables = []
      state.topPaths = null
      state.selectedPathId = null
      state.selectedPathTables = null
      state.selectedPathSql = ''
      state.materializedRows = null
      state.materializedCsv = ''
      state.materializedProjection = null
      state.queryTablesSeed = null
      state.queryTablesPredSig = null
    },

    setResults(state, { requiredTables, topPaths }) {
      state.requiredTables = requiredTables || []
      state.topPaths = topPaths || []
      state.selectedPathId = state.topPaths?.[0]?.path_id ?? null
    },

    setSelectedPath(state, { pathId, pathTables, sql, rows, csv, projection }) {
      state.selectedPathId = pathId
      state.selectedPathTables = pathTables
      state.selectedPathSql = sql
      state.materializedRows = rows
      state.materializedCsv = csv
      state.materializedProjection = projection || null
    },
  },

  actions: {
    async loadDatalakes({ commit }) {
      commit('setDatalakeLoading', true)
      commit('setBackendError', '')
      try {
        commit('setAvailableDatalakes', await listDatalakes())
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to load data lakes.')
      } finally {
        commit('setDatalakeLoading', false)
      }
    },

    async selectDataLake({ commit, dispatch }, name) {
      if (!name) return
      commit('setDatalakeLoading', true)
      commit('setBackendError', '')
      commit('setPendingDatalake', name)
      commit('setSampleQueries', [])
      try {
        const summary = await getDatalakeSummary(name)
        commit('setSelectedDatalakeSummary', { name, summary })
        dispatch('loadSampleQueries', name)
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to load data lake summary.')
      } finally {
        commit('setDatalakeLoading', false)
      }
    },

    async loadSampleQueries({ state, commit }, name) {
      const datalake = name || state.dataLakeName
      if (!datalake) return
      try {
        commit('setSampleQueries', await getSampleQueries(datalake))
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to load sample queries.')
      }
    },

    async preprocess({ state, commit }) {
      if (!state.dataLakeName) return
      commit('setPreprocessLoading', true)
      commit('setBackendError', '')
      try {
        const artifacts = await preprocessDatalake(state.dataLakeName, state.params)
        commit('setPreprocessedArtifacts', {
          semanticIndex: artifacts?.semantic_types || {},
          joinEdges: artifacts?.join_edges || [],
          joinPathIndex: artifacts?.join_paths || [],
          tableDescriptions: artifacts?.table_descriptions || {},
          rowCounts: artifacts?.row_counts || {},
          preprocessStatus: artifacts?.preprocessing || null,
        })
        if (state.stage < 2) commit('setStage', 2)
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to run preprocessing.')
      } finally {
        commit('setPreprocessLoading', false)
      }
    },

    async maybeComputeRowCount({ state, commit }, { pathId }) {
      if (!pathId || !state.dataLakeName) return
      const sig = preprocessSignature(state.dataLake, state.params)
      const key = `${sig}::${pathId}`
      if (Object.prototype.hasOwnProperty.call(state.preprocessRowCounts, key)) return
      const known = (state.topPaths || []).find((p) => p?.path_id === pathId)
      const knownEstimate = known?.row_count_estimate ?? known?.cardinality_estimate
      if (typeof knownEstimate === 'number') {
        commit('setPreprocessRowCount', { key, count: knownEstimate })
        return
      }
      try {
        const data = await getJoinPathMetadata(pathId, state.dataLakeName)
        const meta = data?.path || data?.join_path || {}
        const count = meta.row_count_estimate ?? meta.cardinality_estimate ?? -1
        commit('setPreprocessRowCount', { key, count })
      } catch {
        commit('setPreprocessRowCount', { key, count: -1 })
      }
    },

    async generateQueryTables({ state, commit }) {
      if (!state.dataLakeName) return
      if (!String(state.nlQuery || '').trim()) return
      commit('setBackendError', '')
      try {
        const data = await apiGenerateQueryTables({
          datalake: state.dataLakeName,
          nlQuery: state.nlQuery,
          suggestionCount: Number(state.params.query_table_suggestion_count || 4),
          annTopk: Number(state.params.ann_topk || 25),
        })
        const qts = normalizeQueryTables(data?.query_tables || data?.queryTables || [])
        commit('setQueryTables', { qts, seed: null, predSig: '' })
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to generate query tables.')
      }
    },

    async resubmitFromEdits({ state, commit }) {
      const name = state.selectedQtName
      const rows = (state.editedQueryTables || {})[name] || []
      if (!state.dataLakeName) return
      if (!Array.isArray(rows) || !rows.length) return
      commit('setBackendError', '')
      try {
        const data = await apiResubmitQueryTables({
          datalake: state.dataLakeName,
          nlQuery: state.nlQuery,
          editedRows: rows,
          priorSelectedTableName: name,
          suggestionCount: Number(state.params.query_table_suggestion_count || 4),
          annTopk: Number(state.params.ann_topk || 25),
        })
        const qts = normalizeQueryTables(data?.query_tables || data?.queryTables || [])
        commit('setQueryTables', { qts, seed: null, predSig: '' })
        if (name && qts.some((q) => q.name === name)) commit('setSelectedQtName', name)
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to resubmit query tables.')
      }
    },

    async runJoinSearch({ state, commit, dispatch }) {
      if (!state.dataLakeName || !state.confirmedQtRows?.length) return
      commit('setBackendError', '')
      try {
        const data = await apiJoinSearch({
          datalake: state.dataLakeName,
          nlQuery: state.nlQuery,
          confirmedRows: state.confirmedQtRows,
          topK: Math.max(1, Number(state.params.top_k_paths || 5)),
          dedupThreshold: 0.8,
        })
        const topPaths = data?.join_paths || data?.top_paths || data?.paths || []
        const requiredTables = data?.required_tables || []
        commit('setResults', { requiredTables, topPaths })
        if (topPaths?.[0]) {
          await dispatch('selectPath', topPaths[0].path_id)
        }
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to run join search.')
      }
    },

    async selectPath({ state, commit }, pathId) {
      if (!state.topPaths?.length || !state.dataLakeName) return
      const row = state.topPaths.find((r) => r?.path_id === pathId) || state.topPaths[0]
      if (!row?.path_id) return
      const pathTables = Array.isArray(row.tables_list) && row.tables_list.length
        ? row.tables_list
        : Array.isArray(row.ordered_tables) ? row.ordered_tables : []
      const queryColumns = Array.from(
        new Set(
          (state.confirmedQtRows || []).flatMap((r) => (r && typeof r === 'object' ? Object.keys(r) : [])),
        ),
      )
      const projection = queryColumns.length
        ? {
            queryColumns,
            querySemanticTypes: state.confirmedQtSemanticTypes || {},
          }
        : undefined
      // Reflect the selection immediately so the UI highlights the chosen card while we fetch.
      commit('setSelectedPath', { pathId: row.path_id, pathTables, sql: '', rows: [], csv: '', projection: null })
      commit('setBackendError', '')
      try {
        const [sqlData, matData, csvText] = await Promise.all([
          getJoinPathSql(row.path_id, state.dataLakeName),
          materializeJoinPath(row.path_id, state.dataLakeName, 50, projection),
          getJoinPathCsv(row.path_id, state.dataLakeName, projection),
        ])
        commit('setSelectedPath', {
          pathId: row.path_id,
          pathTables,
          sql: sqlData?.sql || '',
          rows: matData?.rows || [],
          csv: csvText || '',
          projection: matData?.projection || null,
        })
      } catch (err) {
        commit('setBackendError', err?.message || 'Unable to materialize join path.')
      }
    },
  },
})
