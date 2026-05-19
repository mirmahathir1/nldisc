# NLDisc Backend

Phase 1 adds a Flask API for listing local data lakes and summarizing CSV tables.

## Local conda setup

Run these commands from the repository root. Dependency installation is intentionally left as a manual step because later phases include embedding and indexing packages that can take a while to resolve and build.

```bash
conda create --prefix backend/.conda python=3.11 -y
conda activate ./backend/.conda
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

## Run the backend

```bash
conda activate ./backend/.conda
python -m backend.app
```

The Phase 1 API runs at `http://127.0.0.1:5000`.

## Run tests

```bash
conda activate ./backend/.conda
python -m pytest backend/tests
```

## Endpoints

- `GET /api/health`
- `GET /api/datalakes`
- `GET /api/datalakes/<name>/summary`

All JSON responses use this envelope:

```json
{
  "status": "ok",
  "data": {},
  "error": null
}
```
