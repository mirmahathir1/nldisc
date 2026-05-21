# NLDisc Demonstration Workflow — `country`

This document walks through one successful NLDisc session from a user's
perspective, using the bundled `country` data lake and **Query 1** of the
sample queries. The trace shown is what a real run against the backend
produces — no mock data is used.

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
2. Select **`country`**.

**What you see:**

- A row of chips appears below the dropdown summarizing the lake:
  `15 tables  ·  282 rows  ·  GDP_Per_Capita_Completed · 30  ·
  census_data · 29  ·  climate_metrics · 9  ·  continent_gdp · 6  ·
  continent_mapping · 6  ·  country_currency_strength · 29  ·
  currency · 7  ·  economic_metrics · 29  ·  gini_index · 8  ·
  global_tourism · 5  ·  health_indicators · 30  ·  literacy_rates · 30  ·
  query · 4  ·  renewable_energy · 20  ·  tech_market_cap · 20  ·
  university_acceptance · 20`.
- The four threshold sliders become enabled at their defaults (`0.75`,
  `0.75`, `0.9`, `5`).

> Behind the scenes the frontend calls `GET /api/datalakes/country/summary`
> and stores the table summary plus 3 sample rows per table.

---

## 2. Offline Stage — run preprocessing

**You do:**

1. Leave the sliders at their defaults.
2. Click **`Run preprocessing`** in the top-right of the NLDisc card.

**What you see:**

- The button spins for roughly **120–150 seconds** on the first run (OpenAI
  is building semantic types and one-sentence descriptions for each of the
  15 tables and embedding them with MPNet — there are roughly twice as many
  tables as the `orders` lake so it takes proportionally longer).
- When it finishes, two panels appear under the card:
  - **Left:** a scrollable list of `Join Path` cards. The `country` graph is
    densely connected through the shared `country` column, so the list is
    longer than for `orders`. Each card shows a small metrics block
    (`rows / cols / len / hops`), a row of attribute chips, and a mini
    node-graph of the join.
  - **Right:** a **Table descriptions** panel listing each table with the
    backend-generated, LLM-written one-sentence description (e.g.
    `gini_index — Reports per-country Gini coefficient samples.`).
- A blue **`Go to Online Stage`** button appears at the bottom right.

> Behind the scenes `POST /api/preprocess` writes artifacts under
> `preprocessed_data/country/` (semantic types, table descriptions, MinHash
> Jaccard scores, the join graph, simple paths, table-to-path index, and
> path embeddings). Re-running with unchanged params is instant (cache hit).

**You do:**

3. Click **`Go to Online Stage`**.

---

## 3. Online Stage — pick a sample query

The Online Stage page has two columns. The left column has the query input
area at the top and (eventually) the suggested query tables; the right
column will hold the join paths, SQL, and materialized preview once you
confirm a query table.

**You do:**

1. Open the **`Populate a sample query`** dropdown above the textarea.
2. Pick **`Query 1`**.

**What you see:**

- The dropdown closes and the textarea fills with:

  > Show countries with currency, continent, GDP per capita, population,
  > literacy rate, and life expectancy.

- The dropdown resets to empty (so you can pick again later).
- The textarea is editable — you can refine the wording before clicking
  Generate.

> Sample queries come from `GET /api/sample-queries?datalake=country`. The
> textarea starts blank; the dropdown is the one-click way to seed it.

---

## 4. Generate initial query tables

**You do:**

1. (Optional) Slide **`Query table suggestions`** from `4` up or down.
   Leave it at `4` for this walkthrough.
2. Click **`Generate query tables`**.

**What you see:**

- The button spins for ~5–15 seconds.
- The **Query tables** panel below populates with **4 candidate query
  tables**, rendered as cards in a 2-by-2 grid. For Query 1 on `country` the
  backend typically returns suggestions such as:

  | # | Suggestion name | Columns |
  |---|---|---|
  | 1 | `country_profile_with_currency_and_demographics` | Country, Currency, Continent, GDP Per Capita, Population, Literacy Rate, Life Expectancy |
  | 2 | `country_economic_and_social_indicators`         | Country, Currency, Continent, GDP/Capita, Population (M), Literacy, Life Expectancy |
  | 3 | `nation_summary_view`                            | Country, Currency, Continent, GDP per Capita (USD), Population, Literacy Rate (%), Life Expectancy (years) |
  | 4 | `country_demographics_and_economy`               | Country, Currency, Continent, GDP Per Capita, Population, Literacy, Life Expectancy |

