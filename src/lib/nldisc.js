// Core logic ported from app.py (Streamlit) into browser-friendly JS.
// Data tables are arrays of row objects: [{col: value, ...}, ...]

function xmur3(str) {
  // Deterministic string hash → 32-bit unsigned int
  let h = 1779033703 ^ str.length
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353)
    h = (h << 13) | (h >>> 19)
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507)
    h = Math.imul(h ^ (h >>> 13), 3266489909)
    h ^= h >>> 16
    return h >>> 0
  }
}

function mulberry32(a) {
  return () => {
    let t = (a += 0x6d2b79f5)
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function randInt(rng, lo, hiInclusive) {
  return lo + Math.floor(rng() * (hiInclusive - lo + 1))
}

function randNormal(rng) {
  // Box–Muller
  let u = 0
  let v = 0
  while (u === 0) u = rng()
  while (v === 0) v = rng()
  return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v)
}

export function seedFromString(s) {
  return xmur3(String(s))()
}

export function makeDefaultDataLake(seed = 7) {
  const rng = mulberry32(seed >>> 0)

  const products = [
    { product_id: 1, product_name: 'Road Bike', category: 'Bikes' },
    { product_id: 2, product_name: 'Mountain Bike', category: 'Bikes' },
    { product_id: 3, product_name: 'Helmet', category: 'Safety' },
    { product_id: 4, product_name: 'Cycling Jersey', category: 'Apparel' },
    { product_id: 5, product_name: 'Water Bottle', category: 'Accessories' },
    { product_id: 6, product_name: 'Bike Lock', category: 'Accessories' },
    { product_id: 7, product_name: 'Tire Pump', category: 'Accessories' },
    { product_id: 8, product_name: 'Chain Lube', category: 'Accessories' },
    { product_id: 9, product_name: 'Gloves', category: 'Apparel' },
    { product_id: 10, product_name: 'Sunglasses', category: 'Accessories' },
  ]

  const stores = [
    { store_id: 1, store_name: 'Downtown', region: 'West' },
    { store_id: 2, store_name: 'Mall', region: 'West' },
    { store_id: 3, store_name: 'Airport', region: 'East' },
    { store_id: 4, store_name: 'Suburb', region: 'South' },
    { store_id: 5, store_name: 'Outlet', region: 'North' },
  ]

  const quarters = []
  let qid = 1
  for (const year of [2024, 2025]) {
    for (const q of [1, 2, 3, 4]) {
      quarters.push({
        quarter_id: qid,
        year,
        quarter: `Q${q}`,
        quarter_label: `${year}-Q${q}`,
      })
      qid += 1
    }
  }

  const nSales = 180
  const sales_quantities = []
  for (let i = 0; i < nSales; i++) {
    sales_quantities.push({
      sale_id: 10001 + i,
      product_id: randInt(rng, 1, 10),
      store_id: randInt(rng, 1, 5),
      quarter_id: randInt(rng, 1, quarters.length),
      quantity: randInt(rng, 1, 6),
    })
  }

  const priceMap = {
    1: 899.0,
    2: 1099.0,
    3: 49.0,
    4: 79.0,
    5: 12.0,
    6: 25.0,
    7: 35.0,
    8: 9.0,
    9: 29.0,
    10: 59.0,
  }

  const sales_amounts = sales_quantities.map((r) => {
    const unit = priceMap[r.product_id] ?? 0.0
    const noise = randNormal(rng) * 0.06
    const total_amount = Math.round(r.quantity * unit * (1.0 + noise) * 100) / 100
    return {
      sale_id: r.sale_id,
      quarter_id: r.quarter_id,
      total_amount,
      currency: 'USD',
    }
  })

  return {
    products,
    stores,
    quarters,
    sales_quantities,
    sales_amounts,
  }
}

export function buildJoinGraph(params) {
  const edges = [
    {
      left_table: 'sales_quantities',
      left_col: 'product_id',
      right_table: 'products',
      right_col: 'product_id',
      kind: 'equi',
      confidence: 0.99,
    },
    {
      left_table: 'sales_quantities',
      left_col: 'store_id',
      right_table: 'stores',
      right_col: 'store_id',
      kind: 'equi',
      confidence: 0.98,
    },
    {
      left_table: 'sales_quantities',
      left_col: 'quarter_id',
      right_table: 'quarters',
      right_col: 'quarter_id',
      kind: 'equi',
      confidence: 0.97,
    },
    {
      left_table: 'sales_amounts',
      left_col: 'sale_id',
      right_table: 'sales_quantities',
      right_col: 'sale_id',
      kind: 'equi',
      confidence: 0.96,
    },
    {
      left_table: 'sales_amounts',
      left_col: 'quarter_id',
      right_table: 'quarters',
      right_col: 'quarter_id',
      kind: 'semantic',
      confidence: 0.75,
    },
  ]

  const equiThr = Number(params?.equi_joinability_threshold ?? 0.9)
  const semThr = Number(params?.semantic_joinability_threshold ?? 0.75)
  return edges.filter((e) => (e.kind === 'equi' ? e.confidence >= equiThr : e.confidence >= semThr))
}

function otherTable(edge, table) {
  if (table === edge.left_table) return edge.right_table
  if (table === edge.right_table) return edge.left_table
  throw new Error(`Table ${table} not part of edge`)
}

function adjacency(edges) {
  const adj = new Map()
  for (const e of edges) {
    if (!adj.has(e.left_table)) adj.set(e.left_table, [])
    if (!adj.has(e.right_table)) adj.set(e.right_table, [])
    adj.get(e.left_table).push(e)
    adj.get(e.right_table).push(e)
  }
  return adj
}

export function enumerateSimplePaths(edges, maxLen) {
  const adj = adjacency(edges)
  const tables = [...adj.keys()].sort()
  const paths = []

  const dfs = (cur, visited) => {
    if (visited.length >= 2) paths.push([...visited])
    if (visited.length >= maxLen) return
    for (const e of adj.get(cur) || []) {
      const nxt = otherTable(e, cur)
      if (visited.includes(nxt)) continue
      visited.push(nxt)
      dfs(nxt, visited)
      visited.pop()
    }
  }

  for (const t of tables) dfs(t, [t])

  // Deduplicate by canonical (path or reversed path)
  const seen = new Set()
  const uniq = []
  for (const p of paths) {
    const key = p.join('|')
    const rkey = [...p].reverse().join('|')
    const canon = key < rkey ? key : rkey
    if (seen.has(canon)) continue
    seen.add(canon)
    uniq.push(p)
  }
  return uniq
}

export function scorePath(path, edges) {
  const map = edgeLookup(edges)
  const confs = []
  for (let i = 0; i < path.length - 1; i++) {
    const e = map.get(`${path[i]}→${path[i + 1]}`)
    if (e) confs.push(e.confidence)
  }
  const avg = confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : 0.0
  const lengthPenalty = 0.02 * Math.max(0, path.length - 2)
  return avg - lengthPenalty
}

export function buildJoinPathIndex(edges, maxPathLen) {
  const paths = enumerateSimplePaths(edges, maxPathLen)
  const rows = paths.map((p, idx) => ({
    path_id: `JP-${String(idx + 1).padStart(3, '0')}`,
    tables: p.join(' → '),
    tables_list: p,
    length: p.length,
    score: Math.round(scorePath(p, edges) * 10000) / 10000,
  }))
  rows.sort((a, b) => (b.score !== a.score ? b.score - a.score : a.length - b.length))
  return rows
}

export function buildSemanticTypeIndex(dataLake, seed) {
  const rng = mulberry32(seed >>> 0)

  const inferType = (col, sampleValue) => {
    const lc = String(col).toLowerCase()
    if (lc.endsWith('_id')) return 'Identifier'
    if (lc.includes('amount') || lc.includes('price')) return 'Money'
    if (lc.includes('quarter') || lc.includes('year')) return 'TimePeriod'
    if (typeof sampleValue === 'number') return 'Number'
    return 'Text'
  }

  const rows = []
  for (const [tname, table] of Object.entries(dataLake || {})) {
    const cols = columnsForTable(table)
    for (const col of cols) {
      const sample = table?.[0]?.[col]
      const stype = inferType(col, sample)
      const emb = Array.from({ length: 8 }, () => Math.round(randNormal(rng) * 1000) / 1000)
      const ex = table.slice(0, 3).map((r) => String(r[col])).join(', ')
      rows.push({
        table: tname,
        column: col,
        semantic_type: stype,
        example_values: ex,
        embedding_8d: emb,
      })
    }
  }
  return rows
}

export function parseNlQuery(query) {
  const q = String(query || '').toLowerCase()
  const wants_sales = q.includes('sales') || q.includes('revenue') || q.includes('amount')
  const wants_products = q.includes('product') || q.includes('sku') || q.includes('item')
  const wants_store = q.includes('store') || q.includes('region')
  const wants_quarter =
    q.includes('quarter') || q.includes('quarters') || q.includes('q1') || q.includes('q2') || q.includes('q3') || q.includes('q4')
  const wants_past = q.includes('past') || q.includes('last') || q.includes('previous')

  const semantic_types = []
  if (wants_sales) semantic_types.push('Money')
  if (wants_quarter) semantic_types.push('TimePeriod')
  if (wants_products) semantic_types.push('Text')
  if (wants_store) semantic_types.push('Text')

  const examples = []
  if (wants_quarter) examples.push('2025-Q1', '2025-Q2')
  if (wants_sales) examples.push('1500.00', '3200.50')
  if (wants_products) examples.push('Road Bike', 'Helmet')

  const preds = []
  if (wants_past && wants_quarter) preds.push({ field: 'quarter_label', op: 'IN', value: 'past quarters' })

  return {
    semantic_types: semantic_types.length ? semantic_types : ['(unknown)'],
    example_values: examples.length ? examples : ['(none)'],
    selection_predicates: preds.length ? preds : [],
    signals: { wants_sales, wants_products, wants_store, wants_quarter },
  }
}

function columnsForTable(table) {
  if (!Array.isArray(table) || table.length === 0) return []
  return Object.keys(table[0])
}

function isNumericColumn(table, col) {
  for (const r of table || []) {
    const v = r?.[col]
    if (v === null || v === undefined || v === '') continue
    return typeof v === 'number' && Number.isFinite(v)
  }
  return false
}

function applyPredicatesToQueryTables(queryTables, predicates, seed) {
  if (!predicates?.length) return queryTables
  const rng = mulberry32((seed ^ 0xc0ffee) >>> 0)

  const adjustValue = (x, op, v) => {
    if (typeof x !== 'number' || !Number.isFinite(x)) return x
    if (op === '>') return Math.max(x, v + randInt(rng, 1, 250))
    if (op === '<') return Math.max(Math.min(x, v - randInt(rng, 1, 250)), 0.0)
    if (op === '==' || op === '=') return Number(v)
    return x
  }

  return queryTables.map((qt) => {
    const rows = qt.rows.map((r) => {
      const out = { ...r }
      for (const pred of predicates) {
        const field = String(pred?.field || '')
        if (!field || !(field in out)) continue
        out[field] = adjustValue(out[field], String(pred?.op || '>'), Number(pred?.value ?? 0))
      }
      return out
    })
    return { ...qt, rows }
  })
}

export function generateQueryTables(query, seed, predicates = [], suggestionCount = 4, hints = null) {
  const rng = mulberry32(seed >>> 0)
  const parsed = parseNlQuery(query)
  const s = { ...(parsed.signals || {}) }

  // If the user resubmits an edited query table, treat any detected columns as hints.
  // This lets the demo "learn" from edits (e.g., adding Product Name) even if the NL query didn't mention it.
  const hs = hints?.signals || {}
  for (const k of ['wants_sales', 'wants_products', 'wants_store', 'wants_quarter']) {
    if (hs?.[k]) s[k] = true
  }

  const productColName = String(hints?.columnNames?.product_name || 'product_name')
  const storeColName = String(hints?.columnNames?.store_name || 'store_name')

  const productSamples =
    hints?.samples?.product_names?.length ? hints.samples.product_names : ['Road Bike', 'Helmet', 'Cycling Jersey', 'Mountain Bike']
  const storeSamples = hints?.samples?.store_names?.length ? hints.samples.store_names : ['Downtown', 'Mall', 'Outlet', 'Airport']

  // Requirement: in resubmitted suggestion generation, include Product Name on every suggested query table.
  const forceProductEverywhere = Boolean(hints) && (hs?.wants_products || productSamples.length > 0)

  const base_quarters = [{ quarter_label: '2025-Q1' }, { quarter_label: '2025-Q2' }, { quarter_label: '2025-Q3' }]

  const qt1 = base_quarters.map((r, i) => {
    const out = { ...r }
    if (s.wants_sales) out.total_amount = Number(randInt(rng, 900, 4500))
    if (s.wants_products || forceProductEverywhere) out[productColName] = productSamples[i % productSamples.length]
    return out
  })

  const qt2 = base_quarters.map((r, i) => {
    const out = { ...r }
    if (s.wants_sales) out.total_amount = Number(randInt(rng, 500, 9000))
    out[storeColName] = storeSamples[i % storeSamples.length]
    if (forceProductEverywhere) out[productColName] = productSamples[(i + 1) % productSamples.length]
    return out
  })

  const qt3 = [
    // For the initial suggestions, make Query Table 3 vary its "3rd column":
    // - If product is desired/forced (e.g., after resubmit hints), use Product Name.
    // - Otherwise, use a different column (Store Name) instead of Product Name.
    {
      ...(s.wants_products || forceProductEverywhere
        ? { [productColName]: productSamples[0] ?? 'Road Bike' }
        : { [storeColName]: storeSamples[0] ?? 'Downtown' }),
      quarter_label: '2025-Q1',
      total_amount: Number(randInt(rng, 1200, 7000)),
    },
    {
      ...(s.wants_products || forceProductEverywhere
        ? { [productColName]: productSamples[1] ?? 'Mountain Bike' }
        : { [storeColName]: storeSamples[1] ?? 'Mall' }),
      quarter_label: '2025-Q1',
      total_amount: Number(randInt(rng, 1200, 7000)),
    },
    {
      ...(s.wants_products || forceProductEverywhere
        ? { [productColName]: productSamples[2] ?? 'Helmet' }
        : { [storeColName]: storeSamples[2] ?? 'Outlet' }),
      quarter_label: '2025-Q2',
      total_amount: Number(randInt(rng, 1200, 7000)),
    },
  ]

  const qt4 = [
    {
      quarter_label: '2024-Q4',
      total_amount: Number(randInt(rng, 800, 5000)),
      currency: 'USD',
      ...(forceProductEverywhere ? { [productColName]: productSamples[0] ?? 'Road Bike' } : {}),
    },
    {
      quarter_label: '2025-Q1',
      total_amount: Number(randInt(rng, 800, 5000)),
      currency: 'USD',
      ...(forceProductEverywhere ? { [productColName]: productSamples[1] ?? 'Helmet' } : {}),
    },
    {
      quarter_label: '2025-Q2',
      total_amount: Number(randInt(rng, 800, 5000)),
      currency: 'USD',
      ...(forceProductEverywhere ? { [productColName]: productSamples[2] ?? 'Cycling Jersey' } : {}),
    },
  ]

  const qts = [
    { name: 'Query Table 1 (balanced)', rows: qt1 },
    { name: 'Query Table 2 (by store)', rows: qt2 },
    { name: 'Query Table 3 (matches sales + quarter + product)', rows: qt3 },
    { name: 'Query Table 4 (sales-only)', rows: qt4 },
  ]

  const target = Math.max(1, Math.min(10, Number(suggestionCount || 4)))
  if (target > qts.length) {
    for (let i = qts.length + 1; i <= target; i++) {
      const v = base_quarters.map((r) => ({ ...r }))
      const pick = (i - 1) % 3
      for (let ri = 0; ri < v.length; ri++) {
        if (s.wants_sales) {
          const lo = randInt(rng, 400, 1400)
          const hi = randInt(rng, 4500, 12000)
          v[ri].total_amount = Number(randInt(rng, lo, hi))
        }
        if (pick === 0) v[ri][productColName] = productSamples[ri % productSamples.length]
        else if (pick === 1) v[ri][storeColName] = storeSamples[ri % storeSamples.length]
        else v[ri].currency = 'USD'

        if (forceProductEverywhere && !(productColName in v[ri])) {
          v[ri][productColName] = productSamples[(ri + i) % productSamples.length]
        }
      }
      qts.push({ name: `Query Table ${i}`, rows: v })
    }
  }

  return applyPredicatesToQueryTables(qts.slice(0, target), predicates, seed)
}

export function inferCandidateTablesFromQueryTable(table) {
  const cols = columnsForTable(table).map((c) => c.toLowerCase())
  const candidates = new Set()
  if (cols.some((c) => c.includes('product'))) candidates.add('products')
  if (cols.some((c) => c.includes('store') || c.includes('region'))) candidates.add('stores')
  if (cols.some((c) => c.includes('quarter') || c.includes('year'))) candidates.add('quarters')
  if (cols.some((c) => c.includes('amount') || c.includes('currency'))) candidates.add('sales_amounts')
  if (candidates.has('sales_amounts') && candidates.has('products')) candidates.add('sales_quantities')
  return [...candidates].sort()
}

export function findTopJoinPaths(joinPathIndex, requiredTables, k) {
  const req = new Set(requiredTables || [])
  const covers = (tablesStr) => {
    const tables = String(tablesStr)
      .split('→')
      .map((t) => t.trim())
    return [...req].every((t) => tables.includes(t))
  }
  const kk = Math.max(0, Number(k || 0))
  const all = joinPathIndex || []
  const filtered = all.filter((r) => covers(r.tables))
  if (filtered.length >= kk) return filtered.slice(0, kk)

  // Demo-friendly fallback: if strict coverage yields too few paths, pad with the next-best
  // join paths (by precomputed score order) so the UI always has enough options.
  const out = filtered.slice(0, kk)
  const seen = new Set(out.map((r) => r?.path_id))
  for (const r of all) {
    if (out.length >= kk) break
    const id = r?.path_id
    if (!id || seen.has(id)) continue
    out.push(r)
    seen.add(id)
  }
  return out
}

export function edgeLookup(edges) {
  const m = new Map()
  for (const e of edges || []) {
    m.set(`${e.left_table}→${e.right_table}`, e)
    m.set(`${e.right_table}→${e.left_table}`, e)
  }
  return m
}

function joinCols(edge, left, right) {
  if (left === edge.left_table && right === edge.right_table) {
    return [
      [edge.left_table, edge.left_col],
      [edge.right_table, edge.right_col],
    ]
  }
  if (left === edge.right_table && right === edge.left_table) {
    return [
      [edge.right_table, edge.right_col],
      [edge.left_table, edge.left_col],
    ]
  }
  throw new Error(`Edge does not connect ${left} -> ${right}`)
}

function prefixRow(row, prefix) {
  const out = {}
  for (const [k, v] of Object.entries(row)) out[`${prefix}.${k}`] = v
  return out
}

function innerJoin(leftRows, rightRows, leftKey, rightKey) {
  const index = new Map()
  for (const r of rightRows) {
    const v = r[rightKey]
    if (!index.has(v)) index.set(v, [])
    index.get(v).push(r)
  }
  const out = []
  for (const l of leftRows) {
    const v = l[leftKey]
    const matches = index.get(v)
    if (!matches) continue
    for (const r of matches) out.push({ ...l, ...r })
  }
  return out
}

export function materializePath(dataLake, path, edges, limit = 2000) {
  const m = edgeLookup(edges)
  let df = (dataLake?.[path[0]] || []).map((r) => prefixRow(r, path[0]))

  for (let i = 0; i < path.length - 1; i++) {
    const left_t = path[i]
    const right_t = path[i + 1]
    const e = m.get(`${left_t}→${right_t}`)
    if (!e) throw new Error(`No edge for ${left_t}→${right_t}`)
    const [[lt, lc], [rt, rc]] = joinCols(e, left_t, right_t)

    const rightDf = (dataLake?.[right_t] || []).map((r) => prefixRow(r, right_t))
    const leftKey = `${lt}.${lc}`
    const rightKey = `${rt}.${rc}`
    df = innerJoin(df, rightDf, leftKey, rightKey)
  }

  return df.slice(0, limit)
}

export function countRowsForPath(dataLake, path, edges) {
  const m = edgeLookup(edges)
  const needed = Object.fromEntries(path.map((t) => [t, new Set()]))
  for (let i = 0; i < path.length - 1; i++) {
    const e = m.get(`${path[i]}→${path[i + 1]}`)
    if (!e) continue
    const [[lt, lc], [rt, rc]] = joinCols(e, path[i], path[i + 1])
    needed[lt].add(lc)
    needed[rt].add(rc)
  }

  const pickCols = (rows, cols) =>
    rows.map((r) => {
      const o = {}
      for (const c of cols) o[c] = r[c]
      return o
    })

  let df = pickCols(dataLake?.[path[0]] || [], [...needed[path[0]]]).map((r) => prefixRow(r, path[0]))
  for (let i = 0; i < path.length - 1; i++) {
    const left_t = path[i]
    const right_t = path[i + 1]
    const e = m.get(`${left_t}→${right_t}`)
    if (!e) return 0
    const [[lt, lc], [rt, rc]] = joinCols(e, left_t, right_t)

    const rightDf = pickCols(dataLake?.[right_t] || [], [...needed[right_t]]).map((r) => prefixRow(r, right_t))
    df = innerJoin(df, rightDf, `${lt}.${lc}`, `${rt}.${rc}`)
  }
  return df.length
}

export function sqlForPath(path, edges) {
  const m = edgeLookup(edges)
  const aliases = Object.fromEntries(path.map((t, i) => [t, `t${i + 1}`]))
  const lines = ['SELECT', '  *', `FROM ${path[0]} ${aliases[path[0]]}`]
  for (let i = 0; i < path.length - 1; i++) {
    const left_t = path[i]
    const right_t = path[i + 1]
    const e = m.get(`${left_t}→${right_t}`)
    if (!e) continue
    const [[lt, lc], [rt, rc]] = joinCols(e, left_t, right_t)
    lines.push(`JOIN ${right_t} ${aliases[right_t]} ON ${aliases[lt]}.${lc} = ${aliases[rt]}.${rc}`)
  }
  return `${lines.join('\n')};`
}

export function applyPredicatesToMaterialized(rows, predicates) {
  let out = rows
  for (const pred of predicates || []) {
    const field = String(pred?.field || '')
    if (!field) continue
    const candidates = out.length ? Object.keys(out[0]).filter((c) => c.endsWith(`.${field}`) || c === field) : []
    if (!candidates.length) continue
    const c = candidates[0]
    const v = Number(pred?.value ?? 0)
    const op = String(pred?.op || '>')
    if (op === '>') out = out.filter((r) => Number(r[c]) > v)
    else if (op === '<') out = out.filter((r) => Number(r[c]) < v)
    else if (op === '==' || op === '=') out = out.filter((r) => Number(r[c]) === v)
  }
  return out
}

export function toCSV(rows) {
  if (!rows?.length) return ''
  const cols = Object.keys(rows[0])
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v)
    if (/[",\n]/.test(s)) return `"${s.replaceAll('"', '""')}"`
    return s
  }
  const lines = []
  lines.push(cols.join(','))
  for (const r of rows) {
    lines.push(cols.map((c) => esc(r[c])).join(','))
  }
  return lines.join('\n')
}

export function inferNumericColumns(table) {
  return columnsForTable(table).filter((c) => isNumericColumn(table, c))
}

