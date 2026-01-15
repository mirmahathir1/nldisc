<template>
  <v-app>
    <v-main>
      <v-container fluid class="pt-0 pb-6 px-0">
        <router-view />
      </v-container>
    </v-main>
  </v-app>
</template>

<template-old>
  <v-app>
    <v-main>
      <v-container fluid class="pt-0 pb-6 px-0">
        <router-view />
      </v-container>
    </v-main>
  </v-app>
</template-old>

<script-old>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useStore } from 'vuex'

import DelayedMount from './components/DelayedMount.vue'
import JoinGraph from './components/JoinGraph.vue'
import JoinPathCard from './components/JoinPathCard.vue'
import TableDescriptions from './components/TableDescriptions.vue'

const store = useStore()

const SIMULATED_DELAY_MS = 3000

const uploadInput = ref(null)

const stage = computed({
  get: () => store.state.stage,
  set: (v) => store.commit('setStage', v),
})

const lake = computed(() => store.state.dataLake)
const uploadedFiles = computed({
  get: () => store.state.uploadedFiles,
  set: (v) => store.commit('setUploadedFiles', v),
})

function triggerCsvPicker() {
  uploadInput.value?.click?.()
}

function onCsvPicked(e) {
  const files = Array.from(e?.target?.files || [])
  uploadedFiles.value = files
  if (files.length) store.commit('loadDefaultDataLake')
  // Allow re-selecting same files
  if (e?.target) e.target.value = ''
}

const previewTableName = ref(null)

watch(
  lake,
  (v) => {
    const keys = v ? Object.keys(v).sort() : []
    previewTableName.value = keys[0] ?? null
  },
  { immediate: true },
)

function tableHeaders(rows) {
  const cols = rows?.[0] ? Object.keys(rows[0]) : []
  return cols.map((c) => ({ title: c, key: c }))
}

const lakeMeta = computed(() => {
  if (!lake.value) return []
  return Object.entries(lake.value)
    .map(([name, rows]) => {
      const cols = rows?.[0] ? Object.keys(rows[0]) : []
      return { table: name, rows: rows.length, cols: cols.length, columns: cols.join(', ') }
    })
    .sort((a, b) => a.table.localeCompare(b.table))
})

const previewRows = computed(() => {
  if (!lake.value || !previewTableName.value) return []
  return lake.value[previewTableName.value]?.slice(0, 25) ?? []
})

const params = computed(() => store.state.params)

const joinEdges = computed(() => store.state.joinEdges || [])
const joinPathIndex = computed(() => store.state.joinPathIndex || [])

const preprocessingUiRunning = ref(false)
const preprocessRenderTrigger = ref(0)
const queryTablesRenderTrigger = ref(0)
const resultsRenderTrigger = ref(0)

const queryTablesUiRunning = ref(false)
const joinSearchUiRunning = ref(false)

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)))
}

async function runPreprocessWithSimulatedProgress() {
  if (!store.getters.canGoStage2) return
  if (preprocessingUiRunning.value) return

  preprocessingUiRunning.value = true
  preprocessRenderTrigger.value += 1

  try {
    await store.dispatch('preprocess')
    await sleep(SIMULATED_DELAY_MS)
  } finally {
    preprocessingUiRunning.value = false
  }
}

onBeforeUnmount(() => {
  // no-op (kept to avoid churn if other hooks get added later)
})

