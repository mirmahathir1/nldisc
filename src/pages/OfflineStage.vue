<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'

import DelayedMount from '../components/DelayedMount.vue'
import JoinPathCard from '../components/JoinPathCard.vue'
import TableDescriptions from '../components/TableDescriptions.vue'

const store = useStore()
const router = useRouter()

const lake = computed(() => store.state.dataLake)
const availableDatalakes = computed(() => store.state.availableDatalakes || [])
const selectedDatalake = computed({
  get: () => store.state.dataLakeName,
  set: (name) => store.dispatch('selectDataLake', name),
})
const dataLakeSummary = computed(() => store.state.dataLakeSummary)
const backendError = computed(() => store.state.backendError)

const params = computed(() => store.state.params)
const joinEdges = computed(() => store.state.joinEdges || [])
const joinPathIndex = computed(() => store.state.joinPathIndex || [])
const tableDescriptions = computed(() => store.state.tableDescriptions || {})

const preprocessingUiRunning = ref(false)
const preprocessRenderTrigger = ref(0)

onMounted(() => {
  store.dispatch('loadDatalakes')
})

async function runPreprocessWithSimulatedProgress() {
  if (!store.getters.canGoStage2) return
  if (preprocessingUiRunning.value) return

  preprocessingUiRunning.value = true
  preprocessRenderTrigger.value += 1

  try {
    await store.dispatch('preprocess')
  } finally {
    preprocessingUiRunning.value = false
  }
}

function preprocessRowCount(pathId) {
  const path = joinPathIndex.value.find((row) => row.path_id === pathId)
  return path?.row_count_estimate ?? path?.cardinality_estimate
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
            <v-row dense class="align-end">
              <v-col cols="12" sm="6" md="2">
                <div class="text-h5 font-weight-bold mb-2">NLDisc</div>
                <v-select
                  v-model="selectedDatalake"
                  :items="availableDatalakes"
                  :loading="store.state.dataLakeLoading"
                  density="compact"
                  label="Data Lake"
                  prepend-inner-icon="mdi-database"
                  hide-details
                />
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
                  :loading="preprocessingUiRunning || store.state.preprocessLoading"
                  :disabled="!store.getters.canGoStage2 || preprocessingUiRunning"
                  @click="runPreprocessWithSimulatedProgress"
                >
                  Run preprocessing
                </v-btn>
              </v-col>
            </v-row>

            <v-row v-if="dataLakeSummary" dense class="mt-2">
              <v-col cols="12">
                <div class="d-flex align-center flex-wrap ga-2">
                  <v-chip size="small" variant="tonal">{{ dataLakeSummary.table_count }} tables</v-chip>
                  <v-chip size="small" variant="tonal">{{ dataLakeSummary.total_rows }} rows</v-chip>
                  <v-chip
                    v-for="table in dataLakeSummary.tables"
                    :key="table.name"
                    size="small"
                    variant="outlined"
                  >
                    {{ table.name }} · {{ table.row_count }}
                  </v-chip>
                </div>
              </v-col>
            </v-row>

            <v-alert
              v-if="backendError"
              class="mt-3"
              density="compact"
              type="error"
              variant="tonal"
            >
              {{ backendError }}
            </v-alert>
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
                      :attributes="r.attributes"
                      :row-count="preprocessRowCount(r.path_id)"
                      :style="{ transitionDelay: `${Math.min(idx, 12) * 35}ms` }"
                    />
                  </transition-group>
                </v-col>
                <v-col cols="12" md="4">
                  <transition name="mount-pop" appear>
                    <TableDescriptions
                      :data-lake="lake"
                      :descriptions="tableDescriptions"
                      style="transition-delay: 80ms"
                    />
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
