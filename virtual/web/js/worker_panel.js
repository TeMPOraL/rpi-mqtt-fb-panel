/* Web Worker (module type) running the UNMODIFIED panel under Pyodide.
 *
 * Receives an init message with the SharedArrayBuffer input ring + config,
 * fetches the panel sources and the virtual shim package same-origin, writes
 * them into the Pyodide FS, then executes virtual/shims/pyodide_boot.py --
 * which runs the real mqtt_fb_panel.main(), blocking this worker forever (by
 * design). Frames leave via synchronous postMessage from inside the loop;
 * input arrives through the SAB ring, drained by the shims' evdev poll hook.
 * Must be created with {type: "module"}: Pyodide >= 314 dropped classic
 * worker support.
 */
"use strict";

var PYODIDE_VERSION = "v314.0.4"; // pinned; Pillow 12.2 in this distribution
// Default: CDN. Overridable via init config.pyodide_base (absolute URL) — used
// by hermetic tests serving a local mirror, or fully self-hosted deployments.
var DEFAULT_PYODIDE_BASE = "https://cdn.jsdelivr.net/pyodide/" + PYODIDE_VERSION + "/full/";

// Repo files needed by the panel + harness, relative to this worker's URL
// (virtual/web/js/ -> repo root is ../../../).
var REPO_FILES = [
  "mqtt_fb_panel.py",
  "lcars_constants.py",
  "lcars_drawing_utils.py",
  "lcars_ui_components.py",
  "lcars_font_cache.py",
  "event_log_mode.py",
  "clock_mode.py",
  "virtual/__init__.py",
  "virtual/harness.py",
  "virtual/shims/__init__.py",
  "virtual/shims/install.py",
  "virtual/shims/broker.py",
  "virtual/shims/fake_paho.py",
  "virtual/shims/fake_evdev.py",
  "virtual/shims/fake_framebuffer.py",
  "virtual/shims/rgb565.py",
  "virtual/shims/pyodide_boot.py",
];

function log(line) { postMessage({ type: "log", line: String(line) }); }

async function fetchText(url) {
  var r = await fetch(url);
  if (!r.ok) throw new Error("fetch failed: " + url + " (" + r.status + ")");
  return r.text();
}

async function fetchBytes(url) {
  var r = await fetch(url);
  if (!r.ok) throw new Error("fetch failed: " + url + " (" + r.status + ")");
  return new Uint8Array(await r.arrayBuffer());
}

async function boot(msg) {
  var config = msg.config;

  // Globals consumed by pyodide_boot.py via the `js` module.
  self.vpSabI32 = new Int32Array(msg.sab, 0, 16);
  self.vpSabU8 = new Uint8Array(msg.sab, 64);
  self.vpPostFrame = function (u8, w, h) {
    postMessage({ type: "frame", w: w, h: h, buf: u8.buffer }, [u8.buffer]);
  };
  self.vpPostState = function (jsonStr) {
    postMessage({ type: "state", state: JSON.parse(jsonStr) });
  };

  var pyodideBase = config.pyodide_base || DEFAULT_PYODIDE_BASE;
  log("loading Pyodide " + PYODIDE_VERSION + " from " + pyodideBase + "...");
  // Pyodide >= 314 requires a module worker; this file is loaded with
  // {type: "module"} and pulls the runtime in via dynamic import.
  var mod = await import(pyodideBase + "pyodide.mjs");
  var pyodide = await mod.loadPyodide({
    indexURL: pyodideBase,
    stdout: log,
    stderr: log,
  });
  log("loading Pillow...");
  await pyodide.loadPackage("pillow");

  log("fetching panel sources...");
  var repoRoot = "/panel";
  pyodide.FS.mkdirTree(repoRoot + "/virtual/shims");
  pyodide.FS.mkdirTree(repoRoot + "/virtual/fonts");
  for (var i = 0; i < REPO_FILES.length; i++) {
    var rel = REPO_FILES[i];
    var text = await fetchText("../../../" + rel);
    pyodide.FS.writeFile(repoRoot + "/" + rel, text);
  }

  // Fonts: vendored DejaVu always; user-provided Swiss911 bytes win.
  var dejavu = await fetchBytes("../../fonts/DejaVuSans.ttf");
  pyodide.FS.writeFile(repoRoot + "/virtual/fonts/DejaVuSans.ttf", dejavu);
  var fontPath = repoRoot + "/virtual/fonts/DejaVuSans.ttf";
  var fontFallback = true;
  if (msg.swissFont) {
    pyodide.FS.writeFile(repoRoot + "/virtual/fonts/Swiss911-user.ttf",
      new Uint8Array(msg.swissFont));
    fontPath = repoRoot + "/virtual/fonts/Swiss911-user.ttf";
    fontFallback = false;
  }
  config.env.LCARS_FONT_PATH = fontPath;
  config.font_fallback = fontFallback;
  config.repo_root = repoRoot;
  self.vpConfig = config;

  postMessage({ type: "ready", fontFallback: fontFallback });
  log("starting panel main() -- worker will now block, frames keep flowing");

  // Blocks until the panel exits (e.g. the MQTT restart command).
  var code = pyodide.runPython(
    "import runpy, sys\n" +
    "sys.path.insert(0, '" + repoRoot + "')\n" +
    "ns = runpy.run_path('" + repoRoot + "/virtual/shims/pyodide_boot.py')\n" +
    "ns['boot']()\n"
  );
  postMessage({ type: "exit", code: code === undefined ? 0 : code });
}

onmessage = function (ev) {
  if (ev.data && ev.data.type === "init") {
    boot(ev.data).catch(function (err) {
      postMessage({ type: "fatal", error: String(err && err.stack || err) });
    });
  }
};
