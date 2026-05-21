<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'

import DelayedMount from '../components/DelayedMount.vue'
import JoinPathCard from '../components/JoinPathCard.vue'

const store = useStore()
const router = useRouter()

const params = computed(() => store.state.params)
const lake = computed(() => store.state.dataLake)
const backendError = computed(() => store.state.backendError)
const sampleQueries = computed(() => store.state.sampleQueries || [])

const joinEdges = computed(() => store.state.joinEdges || [])

const nlQuery = computed({
  get: () => store.state.nlQuery,
  set: (v) => store.commit('setNlQuery', v),
})

const sampleQueryItems = computed(() =>
  (sampleQueries.value || []).map((q) => ({ title: q.label || q.query, value: q.query })),
)
const sampleQuerySelection = ref(null)

function populateSampleQuery(value) {
  if (!value) return
  nlQuery.value = value
  // Reset the dropdown so the same item can be picked again.
  sampleQuerySelection.value = null
}

onMounted(() => {
  if (store.state.dataLakeName && !sampleQueries.value.length) {
    store.dispatch('loadSampleQueries', store.state.dataLakeName)
  }
})

const queryTables = computed(() => store.state.queryTables || [])
const selectedQtName = computed({
  get: () => store.state.selectedQtName,
  set: (v) => store.commit('setSelectedQtName', v),
})
const selectedEditedRows = computed(() => store.getters.selectedEditedRows || [])

const confirmedQtRows = computed(() => store.state.confirmedQtRows)
const topPaths = computed(() => store.state.topPaths || [])
const selectedPathId = computed({
  get: () => store.state.selectedPathId,
  set: (v) => store.dispatch('selectPath', v),
})
const selectedPathTables = computed(() => store.state.selectedPathTables || [])
const selectedPathSql = computed(() => store.state.selectedPathSql || '')
const materializedRows = computed(() => store.state.materializedRows || [])

const queryTablesUiRunning = ref(false)
const joinSearchUiRunning = ref(false)
const queryTablesRenderTrigger = ref(0)
const resultsRenderTrigger = ref(0)

const headerDrafts = ref({})
const removeColumnName = ref('')

