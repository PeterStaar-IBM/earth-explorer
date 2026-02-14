const { app, BrowserWindow } = require("electron");
const path = require("path");
const { spawn } = require("child_process");

let backendProc = null;

function startBackend() {
  if (backendProc) {
    return;
  }

  const uvCmd = process.platform === "win32" ? "uv.exe" : "uv";
  const args = [
    "run",
    "--project",
    "backend",
    "uvicorn",
    "backend.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
  ];

  backendProc = spawn(uvCmd, args, {
    cwd: __dirname,
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProc.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });

  backendProc.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });

  backendProc.on("exit", (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`);
    backendProc = null;
  });

  backendProc.on("error", (error) => {
    console.error(`[backend] failed to start: ${error.message}`);
    backendProc = null;
  });
}

function stopBackend() {
  if (!backendProc) {
    return;
  }

  backendProc.kill("SIGTERM");
  backendProc = null;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1500,
    height: 920,
    minWidth: 1000,
    minHeight: 700,
    backgroundColor: "#05070d",
    title: "Earth Explorer",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.loadFile(path.join(__dirname, "index.html"));
}

app.whenReady().then(() => {
  startBackend();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", () => {
  stopBackend();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
