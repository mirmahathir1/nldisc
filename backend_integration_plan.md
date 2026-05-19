# NLDisc Backend Integration Plan

This is a planning document only. It does not include Python implementation code.

## 1. Goal

Replace the simulated browser-only NLDisc demo with a real Flask backend that serves data lake metadata, preprocessing artifacts, OpenAI-assisted table descriptions, OpenAI-assisted query table suggestions, corrected-query-table resubmission, join path retrieval, SQL generation, materialization previews, and CSV downloads.

The frontend components should remain in place. The work should remove fake hardcoded data and fake discovery logic from the frontend, then wire the existing UI panels to backend responses.

## 2. Current Repository Findings

- `src/store/index.js` currently drives the whole pipeline from local JavaScript helpers in `src/lib/nldisc.js`.
- `src/lib/nldisc.js` contains hardcoded synthetic data, fake join graph edges, fake semantic types, fake query table generation, fake candidate-table inference, and in-browser materialization.
- `src/pages/OfflineStage.vue` currently uses a CSV upload button. The prompt requires replacing this with a dropdown listing data lake folders under `datalake/`.
- `src/pages/OnlineStage.vue` has the correct interaction surface: natural language query, query table suggestions, editing, resubmit, confirm, join paths, SQL, materialized table, and CSV download.
- `src/components/TableDescriptions.vue` currently guesses descriptions from table names and column names. It must display backend-generated descriptions.
- `src/components/JoinPathCard.vue` and `src/components/JoinGraph.vue` can stay, but their inputs must come from backend artifacts.
- `src/App.vue` contains stale old demo blocks referencing the simulated flow even though `src/main.js` mounts `AppShell.vue`. This stale fake-data code should be cleaned or converted to the same minimal shell so the repository no longer contains hidden fake UI logic.
- `backend/` currently only contains environment-related files and no Flask service.
- `preprocessed_data/<datalake>/` exists but has no artifacts yet.
- `datalake/orders` and `datalake/country` are suitable fixtures for backend tests and UI demos. The `orders` lake is the better first integration target because it has clear equi-join keys.

## 3. OpenAI API Approach

Use the OpenAI Responses API from the backend only. The API key stays in `backend/.env` and is never sent to the browser.

OpenAI documentation basis:

- Responses API overview: https://developers.openai.com/api/reference/responses/overview
- Structured Outputs guide: https://developers.openai.com/api/docs/guides/structured-outputs
- Current model guidance: https://developers.openai.com/api/docs/guides/latest-model.md

Implementation policy:

- Add `OPENAI_MODEL` to backend configuration. Default to the current OpenAI docs recommendation, while allowing the paper-aligned model name to be configured without code changes.
- Use Structured Outputs for query table suggestions, corrected query table suggestions, semantic type extraction, and table description extraction when practical.
- Use temperature 0 for deterministic metadata extraction.
- Use a deterministic file cache for every OpenAI call. The cache key should be a SHA-256 hash of a stable payload containing task type, model, prompt/instructions, input metadata, schema version, temperature, and relevant parameters.
- Store cache files under `preprocessed_data/<datalake>/openai_cache/<sha256>.json`.
- On a cache hit, the backend returns the cached parsed result and does not call OpenAI.
- On a cache miss, the backend calls OpenAI, validates/parses the response, writes the cache, and returns the parsed result.
- Tests should mock OpenAI or seed cache fixtures so backend tests do not require live API calls.

## 4. Backend Layout

Create a Flask backend under `backend/` with this planned structure:

| Path | Purpose |
|---|---|
| `backend/app.py` | Flask application factory and route registration. |
| `backend/config.py` | Loads `.env`, model settings, paths, cache settings, default thresholds. |
| `backend/requirements.txt` | pip dependencies to install inside the project-local conda environment. |
| `backend/services/datalake.py` | Lists data lakes, loads CSVs, computes schemas, table previews, table/file hashes. |
| `backend/services/openai_cache.py` | Hash-based file cache for all OpenAI prompts. |
| `backend/services/llm.py` | OpenAI Responses API wrapper, structured-output parsing, validation, retries. |
| `backend/services/semantic_types.py` | Cached semantic type extraction from table name, column names, and sample values. |
| `backend/services/table_descriptions.py` | Cached one-sentence table descriptions and description embeddings. |
| `backend/services/embeddings.py` | MPNet embeddings and HNSW index helpers. |
| `backend/services/join_detection.py` | Equi-join discovery using MinHash/exact value overlap and SemDisc-inspired thresholds. |
| `backend/services/join_paths.py` | Join graph construction, simple path enumeration, binary table-to-path index, cardinality, path embeddings. |
| `backend/services/query_tables.py` | Initial and corrected query table suggestion workflows. |
| `backend/services/join_search.py` | Candidate table matching from confirmed query tables, path lookup, deduplication, diversification. |
| `backend/services/materialization.py` | SQL generation, pandas joins, previews, CSV output. |
| `backend/api/*.py` | Route modules grouped by datalake, preprocessing, online query, join paths, materialization. |
| `backend/tests/` | Backend-only unit and integration tests. |

Expected `backend/requirements.txt` dependency groups:

- Web/API: Flask, flask-cors, python-dotenv, pydantic.
- Data: pandas, numpy, pyarrow.
- Discovery: datasketch, networkx, scikit-learn.
- Embeddings/index: sentence-transformers, hnswlib.
- OpenAI: openai.
- Tests: pytest, pytest-mock.

The backend should run inside a project-local prefixed conda environment, for example `backend/.conda`, with pip installing `backend/requirements.txt` into that environment. Because the pip installation may take a long time, especially for embedding and indexing dependencies, the implementation should prepare the exact setup commands but hand off the actual pip install execution to the user to run manually.

Execution convention:

- Use `backend/.conda/bin/python` as the Python interpreter for every backend command that executes Python code, including app startup, scripts, migrations, one-off smoke checks, and tests.
- Prefer commands such as `backend/.conda/bin/python -m backend.app`, `backend/.conda/bin/python -m pytest backend/tests`, and `backend/.conda/bin/python -m pip install -r backend/requirements.txt`.
- Avoid relying on shell activation or `conda run` in plan verification commands unless there is a specific reason; direct interpreter execution is more predictable in this repository environment.

## 5. Preprocessed Artifact Layout

All repeated work is stored under `preprocessed_data/<datalake>/`.

Planned artifacts:

| Artifact | Contents |
|---|---|
| `metadata.json` | Data lake name, CSV hashes, parameter signature, preprocessing version, timestamps. |
| `tables.json` | Table names, columns, row counts, sample rows, top values. |
| `semantic_types.json` | Per table/column semantic type, examples, extraction source/cache key. |
| `table_descriptions.json` | One-sentence descriptions and source cache keys. |
| `table_description_embeddings.npy` | MPNet embeddings for table descriptions. |
| `table_description_hnsw.bin` | HNSW index for natural language query to table-description retrieval. |
| `table_description_labels.json` | HNSW vector id to table name mapping. |
| `minhash_jaccard.json` | Column-pair approximate Jaccard scores. |
| `exact_joinability.json` | Optional exact overlap scores for small/demo lakes and tests. |
| `join_graph.json` | Nodes and equi-join edges with columns, score, cardinality support, metadata. |
| `join_paths.json` | Enumerated simple paths, path ids, join order, attributes, hop count, row-count estimate. |
| `table_to_path_index.npy` | Binary matrix: table rows by join path columns. |
| `table_index_map.json` | Matrix row order. |
| `join_path_embeddings.npy` | Mean MPNet embeddings of semantic types across each path. |
| `join_path_embedding_labels.json` | Vector id to path id mapping. |
| `openai_cache/*.json` | Per-prompt cached OpenAI responses. |

Preprocessing should skip recomputation when `metadata.json` shows that CSV hashes, thresholds, max path length, model names, and preprocessing version match.

## 6. Offline Phase Plan

### 6.1 Data Lake Selection

Replace CSV upload with a backend-backed dropdown:

- `GET /api/datalakes` returns folder names under `datalake/`, for example `orders` and `country`.
- Selecting a lake calls `GET /api/datalakes/<name>/summary`.
- The summary includes table names, row counts, columns, and sample rows.
- The store state should use this summary instead of browser-generated data.

