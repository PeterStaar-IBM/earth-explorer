# Earth Explorer (Desktop)

A desktop globe explorer using Electron + CesiumJS + FastAPI with:

- Real Earth imagery
- Continuous zoom from globe scale toward street scale
- Right-side chat panel for navigation commands (for example: `show me Paris`)
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

## Commands

You can type:

- `show me <place>`
- `go to <place>`
- `fly to <place>`
- or just a place name

Chat requests go to backend query endpoint:

- `POST /api/query`

Example body:

```json
{ "action": "geocode", "q": "France" }
```

Response includes point coordinates and, when available, GeoJSON geometry (`Polygon`, `MultiPolygon`, `LineString`, etc.).
The frontend renders geometry overlays and flies camera to the shape extent.

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

Notes:

- First run downloads the GLiNER2 model from Hugging Face.
- Default model: `fastino/gliner2-base-v1` (override with `--model`).
- Default labels include cities, countries, rivers, oil fields, and related location types.

## Offline Location Extraction (Docling JSON -> CSV via NuExtract2)

Standalone script:

```bash
uv run --project backend python backend/scripts/extract_locations_nuextract2.py \
  --input-json backend/output/<input-stem>.docling.json \
  --output-csv backend/output/<input-stem>.nuextract.locations.csv
```

Notes:

- Default model: `numind/NuExtract-2.0-2B` (override with `--model`).
- First run downloads model weights from Hugging Face.

## Offline Location Extraction (Docling JSON -> CSV via GPT-OSS on LM Studio)

Standalone script:

```bash
uv run --project backend python backend/scripts/extract_locations_gpt_oss_lmstudio.py \
  --input-json backend/output/<input-stem>.docling.json \
  --output-csv backend/output/<input-stem>.gptoss.locations.csv \
  --model openai/gpt-oss-20b \
  --base-url http://127.0.0.1:1234/v1
```

Notes:

- Ensure LM Studio is running with an OpenAI-compatible local server enabled.
- Ensure the selected GPT-OSS model is loaded in LM Studio.

## Notes

- Street-level imagery requires network access for map tiles.
- If tile download is blocked, the app will still run but detailed imagery may not load.