function norm(s) {
  return String(s ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
}

const confirmedQueryColumns = computed(() => {
  const rows = confirmedQtRows.value
  if (!Array.isArray(rows)) return []
  const set = new Set()
  for (const r of rows) {
    for (const k of Object.keys(r || {})) set.add(k)
  }
  return [...set]
})

const confirmedQueryColNorms = computed(() => new Set(confirmedQueryColumns.value.map(norm).filter(Boolean)))

function materializedKeyMatchesQuery(colKey) {
  const raw = String(colKey ?? '')
  const suffix = raw.includes('.') ? raw.slice(raw.lastIndexOf('.') + 1) : raw
  const k = norm(suffix)
  return Boolean(k && confirmedQueryColNorms.value.has(k))
}

const materializedHeaders = computed(() => {
  const rows = materializedRows.value || []
  const cols = rows?.[0] ? Object.keys(rows[0]) : []
  return cols.map((c) => {
    const isQuery = materializedKeyMatchesQuery(c)
    return {
      title: c,
      key: c,
      headerProps: {
        class: ['mat-col--header', isQuery ? 'mat-col--query' : ''].filter(Boolean).join(' '),
      },
      cellProps: {
        class: ['mat-col--cell', isQuery ? 'mat-col--query' : ''].filter(Boolean).join(' '),
      },
    }
  })
})

function editedRowsFor(name) {
  return store.getters.editedRowsFor(name) || []
}

function prettyColumnName(col) {
  const s = String(col ?? '')
  if (!s) return s
  return s
    .replaceAll('_', ' ')
    .replaceAll('.', ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase())
}

function headerDraftKey(qtName, col) {
  return `${qtName}::${col}`
}

function headerDraftValue(qtName, col) {
  const key = headerDraftKey(qtName, col)
  return headerDrafts.value?.[key] ?? prettyColumnName(col)
}

function setHeaderDraft(qtName, col, v) {
  const key = headerDraftKey(qtName, col)
  headerDrafts.value = { ...(headerDrafts.value || {}), [key]: v }
}

function commitHeaderRenameIfNeeded(qtName, oldCol) {
  const key = headerDraftKey(qtName, oldCol)
  const raw = headerDrafts.value?.[key]
  const next = String(raw ?? '').trim()
  if (!next) return
  if (next === oldCol) return
  store.commit('renameEditedQueryTableColumn', { name: qtName, oldCol, newCol: next })
  // cleanup old draft entry
  const { [key]: _drop, ...rest } = headerDrafts.value || {}
  headerDrafts.value = rest
}

function qtColumnsFor(rows) {
  const set = new Set()
  for (const r of rows || []) {
    for (const k of Object.keys(r || {})) set.add(k)
  }
  return [...set]
}

function qtCols(qt) {
  const edited = editedRowsFor(qt?.name)
  const cols = qtColumnsFor(edited)
  if (cols.length) return cols
  return qtColumnsFor(qt?.rows || [])
}

function nextNewColumnName(existingCols) {
  const used = new Set((existingCols || []).map((c) => String(c)))
  if (!used.has('New Column')) return 'New Column'
  for (let i = 2; i < 200; i++) {
    const name = `New Column ${i}`
    if (!used.has(name)) return name
  }
  return `New Column ${Date.now()}`
}

function addBlankColumn(qt) {
  const cols = qtCols(qt)
  const name = nextNewColumnName(cols)
  store.commit('addEditedQueryTableColumn', { name: qt?.name, col: name })
}

function removeColumnFromQueryTable(qtName) {
  const col = String(removeColumnName.value || '').trim()
  if (!qtName || !col) return
  store.commit('removeEditedQueryTableColumn', { name: qtName, col })
  // Drop any draft for that header
  const key = headerDraftKey(qtName, col)
  if (headerDrafts.value?.[key] !== undefined) {
    const { [key]: _drop, ...rest } = headerDrafts.value || {}
    headerDrafts.value = rest
  }
  removeColumnName.value = ''
}

watch(
  selectedQtName,
  () => {
    removeColumnName.value = ''
  },
  { immediate: true },
)

function coerceCellValue(raw, current) {
  if (typeof current === 'number') {
    const n = Number(raw)
    return Number.isFinite(n) ? n : raw
  }
  return raw
}

function preprocessRowCount(pathId) {
  const p = (topPaths.value || []).find((row) => row?.path_id === pathId)
  return p?.row_count_estimate ?? p?.cardinality_estimate
}

function downloadSelectedCsv() {
  const csv = store.state.materializedCsv
  if (!csv) return
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `nldisc_${store.state.selectedPathId || 'result'}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function runGenerateQueryTables() {
  if (queryTablesUiRunning.value) return
  queryTablesUiRunning.value = true
  queryTablesRenderTrigger.value += 1
  try {
    await store.dispatch('generateQueryTables')
  } finally {
    queryTablesUiRunning.value = false
  }
}

async function runResubmitQueryTables() {
  if (queryTablesUiRunning.value) return
  queryTablesUiRunning.value = true
  queryTablesRenderTrigger.value += 1
  try {
    await store.dispatch('resubmitFromEdits')
  } finally {
    queryTablesUiRunning.value = false
  }
}

async function runConfirmAndJoinSearch() {
  if (joinSearchUiRunning.value) return
  joinSearchUiRunning.value = true
  resultsRenderTrigger.value += 1
  try {
    store.commit('confirmEditedQueryTable')
    await store.dispatch('runJoinSearch')
  } finally {
    joinSearchUiRunning.value = false
  }
}

function goBackOffline() {
  router.push({ name: 'offline' })
}
</script>

<template>
  <div class="pt-0 pb-6 px-0">
    <div class="d-flex align-center justify-space-between mb-4">
      <div class="d-flex align-center ga-2">
        <v-chip color="primary" variant="tonal" size="small">Online Stage</v-chip>
        <div class="text-h6">Query & Disambiguate</div>
      </div>
      <v-btn size="small" variant="tonal" @click="goBackOffline">Back to Offline Stage</v-btn>
    </div>

    <v-alert v-if="!store.getters.canGoStage3" type="warning" variant="tonal" class="mb-4">
      Please run preprocessing first (Offline Stage).
    </v-alert>

    <template v-else>
      <v-alert v-if="backendError" type="error" variant="tonal" density="compact" class="mb-3">
        {{ backendError }}
      </v-alert>

      <v-row>
      <!-- Left column: NL query + query tables grid -->
      <v-col cols="12" md="6">
        <v-card>
          <v-card-text>
            <v-row dense class="align-center">
              <v-col cols="12" md="5">
                <v-select
                  v-model="sampleQuerySelection"
                  :items="sampleQueryItems"
                  item-title="title"
                  item-value="value"
                  label="Populate a sample query"
                  prepend-inner-icon="mdi-lightbulb-on-outline"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="mb-2"
                  :disabled="!sampleQueryItems.length"
                  @update:model-value="populateSampleQuery"
                />
                <v-textarea
                  v-model="nlQuery"
                  label="Natural Language Query"
                  placeholder="Describe the table you want to build…"
                  variant="outlined"
                  rows="3"
                  auto-grow
                />
              </v-col>

              <v-col cols="12" md="7">
                <div class="text-medium-emphasis mb-1">Query table suggestions ({{ Number(params.query_table_suggestion_count) }})</div>
                <v-slider
                  :model-value="params.query_table_suggestion_count"
                  min="1"
                  max="10"
                  step="1"
                  hide-details
                  @update:model-value="store.commit('setParams', { query_table_suggestion_count: $event })"
                />

                <v-btn
                  class="mt-2"
                  size="x-small"
                  color="primary"
                  block
                  :loading="queryTablesUiRunning"
                  :disabled="queryTablesUiRunning || !nlQuery?.trim()"
                  @click="runGenerateQueryTables"
                >
                  Generate query tables
                </v-btn>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>Query tables</v-card-title>
          <v-card-text v-if="!queryTables.length && !queryTablesUiRunning">Generate query tables to begin.</v-card-text>
          <v-progress-linear v-if="queryTablesUiRunning" indeterminate color="primary" height="3" />
          <DelayedMount :active="!!queryTables.length && !queryTablesUiRunning" :trigger="queryTablesRenderTrigger">
            <v-card-text class="pa-0">
              <v-row dense no-gutters class="ma-0">
                <transition-group name="mount-pop" tag="div" class="qt-grid" appear>
                  <v-col
                    v-for="(qt, idx) in queryTables"
                    :key="qt.name"
                    cols="12"
                    md="6"
                    :style="{ transitionDelay: `${Math.min(idx, 12) * 35}ms` }"
                    class="qt-col"
                  >
                    <v-card
                      variant="outlined"
                      :elevation="qt.name === selectedQtName ? 16 : 1"
                      :class="['qt-card', qt.name === selectedQtName ? 'qt-card--selected' : '']"
                      @click="store.commit('setSelectedQtName', qt.name)"
                    >
                      <v-card-title class="py-2">
                        <div class="d-flex align-center justify-space-between ga-2">
                          <div class="text-subtitle-2">{{ qt.name }}</div>
                          <v-chip v-if="qt.name === selectedQtName" size="x-small" color="primary" variant="tonal">Selected</v-chip>
                        </div>
                      </v-card-title>
                      <v-divider />
                      <v-card-text class="pa-2">
                        <div v-if="qt.name === selectedQtName" class="d-flex ga-2 align-center flex-wrap mb-2">
                          <v-btn
                            size="x-small"
                            variant="tonal"
                            @click.stop="
                              (() => {
                                const cols = qtCols(qt)
                                const template = cols.length ? Object.fromEntries(cols.map((c) => [c, ''])) : {}
                                store.commit('addEditedQueryTableRow', { name: qt.name, template })
                              })()
                            "
                          >
                            Add row
                          </v-btn>
                          <v-btn size="x-small" variant="tonal" @click.stop="addBlankColumn(qt)">Add column</v-btn>

                          <v-spacer />

                          <div class="d-flex ga-2">
                            <v-btn
                              size="x-small"
                              color="primary"
                              :loading="queryTablesUiRunning"
                              :disabled="queryTablesUiRunning || !selectedEditedRows.length"
                              @click.stop="runResubmitQueryTables"
                            >
                              Resubmit
                            </v-btn>
                            <v-btn
                              size="x-small"
                              color="primary"
                              :loading="joinSearchUiRunning"
                              :disabled="!selectedEditedRows.length || joinSearchUiRunning"
                              @click.stop="runConfirmAndJoinSearch"
                            >
                              Confirm
                            </v-btn>
                          </div>
                        </div>

                        <v-table density="compact">
                          <thead>
                            <tr>
                              <th v-for="c in qtCols(qt)" :key="c">
                                <v-text-field
                                  v-if="qt.name === selectedQtName"
                                  :model-value="headerDraftValue(qt.name, c)"
                                  density="compact"
                                  variant="underlined"
                                  hide-details
                                  style="min-width: 120px"
                                  @click.stop
                                  @update:model-value="setHeaderDraft(qt.name, c, $event)"
                                  @blur="commitHeaderRenameIfNeeded(qt.name, c)"
                                  @keyup.enter="commitHeaderRenameIfNeeded(qt.name, c)"
                                />
                                <span v-else>{{ prettyColumnName(c) }}</span>
                              </th>
                              <th v-if="qt.name === selectedQtName" style="width: 1%">Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr v-for="(row, rowIndex) in editedRowsFor(qt.name).slice(0, 5)" :key="`${qt.name}-${rowIndex}`">
                              <td v-for="c in qtCols(qt)" :key="c">
                                <v-text-field
                                  v-if="qt.name === selectedQtName"
                                  :model-value="row?.[c]"
                                  density="compact"
                                  variant="outlined"
                                  hide-details
                                  @click.stop
                                  @update:model-value="
                                    store.commit('updateEditedQueryTableCell', {
                                      name: qt.name,
                                      rowIndex,
                                      col: c,
                                      value: coerceCellValue($event, row?.[c]),
                                    })
                                  "
                                />
                                <span v-else class="text-body-2">{{ row?.[c] }}</span>
                              </td>
                              <td v-if="qt.name === selectedQtName">
                                <v-btn size="x-small" variant="text" @click.stop="store.commit('deleteEditedQueryTableRow', { name: qt.name, rowIndex })">
                                  Remove
                                </v-btn>
                              </td>
                            </tr>
                          </tbody>
                        </v-table>

                        <div v-if="editedRowsFor(qt.name).length > 5" class="text-caption text-medium-emphasis mt-1">Showing first 5 rows.</div>

                        <div v-if="qt.name === selectedQtName" class="d-flex align-center ga-2 mt-2">
                          <v-select
                            v-model="removeColumnName"
                            label="Remove column"
                            density="compact"
                            variant="outlined"
                            hide-details
                            style="max-width: 220px"
                            :items="qtCols(qt).map((c) => ({ title: prettyColumnName(c), value: c }))"
                            item-title="title"
                            item-value="value"
                            @click.stop
                          />
                          <v-btn
                            size="x-small"
                            color="error"
                            variant="tonal"
                            :disabled="!removeColumnName"
                            @click.stop="removeColumnFromQueryTable(qt.name)"
                          >
                            Remove
                          </v-btn>
                        </div>
                      </v-card-text>
                    </v-card>
                  </v-col>
                </transition-group>
              </v-row>
            </v-card-text>
          </DelayedMount>
        </v-card>
      </v-col>

      <!-- Right column: join paths / SQL / download -->
      <v-col cols="12" md="6">
        <v-alert v-if="!confirmedQtRows" type="warning" variant="tonal" class="mb-4">
          Confirm a query table on the left to generate join paths.
        </v-alert>

        <DelayedMount v-else :active="!!confirmedQtRows" :trigger="resultsRenderTrigger">
          <div>
            <transition-group name="mount-pop" tag="div" class="jp-list jp-list--online mb-4" appear>
              <JoinPathCard
                v-for="(p, idx) in topPaths"
                :key="p.path_id"
                :path-id="p.path_id"
                :tables-list="p.tables_list"
                :edges="p.join_edges?.length ? p.join_edges : joinEdges"
                :data-lake="lake"
                :attributes="p.attributes"
                :query-columns="confirmedQueryColumns"
                :highlighted-tables="p.highlighted_tables"
                :row-count="preprocessRowCount(p.path_id)"
                :selected="p.path_id === selectedPathId"
                clickable
                :style="{ transitionDelay: `${Math.min(idx, 10) * 35}ms` }"
                @click="selectedPathId = p.path_id"
                @request-row-count="store.dispatch('maybeComputeRowCount', $event)"
              />
            </transition-group>

            <v-card class="mb-3">
              <v-card-title class="py-1 px-2 text-subtitle-2">SQL</v-card-title>
              <v-card-text v-if="!selectedPathTables.length" class="pt-0 pb-2 px-2">Select a join path from the list above.</v-card-text>
              <v-card-text v-else class="pt-0 pb-2 px-2">
                <pre class="pa-2 rounded bg-grey-lighten-4 sql-pre" style="white-space: pre-wrap; overflow: auto">{{ selectedPathSql }}</pre>
              </v-card-text>
            </v-card>

            <v-card>
              <v-card-title class="d-flex align-center justify-space-between">
                <span>Materialized table</span>
                <v-btn
                  size="small"
                  color="primary"
                  variant="tonal"
                  :disabled="!store.state.materializedCsv"
                  @click="downloadSelectedCsv"
                >
                  Download CSV
                </v-btn>
              </v-card-title>
              <v-card-text v-if="!materializedRows.length">No preview yet.</v-card-text>
              <v-card-text v-else>
                <v-data-table
                  :headers="materializedHeaders"
                  :items="materializedRows.slice(0, 50)"
                  density="compact"
                  :items-per-page="10"
                />
              </v-card-text>
            </v-card>
          </div>
        </DelayedMount>
      </v-col>
    </v-row>
    </template>
  </div>
</template>

<style scoped>
.qt-col {
  padding: 1px !important; /* = 2px gap between adjacent cards */
}

.jp-list {
  max-height: 70vh;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px; /* breathing room for scrollbar */
  scrollbar-gutter: stable;
}

.jp-list--online {
  max-height: 45vh;
}

.sql-pre {
  font-size: 12px;
  line-height: 1.2;
  max-height: 140px;
}

.mat-col--query {
  background: rgba(var(--v-theme-primary), 0.08);
}

.mat-col--header.mat-col--query {
  font-weight: 700;
}

.mat-col--cell.mat-col--query {
  font-weight: 600;
}

.qt-card {
  cursor: pointer;
  transition:
    box-shadow 0.15s ease,
    transform 0.15s ease,
    border-color 0.15s ease;
}

.qt-grid {
  /* Preserve Vuetify `v-row`/`v-col` layout while animating a list. */
  display: contents;
}

.qt-card--selected {
  border: 5px solid rgb(var(--v-theme-primary)) !important;
  transform: translateY(-1px);
}
</style>

