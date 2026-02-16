from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from typing import Any
import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

app = FastAPI(title="Earth Explorer Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = "earth-explorer/1.0 (desktop-app)"
OUTPUT_DIR = (Path(__file__).resolve().parent / "output").resolve()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def geocode_lookup(q: str) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    errors: list[str] = []

    # Primary provider: Nominatim
    try:
        nominatim_params = {"q": q, "format": "json", "limit": 1, "polygon_geojson": 1}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(NOMINATIM_URL, params=nominatim_params, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if data:
                item = data[0]
                geojson = item.get("geojson")
                geometry = geojson if isinstance(geojson, dict) and geojson.get("type") else None
                return {
                    "result": {
                        "kind": "shape" if geometry else "point",
                        "lat": item.get("lat"),
                        "lon": item.get("lon"),
                        "display_name": item.get("display_name"),
                        "geometry": geometry,
                        "bbox": item.get("boundingbox"),
                        "osm_type": item.get("osm_type"),
                        "category": item.get("class"),
                        "feature_type": item.get("type"),
                    }
                }
        else:
            errors.append(f"Nominatim status={response.status_code}")
    except httpx.HTTPError as exc:
        errors.append(f"Nominatim request error={exc}")

    # Fallback provider: Open-Meteo geocoding
    try:
        open_meteo_params = {"name": q, "count": 1, "language": "en", "format": "json"}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(OPEN_METEO_GEOCODE_URL, params=open_meteo_params, headers=headers)

        if response.status_code == 200:
            payload = response.json()
            results = payload.get("results") or []
            if results:
                item = results[0]
                display_name = ", ".join(
                    part for part in [item.get("name"), item.get("admin1"), item.get("country")] if part
                )
                return {
                    "result": {
                        "kind": "point",
                        "lat": item.get("latitude"),
                        "lon": item.get("longitude"),
                        "display_name": display_name or q,
                        "geometry": None,
                        "bbox": None,
                        "osm_type": None,
                        "category": None,
                        "feature_type": None,
                    }
                }
        else:
            errors.append(f"Open-Meteo status={response.status_code}")
    except httpx.HTTPError as exc:
        errors.append(f"Open-Meteo request error={exc}")

    if errors:
        raise HTTPException(status_code=502, detail="; ".join(errors))

    return {"result": None}


def _safe_csv_path(filename: str) -> Path:
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not safe_name.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="filename must end with .csv")
    full_path = (OUTPUT_DIR / safe_name).resolve()
    if full_path.parent != OUTPUT_DIR:
        raise HTTPException(status_code=400, detail="invalid filename path")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {safe_name}")
    return full_path


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({k: (v or "").strip() for k, v in row.items() if k is not None})
    return headers, rows


def _extract_location_names(rows: list[dict[str, str]]) -> list[str]:
    candidates = ("entity", "location", "name", "display_name")
    names: list[str] = []
    seen: set[str] = set()

    for row in rows:
        value = ""
        for key in candidates:
            if key in row and row[key].strip():
                value = row[key].strip()
                break
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(value)
    return names


@app.get("/api/geocode")
async def geocode(q: str = Query(..., min_length=1)) -> dict[str, Any]:
    return await geocode_lookup(q)


@app.get("/api/location-files")
async def list_location_files() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for path in sorted(OUTPUT_DIR.glob("*.csv")):
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return {"files": files}


@app.get("/api/location-files/{filename}")
async def read_location_file(filename: str) -> dict[str, Any]:
    csv_path = _safe_csv_path(filename)
    headers, rows = _read_csv_rows(csv_path)
    names = _extract_location_names(rows)
    return {
        "file": csv_path.name,
        "headers": headers,
        "row_count": len(rows),
        "location_count": len(names),
        "locations": names,
    }


@app.get("/api/location-files/{filename}/resolved-locations")
async def resolved_locations(filename: str, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    csv_path = _safe_csv_path(filename)
    _, rows = _read_csv_rows(csv_path)
    names = _extract_location_names(rows)[:limit]

    semaphore = asyncio.Semaphore(4)

    async def resolve_one(name: str) -> dict[str, Any]:
        async with semaphore:
            try:
                payload = await geocode_lookup(name)
                return {"query": name, "result": payload.get("result")}
            except Exception:
                return {"query": name, "result": None}

    resolved = await asyncio.gather(*(resolve_one(name) for name in names))
    good = [item for item in resolved if item.get("result")]
    return {
        "file": csv_path.name,
        "requested": len(names),
        "resolved": len(good),
        "locations": good,
    }


@app.post("/api/query")
async def query(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip().lower()

    if not action:
        raise HTTPException(status_code=400, detail="Missing required field: action")

    if action == "geocode":
        q = payload.get("q") or payload.get("query") or payload.get("location")
        if not isinstance(q, str) or not q.strip():
            raise HTTPException(
                status_code=400,
                detail="For action='geocode', provide a non-empty string in q/query/location",
            )
        return {"action": "geocode", **(await geocode_lookup(q.strip()))}

    if action == "list_location_files":
        return {"action": action, **(await list_location_files())}

    if action == "view_location_file":
        filename = str(payload.get("filename", "")).strip()
        if not filename:
            raise HTTPException(status_code=400, detail="For action='view_location_file', provide filename")
        return {"action": action, **(await resolved_locations(filename))}

    raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")
