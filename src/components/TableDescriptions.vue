<script setup>
import { computed } from 'vue'

const props = defineProps({
  dataLake: { type: Object, default: null },
})

function titleCase(s) {
  return String(s || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase())
}

function guessDescription(tableName, cols) {
  const n = String(tableName || '').toLowerCase()
  const c = (cols || []).map((x) => String(x).toLowerCase())

  if (n.includes('product')) return 'A catalog of products and their attributes.'
  if (n.includes('store')) return 'A list of stores/locations and their attributes (e.g., region).'
  if (n.includes('quarter') || n.includes('time')) return 'A time dimension table (quarters/years/labels).'
  if (n.includes('sales_amount')) return 'Sales amounts per sale/period (money metrics).'
  if (n.includes('sales_quant')) return 'Sales quantities per sale/period (count metrics).'
  if (n.includes('order_item')) return 'Line items that connect orders to products (quantities/prices).'
  if (n.includes('order')) return 'Orders placed by customers (order-level facts).'
  if (n.includes('customer')) return 'Customer profiles and attributes.'
  if (n.includes('shipment')) return 'Shipment/delivery records for orders.'

  if (c.some((x) => x.includes('amount') || x.includes('price'))) return 'A fact table with monetary measures.'
  if (c.some((x) => x.endsWith('_id'))) return 'A table with identifier columns that likely links to other tables.'
  return 'A table in the data lake.'
}

const tables = computed(() => {
  const lake = props.dataLake || {}
  return Object.entries(lake)
    .map(([name, rows]) => {
      const cols = rows?.[0] ? Object.keys(rows[0]) : []
      const desc = guessDescription(name, cols)
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
      <div v-if="!tables.length" class="text-body-2 text-medium-emphasis">Load a data lake to see table descriptions.</div>

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
              <div class="text-body-2 text-medium-emphasis">{{ t.desc }}</div>
            </td>
          </tr>
        </tbody>
      </v-table>
    </v-card-text>
  </v-card>
</template>

