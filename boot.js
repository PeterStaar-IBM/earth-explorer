(function () {
  const MAX_LINES = 20;
  const debugEl = document.getElementById("debug-log");
  const fatalEl = document.getElementById("fatal-error");

  function log(message, level) {
    const line = `[${new Date().toLocaleTimeString()}] [loader] ${message}`;
    if (level === "error") {
      console.error("[Earth Explorer Loader]", message);
    } else {
      console.log("[Earth Explorer Loader]", message);
    }

    if (debugEl) {
      const current = debugEl.textContent ? debugEl.textContent.split("\n") : [];
      current.push(line);
      debugEl.textContent = current.slice(-MAX_LINES).join("\n");
    }
  }

  function fatal(message) {
    log(message, "error");
    if (fatalEl) {
      fatalEl.textContent = `Startup failed: ${message}`;
      fatalEl.hidden = false;
    }
  }

  function loadScript(src, label) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = false;
      script.onload = () => {
        log(`${label} loaded`);
        resolve();
      };
      script.onerror = () => {
        reject(new Error(`${label} failed to load from ${src}`));
      };
      document.body.appendChild(script);
    });
  }

  window.addEventListener("error", (event) => {
    log(`window error: ${event.message}`, "error");
  });

  window.addEventListener("unhandledrejection", (event) => {
    log(`unhandled rejection: ${String(event.reason)}`, "error");
  });

  log("Boot loader started");

  loadScript("./node_modules/cesium/Build/Cesium/Cesium.js", "Cesium")
    .then(() => {
      if (!window.Cesium) {
        throw new Error("Cesium global missing after script load.");
      }
      return loadScript("./app.js", "App runtime");
    })
    .catch((error) => {
      fatal(error.message);
    });
})();
