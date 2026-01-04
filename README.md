## NLDisc — Streamlit App

This Streamlit app provides an interactive interface for **NLDisc**, a natural-language join discovery system.

### Setup (local conda env in `./env`)

Create the environment:

```bash
conda create --prefix ./env python=3.11 -y
conda activate ./env
pip install -r requirements.txt
```

Run the app:

```bash
streamlit run app.py
```

### Features

- Upload/use a “data lake” (tables)
- Run a preprocessing step to build:
  - semantic type index
  - join graph
  - join path index
- Enter a natural-language query
- Iteratively pick/edit “query tables” (query-by-example)
- Confirm a query table and retrieve top join paths
- Inspect join path details, generated SQL, preview materialized data, and download CSV


