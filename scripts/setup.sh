#!/usr/bin/env bash
set -euo pipefail

printf "\n[1/5] Installing npm dependencies...\n"
npm install

printf "\n[2/5] Syncing Python backend environment with uv...\n"
if command -v uv >/dev/null 2>&1; then
  uv sync --project backend --no-install-project
  printf "  ok   uv environment synced\n"
else
  printf "  warn uv not found (backend cannot run)\n"
fi

printf "\n[3/5] Verifying required local files...\n"
required=(
  "node_modules/cesium/Build/Cesium/Cesium.js"
  "node_modules/cesium/Build/Cesium/Widgets/widgets.css"
  "index.html"
  "boot.js"
  "app.js"
  "styles.css"
  "main.js"
  "backend/main.py"
  "backend/pyproject.toml"
  "backend/uv.lock"
)

for file in "${required[@]}"; do
  if [[ -f "$file" ]]; then
    printf "  ok   %s\n" "$file"
  else
    printf "  miss %s\n" "$file"
    exit 1
  fi
done

printf "\n[4/5] Checking network endpoints used at runtime...\n"
if command -v curl >/dev/null 2>&1; then
  if curl -sSf --max-time 10 "https://tile.openstreetmap.org/0/0/0.png" >/dev/null; then
    printf "  ok   OSM tiles reachable\n"
  else
    printf "  warn OSM tiles not reachable (street imagery will fail)\n"
  fi

  if curl -sSf --max-time 10 "https://nominatim.openstreetmap.org/search?q=Paris&format=json&limit=1" >/dev/null; then
    printf "  ok   Nominatim geocoding reachable\n"
  else
    printf "  warn Nominatim not reachable (chat search via backend will fail)\n"
  fi
else
  printf "  warn curl not available; skipped endpoint checks\n"
fi

printf "\n[5/5] Setup complete.\n"
printf "Run: npm start\n\n"
