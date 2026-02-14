const CesiumLib = window.Cesium;

const MAX_LOG_LINES = 14;
const debugEl = document.getElementById("debug-log");
const fatalEl = document.getElementById("fatal-error");

function debug(message, level = "info") {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  if (level === "error") {
    console.error("[Earth Explorer]", message);
  } else {
    console.log("[Earth Explorer]", message);
  }

  if (!debugEl) {
    return;
  }

  const existing = debugEl.textContent ? debugEl.textContent.split("\n") : [];
  existing.push(line);
  debugEl.textContent = existing.slice(-MAX_LOG_LINES).join("\n");
}

function showFatal(message) {
  if (!fatalEl) {
    return;
  }
  fatalEl.textContent = message;
  fatalEl.hidden = false;
}

window.addEventListener("error", (event) => {
  debug(`Window error: ${event.message}`, "error");
});

window.addEventListener("unhandledrejection", (event) => {
  debug(`Unhandled rejection: ${String(event.reason)}`, "error");
});

function parseLocationCommand(raw) {
  const input = raw.trim();
  if (!input) {
    return null;
  }

  const match = input.match(/^(show me|go to|fly to)\s+(.+)$/i);
  if (match) {
    return match[2].trim();
  }

  return input;
}

async function geocode(query) {
  const url = "http://127.0.0.1:8000/api/query";

  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action: "geocode", q: query }),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail ? `: ${payload.detail}` : "";
    throw new Error(`Backend geocoding failed with ${response.status}${detail}`);
  }

  return payload.result || null;
}