### 6.2 Semantic Type Extraction

Follow the intent of `semdisc_broken_codes/semantic_type_extractor.py`:

- For each table, collect table name, columns, and top/frequent non-null sample values.
- Ask OpenAI for a detailed semantic type/name per column.
- Validate that every returned column maps back to an actual column. Use fuzzy repair only as a fallback.
- Cache each table-level OpenAI call.
- Store per-column semantic types in `semantic_types.json`.

This semantic type layer is needed for table description prompts, semantic type similarity, and join path embeddings.

### 6.3 Table Description Extraction

Implement the paper’s missing table-description step:

- Input to the LLM: table name, each column id, semantic type, and sample values.
- Output: exactly one concise, human-readable sentence describing what the table contains.
- Store descriptions in `table_descriptions.json`.
- Embed descriptions with MPNet (`sentence-transformers/all-mpnet-base-v2`).
- Build an HNSW index over table description embeddings for natural language query retrieval.

This replaces `TableDescriptions.vue` guessing logic.

### 6.4 Equi-Join Discovery

Follow the SemDisc join graph and MinHash ideas, but implement only equi-joins as requested:

- Read all CSVs into pandas DataFrames.
- For every pair of columns across different tables, compute MinHash Jaccard over normalized non-null value sets.
- For small/demo tables, also compute exact value-overlap joinability so tests can assert deterministic values.
- Treat columns as equi-join candidates when their overlap exceeds the configured equi-joinability threshold and their normalized value domains are comparable.
- Do not require numeric-only equi-joins. The current data lakes use string ids such as `order_id`, `customer_id`, `product_id`, and `category_id`.
- Exclude semantic hash joins from the first backend implementation because the prompt explicitly scopes NLDisc to equi-joins.
- Keep edge metadata: left table, left column, right table, right column, Jaccard/overlap score, edge type `equi`, supporting row counts, and confidence.
- Build an undirected NetworkX graph for path enumeration while preserving directed join-order metadata for SQL/materialization.

### 6.5 Join Path Index

Follow `semdisc_broken_codes/pairwise_simple_path_index.py`:

- Enumerate simple paths up to `max_join_path_length`.
- For each adjacent table pair, choose the best equi-join edge by score.
- Store path id, ordered table list, join order, attributes, hop count, score, and cardinality estimate.
- For demo-sized lakes, compute true join cardinality with pandas over join columns. For larger lakes, add a future option for sketch-based estimates.
- Build the binary `table_to_path_index` matrix where a path column is 1 for every table participating in that path.
- Sort offline paths by score, cardinality, and shorter hop count for the offline display.

### 6.6 Join Path Embeddings

Follow the paper’s mean semantic-type embedding strategy:

- For each join path, collect semantic types for all columns from the participating tables.
- Embed those semantic type strings with MPNet.
- Store the mean vector as the path embedding.
- These embeddings are used only for deduplication/diversification, not for join detection.

## 7. Online Phase Plan

### 7.1 Sample Query Dropdown

Add a button/dropdown next to the natural language textarea labeled `Populate a sample query`.

- The dropdown shows `Query 1` and `Query 2` for the currently selected data lake.
- Selecting an item populates the natural language query field.
- The field should start empty instead of using the current hardcoded query.
- `GET /api/sample-queries?datalake=<name>` returns the two sample queries.

Suggested initial samples:

| Data lake | Query 1 | Query 2 |
|---|---|---|
| `orders` | Show orders with customer country, ordered products, quantities, categories, and shipment carriers. | Build a table of customers, orders, product families, quantities, and preferred carriers. |
| `country` | Show countries with currency, continent, GDP per capita, population, literacy rate, and life expectancy. | Build a country profile table with renewable energy, temperature, inflation, tourism, and GDP details. |

These sample queries should also drive backend integration tests.

### 7.2 Initial Query Table Suggestions

Implement the paper’s missing first query table generation:

