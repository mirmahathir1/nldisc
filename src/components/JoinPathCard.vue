<script setup>
import { computed, onMounted, ref } from 'vue'

import JoinGraph from './JoinGraph.vue'

const props = defineProps({
  pathId: { type: String, required: true },
  tablesList: { type: Array, required: true }, // ["sales_amounts", ...]
  edges: { type: Array, required: true },
  dataLake: { type: Object, default: null },
  rowCount: { type: [Number, String], default: undefined }, // undefined -> not computed yet
  selected: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false },
  // Optional: columns from the confirmed query table, used for highlighting.
  queryColumns: { type: Array, default: () => [] },
})

const emit = defineEmits(['request-row-count', 'click'])

const showAllAttrs = ref(false)

const length = computed(() => props.tablesList?.length || 0)
const hops = computed(() => Math.max(0, (props.tablesList?.length || 0) - 1))

const allAttributes = computed(() => {
  const lake = props.dataLake || {}
  const out = []
  for (const t of props.tablesList || []) {
    const rows = lake?.[t]
    const cols = rows?.[0] ? Object.keys(rows[0]) : []
    for (const c of cols) out.push(c)
  }
  return Array.from(new Set(out))
})

const visibleAttributes = computed(() => (showAllAttrs.value ? allAttributes.value : allAttributes.value.slice(0, 5)))
const extraCount = computed(() => Math.max(0, allAttributes.value.length - visibleAttributes.value.length))

function norm(s) {
  return String(s ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
}

const queryColNorms = computed(() => new Set((props.queryColumns || []).map(norm).filter(Boolean)))

const highlightTables = computed(() => {
  const lake = props.dataLake || {}
  const q = queryColNorms.value
  if (!q.size) return []
  const out = new Set()
  for (const t of props.tablesList || []) {
    const rows = lake?.[t]
    const cols = rows?.[0] ? Object.keys(rows[0]) : []
    const colNorms = cols.map(norm)
    if (colNorms.some((c) => c && q.has(c))) out.add(t)
  }
  return [...out]
})

function isQueryAttribute(col) {
  const k = norm(col)
  return Boolean(k && queryColNorms.value.has(k))
}

function formatJoinPathLabel(pathId) {
  const raw = String(pathId ?? '').trim()
  const m = raw.match(/^(?:jp)[-_ ]?(\d+)$/i)
  if (!m) return raw
  const n = String(m[1] ?? '')
  const padded = n.length >= 3 ? n : n.padStart(3, '0')
  return `Join Path ${padded}`
}

const displayPathLabel = computed(() => formatJoinPathLabel(props.pathId))

const displayRowCount = computed(() => {
  if (props.rowCount === undefined) return '—'
  if (typeof props.rowCount === 'number') return props.rowCount >= 0 ? props.rowCount : '—'
  return props.rowCount
})

onMounted(() => {
  if (props.rowCount === undefined) {
    emit('request-row-count', { pathId: props.pathId, pathTables: props.tablesList })
  }
})
</script>

<template>
  <v-card
    variant="outlined"
    class="mb-1"
    :class="[{ 'jp-card--selected': selected, 'jp-card--clickable': clickable }]"
    :elevation="selected ? 16 : 0"
    @click="emit('click')"
  >
    <v-card-text class="pa-1">
      <div class="jp-grid">
        <!-- Left (1/8): metadata -->
        <div class="jp-left">
          <div class="text-caption font-weight-medium">{{ displayPathLabel }}</div>
          <div class="jp-metrics mt-1">
            <div class="jp-metric">
              <div class="jp-k">rows</div>
              <div class="jp-v">{{ displayRowCount }}</div>
            </div>
            <div class="jp-metric">
              <div class="jp-k">cols</div>
              <div class="jp-v">{{ allAttributes.length }}</div>
            </div>
            <div class="jp-metric">
              <div class="jp-k">len</div>
              <div class="jp-v">{{ length }}</div>
            </div>
            <div class="jp-metric">
              <div class="jp-k">hops</div>
              <div class="jp-v">{{ hops }}</div>
            </div>
          </div>
        </div>

        <!-- Right (7/8): attributes + graph -->
        <div class="jp-right">
          <div class="d-flex align-center flex-wrap ga-1 mb-1">
            <v-chip
              v-for="a in visibleAttributes"
              :key="a"
              size="x-small"
              :variant="isQueryAttribute(a) ? 'flat' : 'tonal'"
              :color="isQueryAttribute(a) ? 'primary' : undefined"
              class="text-caption"
            >
              {{ a }}
            </v-chip>

            <v-btn
              v-if="extraCount > 0 && !showAllAttrs"
              size="x-small"
              variant="text"
              class="px-1"
              @click="showAllAttrs = true"
            >
              +{{ extraCount }} attributes
            </v-btn>
          </div>

          <div class="rounded border pa-1">
            <JoinGraph :path="tablesList" :edges="edges" :height="45" :highlight-nodes="highlightTables" />
          </div>
        </div>
      </div>
    </v-card-text>
  </v-card>
</template>

<style scoped>
.jp-card--clickable {
  cursor: pointer;
}

.jp-card--selected {
  border: 5px solid rgb(var(--v-theme-primary)) !important;
}

.jp-grid {
  display: grid;
  /* Keep ~1/8 + 7/8, but enforce a minimum to prevent overlap */
  grid-template-columns: minmax(150px, 12.5%) minmax(0, 1fr);
  gap: 4px;
  align-items: start;
}

.jp-left {
  min-width: 0;
  overflow: hidden;
}

.jp-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px 4px;
}

.jp-metric {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 6px;
  padding: 2px 4px;
  background: transparent;
}

.jp-k {
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(0, 0, 0, 0.55);
  line-height: 1.1;
}

.jp-v {
  font-size: 12px;
  font-weight: 700;
  line-height: 1.1;
  color: rgba(0, 0, 0, 0.8);
}

.jp-right {
  min-width: 0;
}

@media (max-width: 960px) {
  .jp-grid {
    grid-template-columns: 1fr;
  }
}

:deep(.v-chip) {
  padding-inline: 6px;
}
</style>

