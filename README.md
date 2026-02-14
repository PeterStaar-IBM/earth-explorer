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

## Notes

- Street-level imagery requires network access for map tiles.
- If tile download is blocked, the app will still run but detailed imagery may not load.