function preprocessRowCount(pathId) {
  const sigParts = Object.entries(lake.value || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}:${Array.isArray(v) ? v.length : 0}x${v?.[0] ? Object.keys(v[0]).length : 0}`)
    .join('|')
  const p = store.state.params
  const pSig = [p?.semantic_type_similarity_threshold, p?.semantic_joinability_threshold, p?.equi_joinability_threshold, p?.max_join_path_length].join('|')
  const sig = `${sigParts}::${pSig}`
  const key = `${sig}::${pathId}`
  return store.state.preprocessRowCounts?.[key]
}

const nlQuery = computed({
  get: () => store.state.nlQuery,
  set: (v) => store.commit('setNlQuery', v),
})

const queryTables = computed(() => store.state.queryTables || [])
const selectedQtName = computed({
  get: () => store.state.selectedQtName,
  set: (v) => store.commit('setSelectedQtName', v),
})

const selectedEditedRows = computed(() => store.getters.selectedEditedRows || [])
const headerDrafts = ref({})
const removeColumnName = ref('')

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

function coerceCellValue(raw, current) {
  if (typeof current === 'number') {
    const n = Number(raw)
    return Number.isFinite(n) ? n : raw
  }
  return raw
}

const confirmedQtRows = computed(() => store.state.confirmedQtRows)
const requiredTables = computed(() => store.state.requiredTables || [])
const topPaths = computed(() => store.state.topPaths || [])
const selectedPathId = computed({
  get: () => store.state.selectedPathId,
  set: (v) => store.dispatch('selectPath', v),
})
const selectedPathTables = computed(() => store.state.selectedPathTables || [])
const selectedPathSql = computed(() => store.state.selectedPathSql || '')
const materializedRows = computed(() => store.state.materializedRows || [])

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

async function generateQueryTablesWithDelay() {
  if (queryTablesUiRunning.value) return
  queryTablesUiRunning.value = true
  queryTablesRenderTrigger.value += 1
  try {
    await store.dispatch('generateQueryTables')
    await sleep(SIMULATED_DELAY_MS)
  } finally {
    queryTablesUiRunning.value = false
  }
}

async function resubmitQueryTablesWithDelay() {
  if (queryTablesUiRunning.value) return
  queryTablesUiRunning.value = true
  queryTablesRenderTrigger.value += 1
  try {
    await store.dispatch('resubmitFromEdits')
    await sleep(SIMULATED_DELAY_MS)
  } finally {
    queryTablesUiRunning.value = false
  }
}

async function confirmAndRunJoinSearchWithDelay() {
  if (joinSearchUiRunning.value) return
  joinSearchUiRunning.value = true
  resultsRenderTrigger.value += 1
  try {
    store.commit('confirmEditedQueryTable')
    await store.dispatch('runJoinSearch')
    await sleep(SIMULATED_DELAY_MS)
  } finally {
    joinSearchUiRunning.value = false
  }
}
</script-old>

<template-old2>
  <v-app>
    <v-main>
      <v-container fluid class="pt-0 pb-6 px-0">
        <v-row no-gutters>
          <v-col cols="12" class="px-0">
            <v-card>
              <v-card-text>
                <input ref="uploadInput" type="file" accept=".csv" multiple class="d-none" @change="onCsvPicked" />
                <v-row dense class="align-end">
                  <v-col cols="12" sm="6" md="2">
                    <div class="d-flex align-center flex-wrap ga-3">
                      <div class="text-h5 font-weight-bold">NLDisc</div>
                      <v-btn color="primary" size="small" prepend-icon="mdi-upload" @click="triggerCsvPicker">
                        {{
                          uploadedFiles.length
                            ? `${uploadedFiles.length} CSV${uploadedFiles.length === 1 ? '' : 's'} selected`
                            : 'Choose CSVs'
                        }}
                      </v-btn>
                    </div>
                  </v-col>

                  <v-col cols="12" sm="6" md="2">
                    <div class="text-caption text-medium-emphasis mb-1">Semantic Type Similarity</div>
                    <div class="d-flex align-center ga-2">
                      <v-slider
                        class="flex-grow-1"
                        :model-value="params.semantic_type_similarity_threshold"
                        min="0"
                        max="1"
                        step="0.01"
                        :disabled="!store.getters.canGoStage2"
                        hide-details
                        @update:model-value="store.commit('setParams', { semantic_type_similarity_threshold: $event })"
                      />
                      <div class="text-caption text-medium-emphasis" style="width: 3.25rem; text-align: right">
                        {{ Number(params.semantic_type_similarity_threshold).toFixed(2) }}
                      </div>
                    </div>
                  </v-col>
                  <v-col cols="12" sm="6" md="2">
                    <div class="text-caption text-medium-emphasis mb-1">Semantic Joinability</div>
                    <div class="d-flex align-center ga-2">
                      <v-slider
                        class="flex-grow-1"
                        :model-value="params.semantic_joinability_threshold"
                        min="0"
                        max="1"
                        step="0.01"
                        :disabled="!store.getters.canGoStage2"
                        hide-details
                        @update:model-value="store.commit('setParams', { semantic_joinability_threshold: $event })"
                      />
                      <div class="text-caption text-medium-emphasis" style="width: 3.25rem; text-align: right">
                        {{ Number(params.semantic_joinability_threshold).toFixed(2) }}
                      </div>
                    </div>
                  </v-col>
                  <v-col cols="12" sm="6" md="2">
                    <div class="text-caption text-medium-emphasis mb-1">Equi Joinability</div>
                    <div class="d-flex align-center ga-2">
                      <v-slider
                        class="flex-grow-1"
                        :model-value="params.equi_joinability_threshold"
                        min="0"
                        max="1"
                        step="0.01"
                        :disabled="!store.getters.canGoStage2"
                        hide-details
                        @update:model-value="store.commit('setParams', { equi_joinability_threshold: $event })"
                      />
                      <div class="text-caption text-medium-emphasis" style="width: 3.25rem; text-align: right">
                        {{ Number(params.equi_joinability_threshold).toFixed(2) }}
                      </div>
                    </div>
                  </v-col>
                  <v-col cols="12" sm="6" md="2">
                    <div class="text-caption text-medium-emphasis mb-1">Max Join Path Length</div>
                    <div class="d-flex align-center ga-2">
                      <v-slider
                        class="flex-grow-1"
                        :model-value="params.max_join_path_length"
                        min="2"
                        max="10"
                        step="1"
                        :disabled="!store.getters.canGoStage2"
                        hide-details
                        @update:model-value="store.commit('setParams', { max_join_path_length: $event })"
                      />
                      <div class="text-caption text-medium-emphasis" style="width: 3.25rem; text-align: right">
                        {{ Number(params.max_join_path_length) }}
                      </div>
                    </div>
                  </v-col>

                  <v-col cols="12" md="2" class="d-flex flex-column align-end">
                    <v-btn
                      color="primary"
                      :loading="preprocessingUiRunning"
                      :disabled="!store.getters.canGoStage2 || preprocessingUiRunning"
                      @click="runPreprocessWithSimulatedProgress"
                    >
                      Run preprocessing
                    </v-btn>
                  </v-col>
                </v-row>
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>
        <v-row class="mt-0" no-gutters>
          <v-col cols="12" class="px-0">
            <DelayedMount :active="store.state.preprocessed" :trigger="preprocessRenderTrigger">
              <v-card>
                <v-card-text class="pt-0 pb-2 px-2">
                  <v-row dense>
                    <v-col cols="12" md="8">
                      <transition-group name="mount-pop" tag="div" class="jp-list" appear>
                        <JoinPathCard
                          v-for="(r, idx) in joinPathIndex.slice(0, 12)"
                          :key="r.path_id"
                          :path-id="r.path_id"
                          :tables-list="r.tables_list"
                          :edges="joinEdges"
                          :data-lake="lake"
                          :row-count="preprocessRowCount(r.path_id)"
                          :style="{ transitionDelay: `${Math.min(idx, 12) * 35}ms` }"
                          @request-row-count="store.dispatch('maybeComputeRowCount', $event)"
                        />
                      </transition-group>
                    </v-col>
                    <v-col cols="12" md="4">
                      <transition name="mount-pop" appear>
                        <TableDescriptions :data-lake="lake" style="transition-delay: 80ms" />
                      </transition>
                    </v-col>
                  </v-row>
                </v-card-text>
              </v-card>
            </DelayedMount>
          </v-col>
        </v-row>

        <!-- Stage 2 -->
        <v-expand-transition>
          <div v-if="stage >= 2 && !preprocessingUiRunning" class="mt-10">
              <div class="d-flex align-center ga-2 mb-3">
                <v-chip color="primary" variant="tonal" size="small">Online Stage</v-chip>
                <div class="text-h6">Query & Disambiguate</div>
              </div>
                <v-alert v-if="!store.getters.canGoStage3" type="warning" variant="tonal" class="mb-4">
                  Please run preprocessing above first.
                </v-alert>

                <v-row v-else>
                  <!-- Left column: NL query + query tables grid -->
                  <v-col cols="12" md="6">
                    <v-card>
                      <v-card-text>
                        <v-row dense class="align-center">
                          <v-col cols="12" md="5">
                            <v-textarea
                              v-model="nlQuery"
                              label="Natural LanguageQuery"
                              variant="outlined"
                              rows="3"
                              auto-grow
                            />
                          </v-col>

                          <v-col cols="12" md="7">
                            <div class="text-medium-emphasis mb-1">
                              Query table suggestions ({{ Number(params.query_table_suggestion_count) }})
                            </div>
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
                              :disabled="queryTablesUiRunning"
                              @click="generateQueryTablesWithDelay"
                            >
                              Generate query tables
                            </v-btn>
                          </v-col>
                        </v-row>
                      </v-card-text>
                    </v-card>

                    <v-card class="mt-4">
                      <v-card-title>Query tables</v-card-title>
                      <v-card-text v-if="!queryTables.length">Generate query tables to begin.</v-card-text>
                      <DelayedMount :active="!!queryTables.length" :trigger="queryTablesRenderTrigger">
                        <v-card-text>
                          <v-row dense>
                            <transition-group name="mount-pop" tag="div" class="qt-grid" appear>
                              <v-col
                                v-for="(qt, idx) in queryTables"
                                :key="qt.name"
                                cols="12"
                                md="6"
                                :style="{ transitionDelay: `${Math.min(idx, 12) * 35}ms` }"
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
                                          :disabled="queryTablesUiRunning"
                                          @click.stop="resubmitQueryTablesWithDelay"
                                        >
                                          Resubmit
                                        </v-btn>
                                        <v-btn
                                          size="x-small"
                                          color="primary"
                                          :loading="joinSearchUiRunning"
                                          :disabled="!selectedEditedRows.length || joinSearchUiRunning"
                                          @click.stop="confirmAndRunJoinSearchWithDelay"
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
                                            <v-btn
                                              size="x-small"
                                              variant="text"
                                              @click.stop="store.commit('deleteEditedQueryTableRow', { name: qt.name, rowIndex })"
                                            >
                                              Remove
                                            </v-btn>
                                          </td>
                                        </tr>
                                      </tbody>
                                    </v-table>

                                    <div v-if="editedRowsFor(qt.name).length > 5" class="text-caption text-medium-emphasis mt-1">
                                      Showing first 5 rows.
                                    </div>

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
                            :edges="joinEdges"
                            :data-lake="lake"
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
                          <v-card-text v-if="!selectedPathTables.length" class="pt-0 pb-2 px-2">
                            Select a join path from the list above.
                          </v-card-text>
                          <v-card-text v-else class="pt-0 pb-2 px-2">
                            <pre
                              class="pa-2 rounded bg-grey-lighten-4 sql-pre"
                              style="white-space: pre-wrap; overflow: auto"
                            >{{ selectedPathSql }}</pre>
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
                              :headers="tableHeaders(materializedRows)"
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
          </div>
        </v-expand-transition>
      </v-container>
    </v-main>
  </v-app>
</template-old2>

<style-old scoped>
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

:deep(.mount-pop-enter-active),
:deep(.mount-pop-leave-active) {
  transition:
    opacity 0.22s ease,
    transform 0.22s ease;
  will-change: opacity, transform;
}

:deep(.mount-pop-enter-from),
:deep(.mount-pop-leave-to) {
  opacity: 0;
  transform: translateY(10px);
}

:deep(.mount-pop-move) {
  transition: transform 0.22s ease;
}

.sql-pre {
  font-size: 12px;
  line-height: 1.2;
  max-height: 140px;
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
</style-old>
