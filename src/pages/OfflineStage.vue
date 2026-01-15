<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'

import DelayedMount from '../components/DelayedMount.vue'
import JoinPathCard from '../components/JoinPathCard.vue'
import TableDescriptions from '../components/TableDescriptions.vue'

const store = useStore()
const router = useRouter()

const SIMULATED_DELAY_MS = 3000

const uploadInput = ref(null)

const lake = computed(() => store.state.dataLake)
const uploadedFiles = computed({
  get: () => store.state.uploadedFiles,
  set: (v) => store.commit('setUploadedFiles', v),
})

const params = computed(() => store.state.params)
const joinEdges = computed(() => store.state.joinEdges || [])
const joinPathIndex = computed(() => store.state.joinPathIndex || [])

const preprocessingUiRunning = ref(false)
const preprocessRenderTrigger = ref(0)

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)))
}

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

function preprocessRowCount(pathId) {
  const sigParts = Object.entries(lake.value || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}:${Array.isArray(v) ? v.length : 0}x${v?.[0] ? Object.keys(v[0]).length : 0}`)
    .join('|')
  const p = store.state.params
  const pSig = [
    p?.semantic_type_similarity_threshold,
    p?.semantic_joinability_threshold,
    p?.equi_joinability_threshold,
    p?.max_join_path_length,
  ].join('|')
  const sig = `${sigParts}::${pSig}`
  const key = `${sig}::${pathId}`
  return store.state.preprocessRowCounts?.[key]
}

function goToOnlineStage() {
  // Keep stage semantics intact for any existing UI logic.
  if (store.state.stage < 2) store.commit('setStage', 2)
  router.push({ name: 'online' })
}
</script>

<template>
  <div class="pt-0 pb-6 px-0">
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
                <v-slider
                  class="flex-grow-1"
                  :model-value="params.semantic_type_similarity_threshold"
                  min="0"
                  max="1"
                  step="0.01"
                  thumb-label="always"
                  :disabled="!store.getters.canGoStage2"
                  hide-details
                  @update:model-value="store.commit('setParams', { semantic_type_similarity_threshold: $event })"
                />
              </v-col>
              <v-col cols="12" sm="6" md="2">
                <div class="text-caption text-medium-emphasis mb-1">Semantic Joinability</div>
                <v-slider
                  class="flex-grow-1"
                  :model-value="params.semantic_joinability_threshold"
                  min="0"
                  max="1"
                  step="0.01"
                  thumb-label="always"
                  :disabled="!store.getters.canGoStage2"
                  hide-details
                  @update:model-value="store.commit('setParams', { semantic_joinability_threshold: $event })"
                />
              </v-col>
              <v-col cols="12" sm="6" md="2">
                <div class="text-caption text-medium-emphasis mb-1">Equi Joinability</div>
                <v-slider
                  class="flex-grow-1"
                  :model-value="params.equi_joinability_threshold"
                  min="0"
                  max="1"
                  step="0.01"
                  thumb-label="always"
                  :disabled="!store.getters.canGoStage2"
                  hide-details
                  @update:model-value="store.commit('setParams', { equi_joinability_threshold: $event })"
                />
              </v-col>
              <v-col cols="12" sm="6" md="2">
                <div class="text-caption text-medium-emphasis mb-1">Max Join Path Length</div>
                <v-slider
                  class="flex-grow-1"
                  :model-value="params.max_join_path_length"
                  min="2"
                  max="10"
                  step="1"
                  thumb-label="always"
                  :disabled="!store.getters.canGoStage2"
                  hide-details
                  @update:model-value="store.commit('setParams', { max_join_path_length: $event })"
                />
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

        <v-expand-transition>
          <div v-if="store.state.preprocessed" class="d-flex justify-end mt-3">
            <transition name="mount-pop" appear>
              <v-btn
                color="primary"
                variant="tonal"
                :disabled="!store.getters.canGoStage3 || preprocessingUiRunning"
                @click="goToOnlineStage"
              >
                Go to Online Stage
              </v-btn>
            </transition>
          </div>
        </v-expand-transition>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.jp-list {
  max-height: 70vh;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px; /* breathing room for scrollbar */
  scrollbar-gutter: stable;
}
</style>

