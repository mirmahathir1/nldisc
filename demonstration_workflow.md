# NLDisc Demonstration Workflow

This document walks through one successful NLDisc session from a user's
perspective, using the bundled `orders` data lake and **Query 1** of the sample
queries. The trace shown is what a real run against the backend produces — no
mock data is used.

> **What you'll see:** select a data lake, run preprocessing, pick a sample
> natural language query, generate query tables, edit and resubmit one of
> them, confirm a query table, review the discovered join paths, then preview
> and download the materialized CSV.

---

## 0. Prerequisites

Both processes must be running.

1. **Backend** (Flask + OpenAI):

   ```bash
   backend/.conda/bin/python -m backend.app
   ```

   Wait for the line `Running on http://127.0.0.1:5000`.

2. **Frontend** (Vite dev server) in another shell:

   ```bash
   npm run dev
   ```

   Open the printed URL (default `http://localhost:5173`) in a browser.

The frontend automatically calls the backend at `http://127.0.0.1:5000/api`.
The OpenAI API key lives in `backend/.env` and is never sent to the browser.

---

## 1. Offline Stage — pick the data lake

The page opens on the **Offline Stage** with a `Data Lake` dropdown in the
top-left of the NLDisc card.

**You do:**

1. Click the `Data Lake` dropdown.
2. Select **`orders`**.

**What you see:**

- A row of chips appears below the dropdown summarizing the lake:
  `7 tables  ·  31 rows  ·  categories · 3  ·  customers · 4  ·  orders · 5  ·
  order_items · 5  ·  products · 4  ·  query · 5  ·  shipments · 4`.
- The four threshold sliders become enabled at their defaults (`0.75`,
  `0.75`, `0.9`, `5`).

> Behind the scenes the frontend calls `GET /api/datalakes/orders/summary` and
> stores the table summary plus 3 sample rows per table.

---

## 2. Offline Stage — run preprocessing

**You do:**

1. Leave the sliders at their defaults.
2. Click **`Run preprocessing`** in the top-right of the NLDisc card.

**What you see:**

- The button spins for roughly **60–70 seconds** on the first run (OpenAI is
  building semantic types and one-sentence table descriptions for each of the
  7 tables and embedding them with MPNet).
- When it finishes, two panels appear under the card:
  - **Left:** a scrollable list of `Join Path` cards. Each card shows a small
    metrics block (`rows / cols / len / hops`), a row of attribute chips, and
    a mini node-graph of the join.
  - **Right:** a **Table descriptions** panel listing each table with the
    backend-generated, LLM-written one-sentence description.
- A blue **`Go to Online Stage`** button appears at the bottom right.

> Behind the scenes `POST /api/preprocess` writes artifacts under
> `preprocessed_data/orders/` (semantic types, table descriptions, MinHash
> Jaccard scores, the join graph, simple paths, table-to-path index, and path
> embeddings). Re-running with unchanged params is instant (cache hit).

**You do:**

3. Click **`Go to Online Stage`**.

---

## 3. Online Stage — pick a sample query

The Online Stage page has two columns. The left column has the query input
area at the top and (eventually) the suggested query tables; the right column
will hold the join paths, SQL, and materialized preview once you confirm a
query table.

**You do:**

1. Open the **`Populate a sample query`** dropdown above the textarea.
2. Pick **`Query 1`**.

**What you see:**

- The dropdown closes and the textarea fills with:

  > Show orders with customer country, ordered products, quantities,
  > categories, and shipment carriers.

- The dropdown resets to empty (so you can pick again later).
- The textarea is editable — you can refine the wording before clicking
  Generate.

> Sample queries come from `GET /api/sample-queries?datalake=orders`. The
> textarea starts blank; the dropdown is the one-click way to seed it.

---

## 4. Generate initial query tables

**You do:**

1. (Optional) Slide **`Query table suggestions`** from `4` up or down. Leave
   it at `4` for this walkthrough.
2. Click **`Generate query tables`**.

**What you see:**

