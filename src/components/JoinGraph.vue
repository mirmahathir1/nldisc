<script setup>
import * as d3 from 'd3'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  // Array of table names in path order: ["sales_amounts","sales_quantities","products"]
  path: { type: Array, required: true },
  // Join edges list from store (buildJoinGraph): [{left_table,left_col,right_table,right_col,...}]
  edges: { type: Array, required: true },
  height: { type: Number, default: 140 },
  // Optional list of table names to highlight (e.g., tables containing query columns).
  highlightNodes: { type: Array, default: () => [] },
})

const rootEl = ref(null)
let svg = null

function edgeFor(a, b) {
  return (
    props.edges.find((e) => e.left_table === a && e.right_table === b) ||
    props.edges.find((e) => e.left_table === b && e.right_table === a) ||
    null
  )
}

function render() {
  if (!rootEl.value) return
  const containerW = rootEl.value.clientWidth || 800
  const height = props.height

  const hl = new Set((props.highlightNodes || []).map((t) => String(t ?? '').toLowerCase()))

  const nodeH = 22
  const nodeRx = 7
  const minNodeW = 76
  const maxNodeW = 260
  const nodePaddingX = 12
  const approxCharW = 7.2 // px at 12px font-size (rough)
  // Keep roughly the same visual spacing as before (240 center-to-center with 76px nodes => ~164px edge gap)
  const baseEdgeGap = 164
  const labelPaddingX = 18
  const approxLabelCharW = 6.6 // px at 12px font-size (rough)
  const maxExtraGap = 260 // cap edge stretch so paths don't explode horizontally

  // Cleanup previous
  d3.select(rootEl.value).selectAll('*').remove()

  const path = Array.isArray(props.path) ? props.path : []
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
  const nodeWidthFor = (name) => {
    const s = String(name ?? '')
    const w = nodePaddingX * 2 + s.length * approxCharW
    return clamp(Math.round(w), minNodeW, maxNodeW)
  }

  // Precompute edge labels so we can size the gaps between nodes accordingly.
  const edgeLabels = []
  for (let i = 0; i < path.length - 1; i++) {
    const a = path[i]
    const b = path[i + 1]
    const e = edgeFor(a, b)
    const label = e ? `${e.left_col}, ${e.right_col}` : ''
    edgeLabels.push(label)
  }
  const edgeGapFor = (label) => {
    const s = String(label ?? '')
    if (!s) return baseEdgeGap
    const labelW = Math.round(labelPaddingX * 2 + s.length * approxLabelCharW)
    const extra = clamp(labelW - 120, 0, maxExtraGap) // 120px label room is "free" before stretching
    return baseEdgeGap + extra
  }

  const nodes = []
  let left = 12 // relative to SVG; will incorporate margin.left below
  for (let i = 0; i < path.length; i++) {
    const id = path[i]
    const w = nodeWidthFor(id)
    nodes.push({ id, i, w, left })
    // Add gap only if there's an outgoing edge to the next node.
    if (i < path.length - 1) left += w + edgeGapFor(edgeLabels[i])
  }

  const margin = { left: 12, right: 12, top: 10, bottom: 10 }
  const contentW =
    margin.left +
    margin.right +
    (nodes.length ? nodes[nodes.length - 1].left + nodes[nodes.length - 1].w : 0)
  const svgW = Math.max(containerW, contentW)
  const y = height / 2
  const xForNode = (n) => margin.left + n.left + n.w / 2

  svg = d3
    .select(rootEl.value)
    .append('svg')
    .attr('width', svgW)
    .attr('height', height)

  const centerById = new Map(nodes.map((n) => [n.id, xForNode(n)]))

  const links = []
  for (let i = 0; i < path.length - 1; i++) {
    const a = path[i]
    const b = path[i + 1]
    links.push({ source: a, target: b, label: edgeLabels[i] })
  }

  // Arrow marker
  svg
    .append('defs')
    .append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 10)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#4F46E5')

  // Links
  svg
    .append('g')
    .selectAll('line')
    .data(links)
    .enter()
    .append('line')
    .attr('x1', (d) => centerById.get(d.source) ?? 0)
    .attr('x2', (d) => centerById.get(d.target) ?? 0)
    .attr('y1', y)
    .attr('y2', y)
    .attr('stroke', '#4F46E5')
    .attr('stroke-width', 2)
    .attr('marker-end', 'url(#arrow)')

  // Edge labels
  svg
    .append('g')
    .selectAll('text')
    .data(links)
    .enter()
    .append('text')
    .attr('x', (d) => ((centerById.get(d.source) ?? 0) + (centerById.get(d.target) ?? 0)) / 2)
    .attr('y', y - 7)
    .attr('text-anchor', 'middle')
    .attr('fill', '#111827')
    .attr('font-size', 12)
    .text((d) => d.label)

  // Nodes
  const nodeG = svg.append('g').selectAll('g').data(nodes).enter().append('g')

  nodeG
    .append('rect')
    .attr('x', (d) => xForNode(d) - d.w / 2)
    .attr('y', y - nodeH / 2)
    .attr('width', (d) => d.w)
    .attr('height', nodeH)
    .attr('rx', nodeRx)
    .attr('fill', (d) => (hl.has(String(d.id ?? '').toLowerCase()) ? '#FEF3C7' : '#EEF2FF'))
    .attr('stroke', (d) => (hl.has(String(d.id ?? '').toLowerCase()) ? '#D97706' : '#6366F1'))
    .attr('stroke-width', (d) => (hl.has(String(d.id ?? '').toLowerCase()) ? 2 : 1))

  nodeG
    .append('text')
    .attr('x', (d) => xForNode(d))
    .attr('y', y + 2.5)
    .attr('text-anchor', 'middle')
    .attr('font-size', 12)
    .attr('fill', '#111827')
    .text((d) => d.id)
}

let ro = null
onMounted(() => {
  render()
  ro = new ResizeObserver(() => render())
  ro.observe(rootEl.value)
})

onBeforeUnmount(() => {
  ro?.disconnect()
})

watch(
  () => [props.path, props.edges, props.highlightNodes],
  () => render(),
  { deep: true },
)
</script>

<template>
  <div ref="rootEl" class="join-graph-root" />
</template>

<style scoped>
.join-graph-root {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-gutter: stable;
}
</style>

