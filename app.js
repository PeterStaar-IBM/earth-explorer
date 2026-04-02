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

const SLASH_COMMANDS = ["/show", "/list", "/view", "/logs", "/earth", "/help"];

let autocompleteState = {
  mode: "",
  prefix: "",
  matches: [],
  index: -1,
};

function resetAutocompleteState() {
  autocompleteState = {
    mode: "",
    prefix: "",
    matches: [],
    index: -1,
  };
}

function parseIntent(raw) {
  const input = raw.trim();
  if (!input) {
    return { type: "none" };
  }

  if (!input.startsWith("/")) {
    return { type: "geocode", location: parseLocationCommand(input) };
  }

  const parts = input.split(/\s+/);
  const cmd = (parts[0] || "").toLowerCase();
  const args = input.slice(parts[0].length).trim();

  if (cmd === "/help") {
    return { type: "help" };
  }

  if (cmd === "/logs") {
    return { type: "show_logs" };
  }

  if (cmd === "/earth") {
    return { type: "show_earth" };
  }

  if (cmd === "/list") {
    return { type: "list_files" };
  }

  if (cmd === "/view") {
    if (!args) {
      return { type: "error", message: "Usage: /view <filename.csv>" };
    }
    return { type: "view_file", filename: args };
  }

  if (cmd === "/show") {
    if (!args) {
      return { type: "error", message: "Usage: /show <place|logs|earth>" };
    }
    if (/^logs?$/i.test(args)) {
      return { type: "show_logs" };
    }
    if (/^(earth|globe|map)$/i.test(args)) {
      return { type: "show_earth" };
    }
    return { type: "geocode", location: args };
  }

  return { type: "error", message: `Unknown command: ${cmd}. Try /help.` };
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

async function listLocationFiles() {
  const response = await fetch("http://127.0.0.1:8000/api/location-files", {
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || `Failed to list files (${response.status})`);
  }
  return payload.files || [];
}

async function resolvedFileLocations(filename) {
  const encoded = encodeURIComponent(filename);
  const response = await fetch(`http://127.0.0.1:8000/api/location-files/${encoded}/resolved-locations`, {
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || `Failed to view file (${response.status})`);
  }
  return payload;
}

async function boot() {
  if (!CesiumLib) {
    throw new Error("Cesium failed to load from local node_modules.");
  }
  debug("Boot start");
  debug("Geocoding route: POST http://127.0.0.1:8000/api/query");

  const globeContainer = document.getElementById("globe-container");
  const tableView = document.getElementById("table-view");
  const logsView = document.getElementById("logs-view");
  const filesTableBody = document.getElementById("files-table-body");
  const hud = document.querySelector(".hud");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatLog = document.getElementById("chat-log");

  if (!globeContainer || !tableView || !logsView || !filesTableBody || !hud || !chatForm || !chatInput || !chatLog) {
    throw new Error("Required DOM elements are missing.");
  }

  function showGlobeView() {
    tableView.hidden = true;
    logsView.hidden = true;
    globeContainer.hidden = false;
    hud.hidden = false;
  }

  function showTableView() {
    logsView.hidden = true;
    tableView.hidden = false;
    globeContainer.hidden = true;
    hud.hidden = true;
  }

  function showLogsView() {
    tableView.hidden = true;
    logsView.hidden = false;
    globeContainer.hidden = true;
    hud.hidden = true;
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
    },
    show: false,
  });

  let activeShapeDataSource = null;
  const fileLocationsDataSource = new CesiumLib.CustomDataSource("file-locations");
  viewer.dataSources.add(fileLocationsDataSource);
  let cachedFileNames = [];

  function clearActiveShape() {
    if (activeShapeDataSource) {
      viewer.dataSources.remove(activeShapeDataSource, true);
      activeShapeDataSource = null;
    }
  }

  function clearFileLocations() {
    fileLocationsDataSource.entities.removeAll();
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
      stroke: CesiumLib.Color.fromCssColorString("#ff7f7f"),
      fill: CesiumLib.Color.fromCssColorString("#ff4f4f").withAlpha(0.24),
      strokeWidth: 3,
      clampToGround: true,
    });

    activeShapeDataSource = ds;
    viewer.dataSources.add(ds);

    ds.entities.values.forEach((entity) => {
      if (entity.polygon) {
        entity.polygon.outline = true;
        entity.polygon.outlineColor = CesiumLib.Color.fromCssColorString("#ff9c9c");
        entity.polygon.material = CesiumLib.Color.fromCssColorString("#ff4f4f").withAlpha(0.24);
      }
      if (entity.polyline) {
        entity.polyline.width = 4;
        entity.polyline.material = CesiumLib.Color.fromCssColorString("#ff9c9c");
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

  function renderFilesTable(files) {
    filesTableBody.innerHTML = "";

    if (!files.length) {
      const row = document.createElement("tr");
      row.innerHTML = '<td colspan="3">No CSV files found in backend/output.</td>';
      filesTableBody.appendChild(row);
      return;
    }

    files.forEach((file) => {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${file.name}</td><td>${file.size_bytes}</td><td>${file.modified_utc}</td>`;
      filesTableBody.appendChild(row);
    });
  }

  async function plotResolvedLocations(payload) {
    clearActiveShape();
    clearFileLocations();
    marker.show = false;

    const points = [];
    const locations = payload.locations || [];

    locations.forEach((entry) => {
      const result = entry.result || {};
      const lat = Number(result.lat);
      const lon = Number(result.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        return;
      }

      const position = CesiumLib.Cartesian3.fromDegrees(lon, lat, 0);
      points.push(position);

      fileLocationsDataSource.entities.add({
        position,
        point: {
          pixelSize: 7,
          color: CesiumLib.Color.fromCssColorString("#ff5f5f"),
          outlineColor: CesiumLib.Color.WHITE,
          outlineWidth: 1,
        },
        label: {
          text: entry.query,
          font: "12px sans-serif",
          fillColor: CesiumLib.Color.WHITE,
          outlineColor: CesiumLib.Color.BLACK,
          outlineWidth: 2,
          style: CesiumLib.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new CesiumLib.Cartesian2(0, -16),
        },
      });
    });

    if (!points.length) {
      addMessage(`No resolvable locations in ${payload.file}.`, "bot");
      return;
    }

    await viewer.flyTo(fileLocationsDataSource, {
      duration: 2.0,
      offset: new CesiumLib.HeadingPitchRange(0, CesiumLib.Math.toRadians(-60), 0),
    });
  }

showGlobeView();

  addMessage("Ready. Use /show <location> to navigate.", "bot");
  addMessage("Commands: /show <place>, /list, /view <filename.csv>, /logs, /earth, /help", "bot");
  debug("Scene initialized; drag to rotate and scroll to zoom to streets.");

  chatInput.addEventListener("input", () => {
    resetAutocompleteState();
  });

  chatInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Tab") {
      return;
    }

    const value = chatInput.value;
    if (!value.startsWith("/")) {
      return;
    }

    event.preventDefault();

    const spaceIndex = value.indexOf(" ");
    const isCommandToken = spaceIndex === -1;

    if (isCommandToken) {
      const prefix = value.toLowerCase();
      const matches = SLASH_COMMANDS.filter((cmd) => cmd.startsWith(prefix));
      if (!matches.length) {
        return;
      }

      if (autocompleteState.mode === "command" && autocompleteState.prefix === prefix) {
        autocompleteState.index = (autocompleteState.index + 1) % matches.length;
      } else {
        autocompleteState = {
          mode: "command",
          prefix,
          matches,
          index: 0,
        };
      }

      chatInput.value = `${matches[autocompleteState.index]} `;
      return;
    }

    const cmd = value.slice(0, spaceIndex).toLowerCase();
    if (cmd !== "/view") {
      return;
    }

    const tail = value.slice(spaceIndex + 1);
    if (tail.includes(" ")) {
      return;
    }

    if (!cachedFileNames.length) {
      try {
        const files = await listLocationFiles();
        cachedFileNames = files.map((f) => f.name);
      } catch {
        return;
      }
    }

    const prefix = tail.toLowerCase();
    const matches = cachedFileNames.filter((name) => name.toLowerCase().startsWith(prefix));
    if (!matches.length) {
      return;
    }

    if (autocompleteState.mode === "view_file" && autocompleteState.prefix === prefix) {
      autocompleteState.index = (autocompleteState.index + 1) % matches.length;
    } else {
      autocompleteState = {
        mode: "view_file",
        prefix,
        matches,
        index: 0,
      };
    }

    chatInput.value = `/view ${matches[autocompleteState.index]}`;
  });

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const raw = chatInput.value;
    const intent = parseIntent(raw);

    if (intent.type === "none") {
      return;
    }

    addMessage(raw, "user");
    chatInput.value = "";

    try {
      if (intent.type === "help") {
        addMessage(
          "Commands: /show <place>, /list, /view <file.csv>, /logs, /earth, /help",
          "bot"
        );
        return;
      }

      if (intent.type === "error") {
        addMessage(intent.message, "bot");
        return;
      }

      if (intent.type === "show_logs") {
        showLogsView();
        addMessage("Showing logs view.", "bot");
        return;
      }

      if (intent.type === "show_earth") {
        showGlobeView();
        addMessage("Showing Earth view.", "bot");
        return;
      }

      if (intent.type === "list_files") {
        debug("Listing location files");
        const files = await listLocationFiles();
        cachedFileNames = files.map((f) => f.name);
        renderFilesTable(files);
        showTableView();
        addMessage(`Found ${files.length} CSV file(s) in backend/output.`, "bot");
        return;
      }

      if (intent.type === "view_file") {
        showGlobeView();
        debug(`Viewing file: ${intent.filename}`);
        addMessage(`Loading locations from ${intent.filename}...`, "bot");
        const payload = await resolvedFileLocations(intent.filename);
        await plotResolvedLocations(payload);
        addMessage(
          `Showing ${payload.resolved}/${payload.requested} resolved locations from ${payload.file}.`,
          "bot"
        );
        return;
      }

      const location = intent.location;
      if (!location) {
        return;
      }

      showGlobeView();
      clearFileLocations();
      addMessage(`Looking for ${location}...`, "bot");
      debug(`Geocoding: ${location}`);
      const result = await geocode(location);

      if (!result) {
        addMessage(`I could not find '${location}'. Try a more specific name.`, "bot");
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

      addMessage(`Showing ${result.display_name}`, "bot");
      debug(
        `Fly-to target lat=${lat.toFixed(4)} lon=${lon.toFixed(4)} mode=${drewShape ? "shape" : "point"}`
      );
    } catch (error) {
      addMessage("Lookup failed. Check your network connection and try again.", "bot");
      debug(`Action failed: ${error.message}`, "error");
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