- The button spins for ~5–15 seconds.
- The **Query tables** panel below populates with **4 candidate query
  tables**, rendered as cards in a 2-by-2 grid. For Query 1 on `orders` the
  backend typically returns suggestions such as:

  | # | Suggestion name | Columns |
  |---|---|---|
  | 1 | `orders_with_products_categories_and_carriers` | Order ID, Customer Country, Product Name, Quantity, Category, Carrier |
  | 2 | `order_summary_with_category_and_carrier`      | Order ID, Country, Product, Qty, Category, Carrier |
  | 3 | `detailed_order_product_shipment_view`         | Order ID, Customer Country, Product Name, Quantity, Category Name, Shipment Carrier |
  | 4 | `order_products_categories_shipments`          | Order ID, Country, Product, Quantity, Category, Carrier |

- Each card shows 3 example rows and the column names as table headers.
- The first card is automatically **Selected** (a blue chip and a thicker
  border).

> Behind the scenes the frontend calls `POST /api/query-tables`. The backend
> embeds the natural language query with MPNet, looks up the top context
> tables in the HNSW index over table descriptions, then asks OpenAI for
> structured suggestions using only those context tables. Each suggestion's
> rows are values the model believes plausibly answer the query.

---

## 5. Edit a query table and resubmit

The user can refine any suggestion's *intent* by editing column names,
adding/removing columns, or changing example values. When the selected card
is the only editable one — other cards stay read-only.

**You do:**

1. Click the first card (`orders_with_products_categories_and_carriers`) to
   keep it selected. The header cells become editable text fields and three
   action buttons appear: `Add row`, `Add column`, `Resubmit`, `Confirm`,
   plus a `Remove column` dropdown.
2. Click **`Add column`**. A new column titled `New Column` appears with
   empty cells across the 3 rows.
3. Click the new column header and rename it to **`order_date`**. Press
   Enter.
4. (Optional) Type representative values into the new `order_date`
   cells, e.g. `2025-12-10`, `2025-12-11`, `2025-12-20` — but the backend
   matches columns even with empty values.
5. Click **`Resubmit`**.

**What you see:**

- The button spins for ~5–15 seconds.
- The cards refresh. The first card is now the **edited table preserved
  verbatim** (your `order_date` column is still there, with your edits).
  The remaining slots show backend-revised suggestions that take the edit
  into account — they continue to include `order_date` and rebalance the
  other columns around it.
- Selecting the edited card again will show that your changes have been
  retained so you can confirm exactly what you submitted.

> Behind the scenes `POST /api/query-tables/resubmit` scores every data-lake
> column against each of your edited columns using a weighted combination of
> semantic-type similarity, column-name similarity, value overlap, and
> table-description relevance. For `order_date` the strongest evidence
> points at `orders.order_date`, so the `orders` table becomes a dominant
> context source for the new round of suggestions.

---

## 6. Confirm the final query table

You've now decided which query table best represents the answer shape you
want. For this walkthrough we confirm the **edited table** (the first card)
because it captures the `order_date` intent precisely.

**You do:**

1. Make sure the edited card is selected (it has the blue `Selected` chip).
2. Click **`Confirm`**.

**What you see:**

