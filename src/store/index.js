import { createStore } from 'vuex'

import {
  applyPredicatesToMaterialized,
  buildJoinGraph,
  buildJoinPathIndex,
  buildSemanticTypeIndex,
  countRowsForPath,
  generateQueryTables,
  findTopJoinPaths,
  inferCandidateTablesFromQueryTable,
  makeDefaultDataLake,
  materializePath,
  seedFromString,
  sqlForPath,
  toCSV,
} from '../lib/nldisc'

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

function predSignature(preds) {
  if (!preds?.length) return ''
  return preds.map((p) => `${p?.field || ''}|${p?.op || ''}|${p?.value || ''}`).join(';')
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

function inferQueryTableHintsFromRows(rows) {
  const rs = Array.isArray(rows) ? rows : []
  const cols = new Set()
  for (const r of rs) {
    for (const k of Object.keys(r || {})) cols.add(k)
  }
  const colList = [...cols]
  const lowerCols = colList.map((c) => String(c).toLowerCase())

  const findCol = (re) => colList[lowerCols.findIndex((c) => re.test(c))] || null
  const productCol = findCol(/product/)
  const storeCol = findCol(/store|region/)

  const uniqNonEmptyStrings = (col) => {
    if (!col) return []
    const out = []
    const seen = new Set()
    for (const r of rs) {
      const v = r?.[col]
      const s = String(v ?? '').trim()
      if (!s) continue
      const key = s.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      out.push(s)
      if (out.length >= 8) break
    }
    return out
  }

  const wants_sales = lowerCols.some((c) => c.includes('amount') || c.includes('sales') || c.includes('revenue') || c.includes('currency'))
  const wants_products = lowerCols.some((c) => c.includes('product'))
  const wants_store = lowerCols.some((c) => c.includes('store') || c.includes('region'))
  const wants_quarter = lowerCols.some((c) => c.includes('quarter') || c.includes('year') || c.includes('time'))

  return {
    signals: { wants_sales, wants_products, wants_store, wants_quarter },
    columnNames: {
      product_name: productCol || 'product_name',
      store_name: storeCol || 'store_name',
    },
    samples: {
      product_names: uniqNonEmptyStrings(productCol),
      store_names: uniqNonEmptyStrings(storeCol),
    },
  }
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
    dataLake: null,

    // Stage 2
    params: defaultParams(),
    preprocessed: false,
    semanticIndex: null,
    joinEdges: null,
    joinPathIndex: null, // array of {path_id,tables,tables_list,length,score}
    preprocessExpandedPaths: new Set(),
    preprocessRowCounts: {}, // key: `${sig}::${pathId}` -> count

    // Stage 3
    nlQuery: 'Show me sales data for the past quarters.',
    queryTables: null, // [{name, rows}]
    selectedQtName: null,
    editedQueryTables: {}, // name -> edited rows
    confirmedQtRows: null,
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
    canGoStage2: (state) => Boolean(state.dataLake),
    canGoStage3: (state) => Boolean(state.dataLake && state.preprocessed),
    canGoStage4: (state) => Boolean(state.dataLake && state.preprocessed && state.confirmedQtRows),
  },

  mutations: {
    setStage(state, stage) {
      state.stage = stage
    },

    setUploadedFiles(state, files) {
      state.uploadedFiles = files || []
    },

    loadDefaultDataLake(state) {
      state.dataLake = makeDefaultDataLake(7)
      // Reset pipeline state
      state.preprocessed = false
      state.semanticIndex = null
      state.joinEdges = null
      state.joinPathIndex = null
      state.queryTables = null
      state.selectedQtName = null
      state.editedQueryTables = {}
      state.confirmedQtRows = null
      state.predicates = []
      state.requiredTables = []
      state.topPaths = null
      state.selectedPathId = null
      state.selectedPathTables = null
      state.selectedPathSql = ''
      state.materializedRows = null
      state.materializedCsv = ''
      state.queryTablesSeed = null
      state.queryTablesPredSig = null
      state.preprocessExpandedPaths = new Set()
      state.preprocessRowCounts = {}
    },

    setParams(state, params) {
      state.params = { ...state.params, ...(params || {}) }
    },

    setPreprocessedArtifacts(state, { semanticIndex, joinEdges, joinPathIndex }) {
      state.semanticIndex = semanticIndex
      state.joinEdges = joinEdges
      state.joinPathIndex = joinPathIndex
      state.preprocessed = true
      // Reset later stages
      state.queryTables = null
      state.selectedQtName = null
      state.editedQueryTables = {}
      state.confirmedQtRows = null
      state.predicates = []
      state.requiredTables = []
      state.topPaths = null
      state.selectedPathId = null
      state.selectedPathTables = null
      state.selectedPathSql = ''
      state.materializedRows = null
      state.materializedCsv = ''
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

    setQueryTables(state, { qts, seed, predSig }) {
      state.queryTables = qts
      state.queryTablesSeed = seed
      state.queryTablesPredSig = predSig
      state.editedQueryTables = {}
      ensureSelectedQueryTable(state)
      state.confirmedQtRows = null
      state.requiredTables = []
      state.topPaths = null
      state.selectedPathId = null
      state.selectedPathTables = null
      state.selectedPathSql = ''
      state.materializedRows = null
      state.materializedCsv = ''
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
        state.requiredTables = []
        state.topPaths = null
        state.selectedPathId = null
        state.selectedPathTables = null
        state.selectedPathSql = ''
        state.materializedRows = null
        state.materializedCsv = ''
      }
    },

    resetDisambiguation(state) {
      state.queryTables = null
      state.selectedQtName = null
      state.editedQueryTables = {}
      state.confirmedQtRows = null
      state.predicates = []
      state.requiredTables = []
      state.topPaths = null
      state.selectedPathId = null
      state.selectedPathTables = null
      state.selectedPathSql = ''
      state.materializedRows = null
      state.materializedCsv = ''
      state.queryTablesSeed = null
      state.queryTablesPredSig = null
    },

    setResults(state, { requiredTables, topPaths }) {
      state.requiredTables = requiredTables || []
      state.topPaths = topPaths || []
      state.selectedPathId = state.topPaths?.[0]?.path_id ?? null
    },

    setSelectedPath(state, { pathId, pathTables, sql, rows, csv }) {
      state.selectedPathId = pathId
      state.selectedPathTables = pathTables
      state.selectedPathSql = sql
      state.materializedRows = rows
      state.materializedCsv = csv
    },
  },

  actions: {
    preprocess({ state, commit }) {
      if (!state.dataLake) return
      const semanticIndex = buildSemanticTypeIndex(state.dataLake, seedFromString('semantic'))
      const joinEdges = buildJoinGraph(state.params)
      const joinPathIndex = buildJoinPathIndex(joinEdges, Number(state.params.max_join_path_length || 5))
      commit('setPreprocessedArtifacts', { semanticIndex, joinEdges, joinPathIndex })
      if (state.stage < 2) commit('setStage', 2)
    },

    maybeComputeRowCount({ state, commit }, { pathId, pathTables }) {
      const sig = preprocessSignature(state.dataLake, state.params)
      const key = `${sig}::${pathId}`
      if (Object.prototype.hasOwnProperty.call(state.preprocessRowCounts, key)) return
      try {
        const count = countRowsForPath(state.dataLake, pathTables, state.joinEdges)
        commit('setPreprocessRowCount', { key, count })
      } catch {
        commit('setPreprocessRowCount', { key, count: -1 })
      }
    },

    generateQueryTables({ state, commit }) {
      const q = state.nlQuery
      const seed = seedFromString(q) ^ 0xa5a5
      const predSig = predSignature(state.predicates)
      const qts = generateQueryTables(q, seed, state.predicates, Number(state.params.query_table_suggestion_count || 4))
      commit('setQueryTables', { qts, seed, predSig })
    },

    regenerateQueryTablesIfPredicateChanged({ state, commit }) {
      if (!state.queryTables || state.queryTablesSeed == null) return
      const curSig = predSignature(state.predicates)
      if (curSig === (state.queryTablesPredSig || '')) return
      const qts = generateQueryTables(
        state.nlQuery,
        Number(state.queryTablesSeed),
        state.predicates,
        Number(state.params.query_table_suggestion_count || 4),
      )
      commit('setQueryTables', { qts, seed: Number(state.queryTablesSeed), predSig: curSig })
    },

    resubmitFromEdits({ state, commit }) {
      const name = state.selectedQtName
      const rows = (state.editedQueryTables || {})[name] || []
      if (!rows) return
      const seed = seedFromString(JSON.stringify(rows)) ^ 0x5a5a
      const predSig = predSignature(state.predicates)
      const hints = inferQueryTableHintsFromRows(rows)
      const qts = generateQueryTables(
        state.nlQuery,
        seed,
        state.predicates,
        Number(state.params.query_table_suggestion_count || 4),
        hints,
      )

      // Keep the user's edited table as the corresponding suggestion so they can confirm it after resubmit.
      const idx = (qts || []).findIndex((q) => q?.name === name)
      if (idx >= 0) {
        qts[idx] = { ...qts[idx], rows: rows.map((r) => ({ ...r })) }
      } else if (qts?.length) {
        qts[0] = { ...qts[0], rows: rows.map((r) => ({ ...r })) }
      }
      commit('setQueryTables', { qts, seed, predSig })
    },

    runJoinSearch({ state, commit, dispatch }) {
      if (!state.confirmedQtRows || !state.joinPathIndex) return
      const requiredTables = inferCandidateTablesFromQueryTable(state.confirmedQtRows)
      const k = Math.max(10, Number(state.params.top_k_paths || 5))
      const topPaths = findTopJoinPaths(state.joinPathIndex, requiredTables, k)
      commit('setResults', { requiredTables, topPaths })
      if (topPaths?.[0]) {
        dispatch('selectPath', topPaths[0].path_id)
      }
    },

    selectPath({ state, commit }, pathId) {
      if (!state.topPaths?.length || !state.dataLake) return
      const row = state.topPaths.find((r) => r.path_id === pathId) || state.topPaths[0]
      const pathTables = row.tables_list || String(row.tables).split('→').map((t) => t.trim())
      const sql = sqlForPath(pathTables, state.joinEdges)
      const rows0 = materializePath(state.dataLake, pathTables, state.joinEdges, 200)
      const rows = applyPredicatesToMaterialized(rows0, state.predicates)
      const csv = toCSV(rows)
      commit('setSelectedPath', { pathId: row.path_id, pathTables, sql, rows, csv })
    },
  },
})