- Endpoint: `POST /api/query-tables`.
- Inputs: data lake name, natural language query, desired suggestion count, `ann_topk`.
- Embed the natural language query with MPNet.
- Search the table description HNSW index to retrieve top candidate context tables.
- Build LLM context from those tables: table name, column semantic types, top values, and a small sample.
- Ask OpenAI to produce the requested number of query table suggestions, each with 3 rows.
- Use Structured Outputs so the backend receives predictable table names, columns, semantic types, and example values.
- Normalize suggestions into the shape the existing UI can render: query table name plus `rows`, with row objects keyed by column display names.
- Return candidate context tables and match scores for debugging and tests, even if the UI initially hides them.

### 7.3 Corrected Query Table Resubmission

Implement the paper’s missing iterative feedback step:

- Endpoint: `POST /api/query-tables/resubmit`.
- Inputs: data lake name, original natural language query, selected/edited query table rows, prior selected table name, suggestion count.
- Infer corrected query-table column intents from column names, values, and semantic type similarity.
- Match edited columns to data lake columns using a weighted score:
  - semantic type embedding similarity,
  - column-name embedding/string similarity,
  - exact value overlap with edited example values,
  - table-description relevance to the original natural language query.
- Select context tables with overlapping semantic types and values.
- Ask OpenAI to generate revised query table suggestions using original query, edited query table, and selected context tables.
- Preserve the user’s edited table as one returned suggestion so users can confirm it after resubmission.
- Return revised suggestions and candidate table/column evidence.

### 7.4 Confirmed Query Table to Join Paths

Implement join path retrieval after the user confirms a query table:

- Endpoint: `POST /api/join-search`.
- Inputs: data lake name, confirmed query table rows, top K, dedup threshold.
- Match query table columns and example values to candidate data lake columns/tables using the same evidence scoring as resubmission.
- Convert candidate tables to table indices.
- Query `table_to_path_index` by selecting path columns where all required candidate-table rows are 1.
- If strict coverage is empty, fall back to ranked paths that cover the largest subset, but label this in backend metadata so tests can detect it.
- Deduplicate candidate paths by cosine similarity of path embeddings using the paper’s approximate threshold of 0.8.
- Diversify with K-means over deduplicated path embeddings and select the path closest to each centroid.
- Return top paths with path id, ordered tables, join edges, row-count estimate, attributes, hop count, score, matched query columns, and highlighted tables.

### 7.5 SQL, Materialization, and Download

Implement path-specific retrieval:

- Endpoint: `GET /api/join-paths/<path_id>` returns path metadata.
- Endpoint: `GET /api/join-paths/<path_id>/sql?datalake=<name>` returns SQL text.
- Endpoint: `GET /api/join-paths/<path_id>/materialize?datalake=<name>&limit=50` returns preview rows and columns.
- Endpoint: `GET /api/join-paths/<path_id>/csv?datalake=<name>` returns a CSV download.

Materialization policy:

- Use pandas inner joins over the stored join order.
- Generate SQL from the same join order so SQL and materialization agree.
- Prefix duplicate output column names with table names or aliases to avoid collisions.
- Highlight columns/tables matched to the query table in the response metadata.

## 8. Frontend Integration Plan

### 8.1 API Client

Add a small frontend API module, for example `src/api/nldiscApi.js`, to centralize fetch calls and response normalization.

The Vuex store should call this API module instead of importing discovery functions from `src/lib/nldisc.js`.

### 8.2 Store Changes

Replace simulated actions with backend calls:

- `loadDefaultDataLake` becomes `selectDataLake`.
- `preprocess` calls `POST /api/preprocess`.
- `maybeComputeRowCount` reads row counts from path metadata or a backend path endpoint.
- `generateQueryTables` calls `POST /api/query-tables`.
- `resubmitFromEdits` calls `POST /api/query-tables/resubmit`.
- `runJoinSearch` calls `POST /api/join-search`.
- `selectPath` calls materialization and SQL endpoints.

Remove hardcoded state defaults:

- `nlQuery` starts as an empty string.
- `dataLake` is backend table summary/preview, not synthetic rows.
- `queryTables`, `joinEdges`, `joinPathIndex`, `topPaths`, SQL, and materialized rows all come from API responses.

### 8.3 Offline UI

Modify `src/pages/OfflineStage.vue`:

- Replace hidden file input and upload button with a `v-select` or menu populated from `GET /api/datalakes`.
- Keep the NLDisc header and existing threshold sliders.
- Keep `Run preprocessing`.
- Keep the join path list and table descriptions panels, but feed them backend artifacts.
- Display selected data lake table count and row-count summary in the existing layout where helpful.

### 8.4 Online UI

Modify `src/pages/OnlineStage.vue`:

- Add `Populate a sample query` dropdown next to the textarea.
- Fix the label typo `Natural LanguageQuery` to `Natural Language Query`.
- Keep query table cards, editing controls, resubmit, confirm, join path list, SQL card, materialized table, and download button.
- Generate/resubmit/confirm buttons should call backend-backed Vuex actions.
- Use backend matched-column metadata for highlighting instead of local name-only matching where possible.

### 8.5 Component Changes

- `TableDescriptions.vue`: accept backend descriptions directly; remove `guessDescription`.
- `JoinPathCard.vue`: keep the component; adjust props only if backend returns richer row counts or highlighted table metadata.
- `JoinGraph.vue`: keep the component; continue rendering edge labels from backend join edges.
- `src/lib/nldisc.js`: remove fake generators and either delete it if unused or repurpose it to pure frontend formatting helpers with no fake data.
- `src/App.vue`: remove stale old demo blocks so hidden fake-data code is not left in the repository.

## 9. Backend API Contract

Planned endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health check and backend version. |
| GET | `/api/datalakes` | List available data lake folders. |
| GET | `/api/datalakes/<name>/summary` | Table names, row counts, columns, sample rows. |
| GET | `/api/sample-queries?datalake=<name>` | Query 1 and Query 2 for the selected lake. |
| POST | `/api/preprocess` | Build or load cached preprocessing artifacts. |
| GET | `/api/preprocess/<name>/artifacts` | Return join paths, join edges, descriptions, and metadata for UI. |
| POST | `/api/query-tables` | Generate initial query table suggestions from NL query. |
| POST | `/api/query-tables/resubmit` | Generate revised suggestions from edited query table. |
| POST | `/api/join-search` | Retrieve diverse top-K join paths from confirmed query table. |
| GET | `/api/join-paths/<path_id>` | Return one path’s metadata. |
| GET | `/api/join-paths/<path_id>/sql` | Return SQL for a selected path. |
| GET | `/api/join-paths/<path_id>/materialize` | Return preview rows for a selected path. |
| GET | `/api/join-paths/<path_id>/csv` | Return materialized CSV. |

All endpoints that need a data lake should accept a data lake name and reject unknown names. All JSON responses should include a stable `status`, `data`, and optional `error` structure so frontend loading/error states can be simple.

## 10. Test Plan

Backend-only tests should cover the whole NLDisc method without requiring the UI.

### 10.1 Unit Tests

- Data lake listing returns `orders` and `country`.
- CSV loader returns correct table names, columns, row counts, and sample rows.
- OpenAI cache computes stable hash filenames and prevents duplicate calls for identical prompts.
- Semantic type parser maps every returned LLM column to a real CSV column.
- Table description extraction stores one sentence per table and reuses cache on a second call.
- MPNet embedding service returns vectors with consistent dimensions and builds an HNSW index.
- MinHash/exact overlap discovers expected `orders` joins:
  - `orders.order_id` to `order_items.order_id`.
  - `orders.order_id` to `shipments.order_id`.
  - `orders.customer_id` to `customers.customer_id`.
  - `order_items.product_id` to `products.product_id`.
  - `products.category_id` to `categories.category_id`.
- Join graph does not create self-joins or same-table edges.
- Simple path enumeration respects `max_join_path_length`.
- Table-to-path index returns paths containing all required tables.
- SQL generation uses the same join columns as materialization.

### 10.2 Integration Tests

Use cached/mocked OpenAI responses for deterministic integration tests.

Test case 1, `orders`, Query 1:

- Natural language query: `Show orders with customer country, ordered products, quantities, categories, and shipment carriers.`
- Preprocess `orders`.
- Initial query table suggestions should include columns semantically matching order, customer/country, product/category, quantity, and carrier.
- Confirm a suggestion.
- Join search should return a path covering `customers`, `orders`, `order_items`, `products`, `categories`, and `shipments`, or a best diversified subset if the max path setting prevents the full path.
- Materialization should produce non-empty rows.
- SQL should include equi-join predicates on the expected id columns.

Test case 2, `orders`, correction/resubmit:

- Start with Query 2: `Build a table of customers, orders, product families, quantities, and preferred carriers.`
- Generate initial suggestions.
- Edit the selected query table by adding or renaming a column to emphasize `product_family`.
- Resubmit.
- Revised suggestions should retain the edited table and include product-related columns.
- Candidate table evidence should include `products` and `order_items`.

Test case 3, `country`, Query 1:

- Natural language query: `Show countries with currency, continent, GDP per capita, population, literacy rate, and life expectancy.`
- Preprocess `country`.
- Initial query table suggestions should include country, currency, continent, GDP/population, literacy, and health fields.
- Join search should prefer paths connected through the `country` column.
- Materialization should produce non-empty rows for countries represented in multiple tables.

Test case 4, caching:

- Run preprocessing twice with unchanged data and parameters.
- Assert the second run loads artifacts and makes no OpenAI calls.
- Change a threshold or CSV hash and assert preprocessing invalidates only the affected artifacts.

Test case 5, API contract:

- Exercise the UI-facing endpoint sequence:
  - list data lakes,
  - select lake summary,
  - preprocess,
  - fetch artifacts,
  - fetch sample queries,
  - generate query tables,
  - resubmit edited table,
  - join search,
  - materialize selected path,
  - fetch SQL,
  - fetch CSV.
- Validate each response shape matches the frontend store expectations.

### 10.3 Data Fixture Adjustments

The `orders` fixture can be used mostly as-is.

For `country`, inspect and optionally normalize small inconsistencies in `continent_mapping.csv`, `currency.csv`, and `query.csv` so integration tests have deterministic non-empty join results. Any fixture changes should be minimal and documented in test notes.

## 11. Standalone Implementation Phases

Each phase below should end with a runnable or testable checkpoint. Later phases may build on earlier artifacts, but every phase has its own clear scope, deliverables, and verification target.

### Phase 1: Backend Foundation and Data Lake API

References: Sections 2, 4, 5, 6.1, 9, 10.1, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Create the Flask backend skeleton, configuration loader, `.env` loading, CORS policy, and `backend/requirements.txt`.
- Add the project-local conda environment setup instructions or scripts, including exact pip install commands that are handed off to the user for manual execution because installation may take substantial time.
- Document that backend execution commands should use `backend/.conda/bin/python` directly as the Python interpreter.
- Implement `GET /api/health`, `GET /api/datalakes`, and `GET /api/datalakes/<name>/summary`.
- Implement CSV loading, table summaries, column lists, row counts, sample rows, and file hashes.

Deliverable:

- A backend that can list `orders` and `country`, summarize their CSV files, and return stable JSON response envelopes as defined in Section 9.

Standalone verification:

- Backend unit tests for data lake listing and summary loading from Section 10.1 pass without OpenAI, embeddings, join discovery, or frontend changes.

### Phase 2: OpenAI Cache and LLM Metadata Services

References: Sections 3, 5, 6.2, 6.3, 9, 10.1, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Implement the hash-based OpenAI cache under `preprocessed_data/<datalake>/openai_cache/`.
- Implement the OpenAI Responses API wrapper with Structured Outputs support.
- Implement semantic type extraction from table names, column names, and sample values.
- Implement table description extraction using the paper prompt from Section 6.3.
- Store `semantic_types.json` and `table_descriptions.json`.

Deliverable:

- A metadata extraction service that can generate or load cached semantic types and table descriptions for a selected data lake.

Standalone verification:

- Mocked OpenAI tests prove identical prompts reuse the same cache file.
- Semantic type and table description tests from Section 10.1 pass without join discovery or frontend integration.

### Phase 3: Embeddings and Table Description Retrieval

References: Sections 5, 6.3, 7.2, 9, 10.1, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Add MPNet embedding support for table descriptions.
- Build and persist `table_description_embeddings.npy`, `table_description_hnsw.bin`, and `table_description_labels.json`.
- Add a service that embeds a natural language query and retrieves top candidate context tables from the HNSW index.