- The button spins for ~3–8 seconds.
- The right column populates with three sections:
  1. A scrollable list of **join path cards** (top results from the search).
  2. A **SQL** card (initially with the first path's SQL pre-loaded).
  3. A **Materialized table** card showing a preview of joined rows.
- The first path in the list is highlighted (thicker border) — it's the
  default selected path.

> Behind the scenes the frontend calls `POST /api/join-search`. The backend:
> infers which data-lake tables you actually need from your confirmed rows
> (here: `orders`, `customers`, `order_items`, `products`, `categories`),
> queries the table-to-path index for paths covering all five tables,
> deduplicates near-duplicate paths via cosine similarity over their MPNet
> embeddings, then diversifies the survivors with K-means and returns the
> top K.

---

## 7. Review join paths

The join path cards summarise each candidate path: a compact metrics block
(`rows / cols / len / hops`), the participating attributes (highlighted if
they match one of your confirmed query columns), and a small node-graph
showing the join order.

For the confirmed table above, the top path returned by the backend is:

```
jp_00069   categories → products → order_items → orders → customers
           hops = 4    row_est = 4    all five tables highlighted
```

**You do:**

1. Click on a different join path card to compare its SQL and materialized
   preview, or simply keep `jp_00069` selected for the final result.

**What you see:**

- The selected card visibly bumps up with a thicker border.
- The SQL card and Materialized table card both refresh to reflect the
  newly-selected path.

---

## 8. Inspect the SQL

Selecting a path triggers `GET /api/join-paths/<path_id>/sql`. The backend
generates the SQL from the same stored join order it uses for materialization
(so the two never disagree). Output columns are prefixed with their source
table name to avoid collisions.

For `jp_00069` you see:

```sql
SELECT
  t1."category_id" AS "categories.category_id",
  t1."category"    AS "categories.category",
  t1."category_no" AS "categories.category_no",
  t2."product_id"  AS "products.product_id",
  t2."product"     AS "products.product",
  t2."category_id" AS "products.category_id",
  t2."product_family" AS "products.product_family",
  …
  t5."customer_id" AS "customers.customer_id",
  t5."name"        AS "customers.name",
  t5."country"     AS "customers.country",
  t5."customer_no" AS "customers.customer_no"
FROM "categories" AS t1
JOIN "products"     AS t2 ON t1."category_id" = t2."category_id"
JOIN "order_items"  AS t3 ON t2."product_id"  = t3."product_id"
JOIN "orders"       AS t4 ON t3."order_id"    = t4."order_id"
JOIN "customers"    AS t5 ON t4."customer_id" = t5."customer_id";
```

Every join predicate is an equi-join on the inferred shared key.

---

## 9. Preview the materialized table

Below the SQL card the **Materialized table** card shows the first 50 rows
returned by `GET /api/join-paths/<path_id>/materialize?limit=50`.

For `jp_00069` you see **4 rows**, with columns matching your confirmed
query highlighted in primary colour (e.g. `customers.country`,
`products.product`, `orders.order_date`, `orders.preferred_carrier`).

The first row contains, in part:

| Column | Value |
|---|---|
| `categories.category` | Accessories |
| `customers.country` | US |
| `customers.name` | A. Rivera |
| `order_items.qty` | 1 |
| `orders.order_id` | O100 |
| `orders.order_date` | 2025-12-10 |
| `orders.preferred_carrier` | DHL |
| `products.product` | Keyboard |
| `products.product_family` | Accessories |

---

## 10. Download the CSV

**You do:**

1. Click the **`Download CSV`** button in the top-right of the Materialized
   table card.

**What you see:**

- The browser downloads `nldisc_jp_00069.csv` (1 051 bytes, 4 data rows + 1
  header row for this run).

> Behind the scenes the frontend already fetched the full CSV via
> `GET /api/join-paths/<path_id>/csv` when you selected the path and stashed
> it in the store, so the download is instantaneous (no extra round-trip).
> The CSV contains the full inner-join — not just the 50-row preview — and
> the columns match the SQL output exactly.

---

## Recap of the user flow

```
Offline Stage
  └─ pick "orders" from Data Lake dropdown
  └─ click Run preprocessing                  (~60–70 s first run, cached after)
  └─ click Go to Online Stage

Online Stage
  ├─ Populate a sample query → Query 1
  ├─ click Generate query tables               (~5–15 s)  → 4 suggestions
  ├─ select card 1, Add column → "order_date"
  ├─ click Resubmit                            (~5–15 s)  → revised suggestions
  ├─ select the edited card, click Confirm     (~3–8 s)   → join paths + SQL + preview
  ├─ (optionally click other paths to compare)
  └─ click Download CSV                        (instant)
```

That's the full NLDisc loop from a natural language description to a
materialized, downloadable joined table — every step backed by the Flask
backend, with all OpenAI calls cached on disk for reproducibility.