async function boot() {
  if (!CesiumLib) {
    throw new Error("Cesium failed to load from local node_modules.");
  }
  debug("Boot start");
  debug("Geocoding route: POST http://127.0.0.1:8000/api/query");

  const globeContainer = document.getElementById("globe-container");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatLog = document.getElementById("chat-log");

  if (!globeContainer || !chatForm || !chatInput || !chatLog) {
    throw new Error("Required DOM elements are missing.");
  }

  debug("Initializing Cesium viewer");

  const viewerOptions = {
    animation: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    infoBox: false,
    navigationHelpButton: false,
    sceneModePicker: false,
    selectionIndicator: false,
    timeline: false,
    fullscreenButton: false,
    shouldAnimate: true,
  };

  const viewer = new CesiumLib.Viewer("globe-container", viewerOptions);
  viewer.scene.globe.baseColor = CesiumLib.Color.BLACK;

  // Always attach imagery explicitly for cross-version reliability.
  let osmProvider;
  if (typeof CesiumLib.OpenStreetMapImageryProvider.fromUrl === "function") {
    debug("Using OSM provider via fromUrl()");
    osmProvider = await CesiumLib.OpenStreetMapImageryProvider.fromUrl("https://tile.openstreetmap.org/");
  } else {
    debug("Using OSM provider via constructor");
    osmProvider = new CesiumLib.OpenStreetMapImageryProvider({
      url: "https://tile.openstreetmap.org/",
    });
  }

  if (osmProvider?.errorEvent?.addEventListener) {
    osmProvider.errorEvent.addEventListener((err) => {
      debug(`OSM imagery error: ${err?.message || "unknown tile error"}`, "error");
    });
  }

  viewer.imageryLayers.removeAll();
  viewer.imageryLayers.addImageryProvider(osmProvider);
  debug("OSM imagery layer attached");

  viewer.scene.globe.enableLighting = true;
  viewer.camera.setView({
    destination: CesiumLib.Cartesian3.fromDegrees(0, 15, 22000000),
  });

  debug("Cesium viewer ready");

  const marker = viewer.entities.add({
    position: CesiumLib.Cartesian3.fromDegrees(0, 0, 0),
    point: {
      pixelSize: 10,
      color: CesiumLib.Color.fromCssColorString("#ff5f5f"),
      outlineColor: CesiumLib.Color.WHITE,
      outlineWidth: 2,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
    show: false,
  });
  let activeShapeDataSource = null;

  function clearActiveShape() {
    if (activeShapeDataSource) {
      viewer.dataSources.remove(activeShapeDataSource, true);
      activeShapeDataSource = null;
    }
  }

  async function showShape(feature) {
    if (!feature?.geometry || !feature.geometry.type) {
      return false;
    }

    clearActiveShape();

    const geojsonFeature = {
      type: "Feature",
      geometry: feature.geometry,
      properties: {
        name: feature.display_name || "shape",
      },
    };

    const ds = await CesiumLib.GeoJsonDataSource.load(geojsonFeature, {
      stroke: CesiumLib.Color.fromCssColorString("#4fc3ff"),
      fill: CesiumLib.Color.fromCssColorString("#4fc3ff").withAlpha(0.24),
      strokeWidth: 3,
      clampToGround: true,
    });

    activeShapeDataSource = ds;
    viewer.dataSources.add(ds);

    // Normalize styling across polygon and line features.
    ds.entities.values.forEach((entity) => {
      if (entity.polygon) {
        entity.polygon.outline = true;
        entity.polygon.outlineColor = CesiumLib.Color.fromCssColorString("#7fd6ff");
        entity.polygon.material = CesiumLib.Color.fromCssColorString("#4fc3ff").withAlpha(0.24);
      }
      if (entity.polyline) {
        entity.polyline.width = 4;
        entity.polyline.material = CesiumLib.Color.fromCssColorString("#7fd6ff");
      }
    });

    await viewer.flyTo(ds, {
      duration: 2.0,
      offset: new CesiumLib.HeadingPitchRange(0, CesiumLib.Math.toRadians(-50), 0),
    });
    return true;
  }

  function addMessage(text, role = "bot") {
    const bubble = document.createElement("div");
    bubble.className = `msg ${role}`;
    bubble.textContent = text;
    chatLog.appendChild(bubble);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  addMessage("Ready. Ask for a place with 'show me <location>'.");
  debug("Scene initialized; drag to rotate and scroll to zoom to streets.");

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const raw = chatInput.value;
    const location = parseLocationCommand(raw);

    if (!location) {
      return;
    }

    addMessage(raw, "user");
    chatInput.value = "";

    try {
      addMessage(`Looking for ${location}...`);
      debug(`Geocoding: ${location}`);
      const result = await geocode(location);

      if (!result) {
        addMessage(`I could not find '${location}'. Try a more specific name.`);
        return;
      }

      const lat = Number(result.lat);
      const lon = Number(result.lon);
      const drewShape = await showShape(result);

      if (!drewShape) {
        clearActiveShape();
      }

      const placePoint = CesiumLib.Cartesian3.fromDegrees(lon, lat, 0);
      marker.position = placePoint;
      marker.show = true;

      if (!drewShape) {
        viewer.camera.flyToBoundingSphere(new CesiumLib.BoundingSphere(placePoint, 1200), {
          duration: 2.0,
          offset: new CesiumLib.HeadingPitchRange(0, CesiumLib.Math.toRadians(-45), 9000),
        });
      }

      addMessage(`Showing ${result.display_name}`);
      debug(
        `Fly-to target lat=${lat.toFixed(4)} lon=${lon.toFixed(4)} mode=${drewShape ? "shape" : "point"}`
      );
    } catch (error) {
      addMessage("Lookup failed. Check your network connection and try again.");
      debug(`Geocode failed: ${error.message}`, "error");
    }
  });

  let frames = 0;
  viewer.scene.preRender.addEventListener(() => {
    frames += 1;
    if (frames === 120) {
      debug("Render heartbeat OK (120 frames)");
    }
  });
}

boot().catch((error) => {
  debug(`Boot failed: ${error.message}`, "error");
  showFatal(`Startup failed: ${error.message}`);
});