- Each card shows 3 example rows and the column names as table headers.
- The first card is automatically **Selected** (a blue chip and a thicker
  border).

> Behind the scenes the frontend calls `POST /api/query-tables`. The
> backend embeds the natural language query with MPNet, looks up the top
> context tables in the HNSW index over table descriptions
> (`GDP_Per_Capita_Completed`, `currency`, `continent_mapping`,
> `literacy_rates`, `health_indicators`, `census_data` lead the ranking),
> then asks OpenAI for structured suggestions using only those context
> tables.

---

## 5. Edit a query table and resubmit

The user can refine any suggestion's *intent* by editing column names,
adding/removing columns, or changing example values. Only the selected
card is editable — other cards stay read-only.

**You do:**

1. Click the first card (`country_profile_with_currency_and_demographics`)
   to keep it selected. The header cells become editable text fields and
   three action buttons appear: `Add row`, `Add column`, `Resubmit`,
   `Confirm`, plus a `Remove column` dropdown.
2. Click **`Add column`**. A new column titled `New Column` appears with
   empty cells across the 3 rows.
3. Click the new column header and rename it to **`gini_coefficient`**.
   Press Enter.
4. (Optional) Type representative values into the new `gini_coefficient`
   cells, e.g. `41.5`, `30.5`, `33.7` — but the backend matches columns
   even with empty values.
5. Click **`Resubmit`**.

**What you see:**

- The button spins for ~5–15 seconds.
- The cards refresh. The first card is now the **edited table preserved
  verbatim** (your `gini_coefficient` column is still there, with your
  edits). The remaining slots show backend-revised suggestions that take
  the edit into account — they continue to include `gini_coefficient` and
  rebalance the other columns around it.
- Selecting the edited card again will show that your changes have been
  retained so you can confirm exactly what you submitted.

> Behind the scenes `POST /api/query-tables/resubmit` scores every
> data-lake column against each of your edited columns using a weighted
> combination of semantic-type similarity, column-name similarity, value
> overlap, and table-description relevance. For `gini_coefficient` the
> strongest evidence points at `gini_index.gini_coefficient`, so the
> `gini_index` table is pulled into the dominant context set for the new
> round of suggestions.

---

## 6. Confirm the final query table

You've now decided which query table best represents the answer shape you
want. For this walkthrough we confirm the **edited table** (the first card)
because it captures the `gini_coefficient` intent precisely.

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

> Behind the scenes the frontend calls `POST /api/join-search`. The
> backend: infers which data-lake tables you actually need from your
> confirmed rows (here: `GDP_Per_Capita_Completed`, `continent_mapping`,
> `literacy_rates`, `health_indicators`, `census_data`, `gini_index` — all
> share the `country` column as their join key), queries the
> table-to-path index for paths covering every required table, deduplicates
> near-duplicate paths via cosine similarity over their MPNet embeddings,
> then diversifies the survivors with K-means and returns the top K.

---

## 7. Review join paths

The join path cards summarise each candidate path: a compact metrics block
(`rows / cols / len / hops`), the participating attributes (highlighted if
they match one of your confirmed query columns), and a small node-graph
showing the join order.

For the confirmed table above, the top path returned by the backend chains
together the six tables sharing `country` as the join key:

```
jp_country_top   GDP_Per_Capita_Completed → census_data
                                          → continent_mapping
                                          → literacy_rates
                                          → health_indicators
                                          → gini_index
                  hops = 5    all six tables highlighted
```

**You do:**

1. Click on a different join path card to compare its SQL and materialized
   preview, or simply keep the top path selected for the final result.

**What you see:**

- The selected card visibly bumps up with a thicker border.
- The SQL card and Materialized table card both refresh to reflect the
  newly-selected path.

---

## 8. Inspect the SQL

Selecting a path triggers `GET /api/join-paths/<path_id>/sql`. The backend
generates the SQL from the same stored join order it uses for
materialization (so the two never disagree). Output columns are prefixed
with their source table name to avoid collisions.

For the top path you see:

```sql
SELECT
  t1."country"              AS "GDP_Per_Capita_Completed.country",
  t1."gdp_per_capita_usd"   AS "GDP_Per_Capita_Completed.gdp_per_capita_usd",
  t1."currency"             AS "GDP_Per_Capita_Completed.currency",
  t1."population_millions"  AS "GDP_Per_Capita_Completed.population_millions",
  t2."pop_data"             AS "census_data.pop_data",
  t3."continent"            AS "continent_mapping.continent",
  t4."literacy_rate"        AS "literacy_rates.literacy_rate",
  t5."life_expectancy"      AS "health_indicators.life_expectancy",
  t5."healthcare_expenditures" AS "health_indicators.healthcare_expenditures",
  t6."gini_coefficient"     AS "gini_index.gini_coefficient",
  …
FROM "GDP_Per_Capita_Completed" AS t1
JOIN "census_data"        AS t2 ON t1."country" = t2."country"
JOIN "continent_mapping"  AS t3 ON t1."country" = t3."country"
JOIN "literacy_rates"     AS t4 ON t1."country" = t4."country"
JOIN "health_indicators"  AS t5 ON t1."country" = t5."country"
JOIN "gini_index"         AS t6 ON t1."country" = t6."country";
```

Every join predicate is an equi-join on the shared `country` key.

---

## 9. Preview the materialized table

Below the SQL card the **Materialized table** card shows the first 50 rows
returned by `POST /api/join-paths/<path_id>/materialize`. Because you
confirmed a query table, the backend projects the joined table down to
the columns whose semantic types are most similar (highest cosine
similarity over MPNet semantic-type embeddings) to your query columns.

For the top path you typically see rows like the one below, with each
column matching exactly one of the seven confirmed query columns:

| Column | Value |
|---|---|
| `GDP_Per_Capita_Completed.country`            | Italy |
| `GDP_Per_Capita_Completed.currency`           | EUR |
| `continent_mapping.continent`                 | Oceania |
| `GDP_Per_Capita_Completed.gdp_per_capita_usd` | 36812.34 |
| `census_data.pop_data`                        | 58.9 |
| `literacy_rates.literacy_rate`                | 99.0 |
| `health_indicators.life_expectancy`           | 83.4 |
| `gini_index.gini_coefficient`                 | 33.72 |

> Behind the scenes the frontend sends the confirmed query columns plus
> their LLM-assigned semantic types (e.g. `Currency → currency code`,
> `GDP Per Capita → gross domestic product per capita`) to the materialize
> endpoint. For each query column the backend embeds the query semantic
> type and every joined-table column's semantic type with MPNet, picks
> the argmax over cosine similarity, and projects the materialized
> DataFrame to that subset. Duplicates are deduplicated, and a
> `projection.column_mapping` field in the response records which lake
> column won for each query column along with the cosine score.

Note that the `continent_mapping` data in this lake is intentionally noisy
(e.g. `United States → Oceania`, `Germany → Asia`) — the value you see
will reflect that file faithfully, since NLDisc does not silently correct
data.

---

## 10. Download the CSV

**You do:**

1. Click the **`Download CSV`** button in the top-right of the Materialized
   table card.

**What you see:**

- The browser downloads `nldisc_<path_id>.csv` containing the projected
  columns only — one header row plus one row per joined record.

> Behind the scenes the frontend already fetched the projected CSV via
> `POST /api/join-paths/<path_id>/csv` (with the same query column +
> semantic type payload) when you selected the path and stashed it in the
> store, so the download is instantaneous (no extra round-trip). The CSV
> contains the full inner-join projected to the query columns — not just
> the 50-row preview — and the columns match the previewed table exactly.

---

## Recap of the user flow

```
Offline Stage
  └─ pick "country" from Data Lake dropdown
  └─ click Run preprocessing                  (~120–150 s first run, cached after)
  └─ click Go to Online Stage

Online Stage
  ├─ Populate a sample query → Query 1
  ├─ click Generate query tables               (~5–15 s)  → 4 suggestions
  ├─ select card 1, Add column → "gini_coefficient"
  ├─ click Resubmit                            (~5–15 s)  → revised suggestions
  ├─ select the edited card, click Confirm     (~3–8 s)   → join paths + SQL + projected preview
  ├─ (optionally click other paths to compare)
  └─ click Download CSV                        (instant, projected)
```

That's the full NLDisc loop on the `country` data lake — from a natural
language description to a projected, downloadable joined table over six
country-keyed tables, with every step backed by the Flask backend and all
OpenAI calls cached on disk for reproducibility.
