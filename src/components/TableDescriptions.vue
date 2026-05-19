<script setup>
import { computed } from 'vue'

const props = defineProps({
  dataLake: { type: Object, default: null },
  descriptions: { type: Object, default: () => ({}) },
})

function titleCase(s) {
  return String(s || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase())
}

const tables = computed(() => {
  const lake = props.dataLake || {}
  const descriptions = props.descriptions || {}
  const names = new Set([...Object.keys(lake), ...Object.keys(descriptions)])
  return [...names]
    .map((name) => {
      const rows = lake[name] || []
      const cols = rows?.[0] ? Object.keys(rows[0]) : []
      const rawDescription = descriptions?.[name]
      const desc =
        typeof rawDescription === 'string'
          ? rawDescription
          : rawDescription?.description || ''
      return {
        name,
        cols,
        desc,
      }
    })
    .sort((a, b) => a.name.localeCompare(b.name))
})
</script>

<template>
  <v-card variant="outlined">
    <v-card-title class="py-2">Table descriptions</v-card-title>
    <v-divider />
    <v-card-text class="pa-2">
      <div v-if="!tables.length" class="text-body-2 text-medium-emphasis">Select a data lake to see table descriptions.</div>

      <v-table v-else density="compact">
        <thead>
          <tr>
            <th style="width: 30%">Table</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tables" :key="t.name">
            <td>
              <div class="text-subtitle-2 font-weight-medium">{{ titleCase(t.name) }}</div>
            </td>
            <td>
              <div class="text-body-2 text-medium-emphasis">{{ t.desc || 'No backend description available.' }}</div>
            </td>
          </tr>
        </tbody>
      </v-table>
    </v-card-text>
  </v-card>
</template>
