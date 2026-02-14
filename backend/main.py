from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from typing import Any

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


@app.get("/api/geocode")
async def geocode(q: str = Query(..., min_length=1)) -> dict[str, Any]:
    return await geocode_lookup(q)


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

    raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")