Deliverable:

- A reusable retrieval layer that maps a natural language query to ranked context tables using generated table descriptions.

Standalone verification:

- Embedding/index tests from Section 10.1 pass.
- A backend-only smoke test can retrieve plausible context tables for the sample queries in Section 7.1 without generating query tables yet.

### Phase 4: Equi-Join Discovery and Join Path Indexing

References: Sections 5, 6.4, 6.5, 6.6, 9, 10.1, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Implement MinHash and exact value-overlap equi-join discovery.
- Build the equi-join graph with edge metadata.
- Enumerate simple paths up to `max_join_path_length`.
- Compute path attributes, hop count, score, and demo-sized true cardinality.
- Build `table_to_path_index.npy`, `table_index_map.json`, `join_paths.json`, and join path embeddings.

Deliverable:

- A complete offline join discovery artifact set for at least `orders`, independent of query table generation.

Standalone verification:

- Unit tests from Section 10.1 confirm expected `orders` joins, no same-table joins, max path length behavior, table-to-path lookup, and path metadata.

### Phase 5: Preprocessing Endpoint and Artifact Loading

References: Sections 5, 6, 9, 10.2, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Implement `POST /api/preprocess`.
- Implement `GET /api/preprocess/<name>/artifacts`.
- Add artifact invalidation using CSV hashes, preprocessing version, model names, thresholds, and max path length.
- Return join paths, join edges, table descriptions, preprocessing status, and row counts in UI-ready shapes.

Deliverable:

- A single API flow that builds or loads all offline artifacts needed by the existing offline UI panels.

Standalone verification:

- Backend integration tests can preprocess `orders`, fetch artifacts, run preprocessing again, and assert that cached artifacts are reused as described in Section 10.2.

### Phase 6: Initial Query Table Suggestion API

References: Sections 3, 6.3, 7.1, 7.2, 9, 10.2, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Implement `GET /api/sample-queries?datalake=<name>`.
- Implement `POST /api/query-tables`.
- Retrieve context tables from the table description index.
- Build the LLM prompt from Section 7.2.
- Validate and normalize Structured Output responses into query table rows that the current UI can render.
- Return candidate context tables and match scores for tests and debugging.

Deliverable:

- A backend-only flow that accepts a natural language query and returns real LLM-generated query table suggestions.

Standalone verification:

- Cached or mocked integration tests for `orders` Query 1 and `country` Query 1 from Section 10.2 can generate query tables without frontend changes.

### Phase 7: Corrected Query Table Resubmission API

References: Sections 3, 7.3, 9, 10.2, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Implement `POST /api/query-tables/resubmit`.
- Match edited query table columns and values to candidate data lake columns using semantic type similarity, column-name similarity, value overlap, and table-description relevance.
- Build revised LLM context from the matched tables and columns.
- Preserve the user-edited query table as one returned suggestion.
- Return candidate table/column evidence.

Deliverable:

- A backend-only iterative disambiguation flow that can refine query table suggestions from user edits.

Standalone verification:

- The correction/resubmit test case in Section 10.2 passes with cached or mocked OpenAI responses and proves product-related edits surface `products` and `order_items`.

### Phase 8: Join Search, Deduplication, and Diversification

References: Sections 6.5, 6.6, 7.4, 9, 10.2, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Implement `POST /api/join-search`.
- Match confirmed query table columns and values to data lake tables.
- Query `table_to_path_index.npy` for paths covering the required tables.
- Add labeled fallback behavior when strict coverage is empty.
- Deduplicate candidate paths using the path embedding cosine threshold from Section 7.4.
- Diversify with K-means and return top paths in UI-ready shape.

Deliverable:

- A backend-only confirmed-query-table-to-join-paths flow that returns ranked diverse paths and matching metadata.

Standalone verification:

- Join search integration tests from Section 10.2 pass for `orders` and `country` using confirmed query table fixtures, without materialization or frontend changes.

### Phase 9: SQL, Materialization, and CSV API

