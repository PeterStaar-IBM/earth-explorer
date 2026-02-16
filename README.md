# Earth Explorer (Desktop)

A desktop globe explorer using Electron + CesiumJS + FastAPI with:

- Real Earth imagery
- Continuous zoom from globe scale toward street scale
- Right-side chat panel for navigation commands
- Python backend query API
- Shape rendering for countries, rivers, and regions when geometry is available

## Setup

From this directory:

```bash
npm run setup
```

This installs Node + Python dependencies, verifies required files, and checks runtime endpoints.

## Run

```bash
npm start
```

Electron starts the FastAPI backend automatically with `uv run` (`http://127.0.0.1:8000`) and then launches the app window.

## Chat Commands

- `show me <place>`
- `go to <place>`
- `fly to <place>`
- `list location files`
- `view <filename>`
- `show logs`
- `show earth`

`list location files` switches the viewer into a tabular file view showing CSV files in `backend/output`.

`view <filename>` resolves and plots all location rows from that CSV on the globe.

`show logs` opens the dedicated logs view.

`show earth` returns to the globe view.

All navigation between views is chat-driven.

## Backend API

- `POST /api/query`
- `GET /api/geocode?q=<place>`
- `GET /api/location-files`
- `GET /api/location-files/{filename}`
- `GET /api/location-files/{filename}/resolved-locations`

## Manual backend run (optional)

```bash
uv run --project backend uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## Offline PDF Processing (Docling)

Standalone script:

```bash
uv run --project backend python backend/scripts/process_pdf_docling.py \
  --input /absolute/path/to/file.pdf \
  --output-dir backend/output
```

Output file format:

- `backend/output/<input-stem>.docling.json`

## Offline Location Extraction (Docling JSON -> CSV via GLiNER2)

Standalone script:

```bash
uv run --project backend python backend/scripts/extract_locations_gliner2.py \
  --input-json backend/output/<input-stem>.docling.json \
  --output-csv backend/output/<input-stem>.locations.csv
```

## Offline Location Extraction (Docling JSON -> CSV via NuExtract2)

Standalone script:

```bash
uv run --project backend python backend/scripts/extract_locations_nuextract2.py \
  --input-json backend/output/<input-stem>.docling.json \
  --output-csv backend/output/<input-stem>.nuextract.locations.csv
```

## Offline Location Extraction (Docling JSON -> CSV via GPT-OSS on LM Studio)

Standalone script:

```bash
uv run --project backend python backend/scripts/extract_locations_gpt_oss_lmstudio.py \
  --input-json backend/output/<input-stem>.docling.json \
  --output-csv backend/output/<input-stem>.gptoss.locations.csv \
  --model openai/gpt-oss-20b \
  --base-url http://127.0.0.1:1234/v1
```

## Notes

- Street-level imagery requires network access for map tiles.
- If tile download is blocked, the app will still run but detailed imagery may not load.
