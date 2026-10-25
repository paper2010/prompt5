const { app, BrowserWindow } = require("electron");
const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

let mainWindow = null;
let backendProcess = null;
let backendPort = 0;

function log(message) {
  try {
    const logDir = app.getPath("logs");
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(path.join(logDir, "desktop.log"), `[${new Date().toISOString()}] ${message}\n`);
  } catch {
    // Logging must never prevent startup.
  }
}

process.on("uncaughtException", (error) => {
  log(`uncaughtException: ${error.stack || error}`);
});
process.on("unhandledRejection", (error) => {
  log(`unhandledRejection: ${error && error.stack ? error.stack : String(error)}`);
});

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

function backendExecutablePath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend", "prompt5-backend.exe");
  }
  return path.join(__dirname, "..", "dist", "prompt5-backend.exe");
}

function startBackend(port) {
  const executable = backendExecutablePath();
  const userDataDir = app.getPath("userData");
  log(`starting backend: ${executable} port=${port} data=${userDataDir}`);
  try {
    backendProcess = spawn(
      executable,
      ["--host", "127.0.0.1", "--port", String(port), "--data-dir", userDataDir],
      {
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      },
    );
  } catch (error) {
    log(`spawn threw: ${error.stack || error}`);
    app.quit();
    return;
  }
  backendProcess.stdout.on("data", (chunk) => log(`backend stdout: ${String(chunk).trim()}`));
  backendProcess.stderr.on("data", (chunk) => log(`backend stderr: ${String(chunk).trim()}`));
  backendProcess.on("error", (error) => {
    log(`backend error: ${error.stack || error}`);
    app.quit();
  });
  backendProcess.on("exit", (code, signal) => log(`backend exited: code=${code} signal=${signal}`));
}

function waitForBackend(port) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const timer = setInterval(() => {
      const request = http.get(`http://127.0.0.1:${port}/healthz`, (response) => {
        if (response.statusCode === 200) {
          clearInterval(timer);
          log(`backend healthy on ${port}`);
          resolve();
        }
      });
      request.on("error", () => {
        if (Date.now() - started > 15000) {
          clearInterval(timer);
          log(`backend startup timeout on ${port}`);
          reject(new Error("Backend startup timeout"));
        }
      });
    }, 300);
  });
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) return;
  try {
    if (process.platform === "win32") {
      execFileSync("taskkill", ["/pid", String(backendProcess.pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
        timeout: 5000,
      });
    } else {
      backendProcess.kill("SIGTERM");
    }
    log("backend stopped");
  } catch (error) {
    log(`stopBackend failed: ${error && error.message ? error.message : String(error)}`);
  } finally {
    backendProcess = null;
  }
}

async function createWindow() {
  log("app ready");
  backendPort = await getFreePort();
  log(`selected backend port ${backendPort}`);
  startBackend(backendPort);

  try {
    await waitForBackend(backendPort);
  } catch (error) {
    log(`waitForBackend failed: ${error.stack || error}`);
    stopBackend();
    app.quit();
    return;
  }

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1120,
    minHeight: 720,
    title: "Prompt5",
    backgroundColor: "#f5f6f8",
    autoHideMenuBar: true,
    show: false,
  });

  mainWindow.webContents.on("did-fail-load", (_event, code, description) => {
    log(`did-fail-load: ${code} ${description}`);
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  await mainWindow.loadURL(`http://127.0.0.1:${backendPort}`);
  log("window loaded");
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  stopBackend();
  app.quit();
});

app.on("before-quit", () => {
  stopBackend();
});

app.on("activate", () => {
  if (mainWindow === null) createWindow();
});