References: Sections 6.5, 7.5, 9, 10.1, 10.2, and 12.

Python interpreter for backend execution: `backend/.conda/bin/python`.

Scope:

- Implement selected path metadata lookup.
- Implement SQL generation from the stored join order.
- Implement pandas materialization previews.
- Implement CSV download output.
- Ensure SQL generation and materialization use the same join columns and aliases.

Deliverable:

- A backend-only path selection flow that returns SQL, preview rows, and downloadable CSV data.

Standalone verification:

- SQL/materialization tests from Sections 10.1 and 10.2 pass and confirm non-empty materialized rows for the planned sample queries.

### Phase 10: Frontend Offline Integration

References: Sections 2, 8.1, 8.2, 8.3, 8.5, 9, and 12.

Python interpreter for backend execution during API startup and backend verification: `backend/.conda/bin/python`.

Scope:

- Add `src/api/nldiscApi.js`.
- Replace the CSV upload button with a data lake dropdown backed by `GET /api/datalakes`.
- Wire selected data lake summary and preprocessing actions to backend endpoints.
- Render backend table descriptions, join paths, join edges, and row counts.
- Keep the existing offline UI components and remove frontend-generated offline fake data.

Deliverable:

- The offline page works against the backend and no longer needs simulated browser data for data lake loading or preprocessing.

Standalone verification:

- Frontend build passes.
- Manual offline flow can select `orders`, run preprocessing, and display backend join paths and descriptions.

### Phase 11: Frontend Online Integration

References: Sections 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.4, 8.5, 9, and 12.

Python interpreter for backend execution during API startup and backend verification: `backend/.conda/bin/python`.

Scope:

- Add the `Populate a sample query` dropdown and remove the hardcoded initial natural language query.
- Wire query table generation, resubmission, confirm/search, selected path SQL, materialized preview, and CSV download to backend endpoints.
- Use backend matched-column and highlighted-table metadata where available.
- Keep the existing query table editing, join path list, SQL card, materialized table, and download components.

Deliverable:

- The online page works against the backend from sample query selection through materialized CSV download.

Standalone verification:

- Frontend build passes.
- Manual online flow works for at least `orders` Query 1 and one corrected/resubmitted query table.

### Phase 12: Fake Data Removal and End-to-End Acceptance

References: Sections 2, 8.2, 8.5, 10.2, 10.3, and 12.

Python interpreter for backend execution during backend tests, API startup, and end-to-end verification: `backend/.conda/bin/python`.

Scope:

- Remove fake data generation and fake discovery logic from `src/lib/nldisc.js`.
- Remove stale fake demo blocks from `src/App.vue`.
- Remove `TableDescriptions.vue` description guessing.
- Normalize any minimal `country` fixture issues needed for deterministic tests, as described in Section 10.3.
- Run the full backend test suite, frontend build, and manual end-to-end flows.

Deliverable:

- A repository where UI data comes from backend APIs and all fake hardcoded discovery behavior is removed.

Standalone verification:

- All backend tests in Sections 10.1 and 10.2 pass.
- Frontend build passes.
- Acceptance criteria in Section 12 are satisfied for both `orders` and `country` where applicable.

## 12. Acceptance Criteria

- Backend runs from a project-local conda prefix, installs dependencies from `backend/requirements.txt`, and uses `backend/.conda/bin/python` as the Python interpreter for backend execution commands.
- No OpenAI key is exposed to the frontend.
- All OpenAI calls are cached under hash-named files.
- Preprocessing writes artifacts under `preprocessed_data/<datalake>`.
- The offline UI lists existing data lakes instead of uploading CSVs.
- Table descriptions come from backend-generated LLM descriptions.
- Query table suggestions come from the backend using natural language query plus table description retrieval.
- Resubmission uses edited query tables and returns revised backend suggestions.
- Join path search uses a real equi-join graph and table-to-path index.
- Returned join paths are deduplicated and diversified using join path embeddings.
- SQL and materialized previews come from backend join orders.
- Fake hardcoded demo data and fake discovery logic are removed from the frontend.
- Backend tests cover preprocessing, OpenAI caching, query table generation, resubmission, join path retrieval, SQL, materialization, and CSV output.
