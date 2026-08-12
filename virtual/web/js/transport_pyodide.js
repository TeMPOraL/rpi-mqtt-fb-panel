/* Pyodide transport (Phase 2b): runs the panel in a Web Worker and adapts it
 * to the same viewer interface as the HTTP transport.
 *
 * Frames arrive as transferable RGBA buffers and are converted to data URLs
 * through an offscreen canvas so viewer.js can keep using a plain <img>.
 * Input flows through a SharedArrayBuffer ring (the worker is blocked inside
 * the panel's main loop and cannot receive postMessage): 64 slots x 4096
 * bytes, Int32 header [writeIdx, readIdx, dropped] at offset 0, data at
 * byte 64. Requires window.crossOriginIsolated (coi-serviceworker on Pages).
 */
function TransportPyodide(options) {
  options = options || {};
  var frameCb = null, stateCb = null, connCb = null, logCb = null;
  var worker = null, sab = null, i32 = null, u8 = null;
  var seq = 0, frameDataUrl = null;
  var canvas = document.createElement("canvas");
  var encoder = new TextEncoder();
  var SLOTS = 64, SLOT_SIZE = 4096;

  function writeRecord(obj) {
    if (!i32) return;
    var payload = encoder.encode(JSON.stringify(obj));
    if (payload.length > SLOT_SIZE - 4) return;
    var writeIdx = Atomics.load(i32, 0);
    var readIdx = Atomics.load(i32, 1);
    if (writeIdx - readIdx >= SLOTS) {
      Atomics.add(i32, 2, 1); // ring full; drop (panel drains every ~10ms)
      return;
    }
    var base = (writeIdx % SLOTS) * SLOT_SIZE;
    u8[base] = payload.length & 0xff;
    u8[base + 1] = (payload.length >> 8) & 0xff;
    u8[base + 2] = (payload.length >> 16) & 0xff;
    u8[base + 3] = (payload.length >> 24) & 0xff;
    u8.set(payload, base + 4);
    Atomics.store(i32, 0, writeIdx + 1);
  }

  function onWorkerMessage(ev) {
    var m = ev.data;
    if (m.type === "frame") {
      canvas.width = m.w;
      canvas.height = m.h;
      var ctx = canvas.getContext("2d");
      var img = new ImageData(new Uint8ClampedArray(m.buf), m.w, m.h);
      ctx.putImageData(img, 0, 0);
      frameDataUrl = canvas.toDataURL("image/png");
      seq += 1;
      if (connCb) connCb(true);
      if (frameCb) frameCb({ seq: seq, w: m.w, h: m.h });
    } else if (m.type === "state") {
      if (stateCb) stateCb(m.state);
    } else if (m.type === "log") {
      if (logCb) logCb(m.line);
    } else if (m.type === "ready") {
      if (logCb) logCb("[worker ready; font fallback: " + m.fontFallback + "]");
    } else if (m.type === "exit") {
      if (logCb) logCb("[panel exited with code " + m.code + "]");
      if (connCb) connCb(false);
      worker.terminate();
      worker = null;
      if (m.code !== 0) {
        // systemd Restart=always emulation: cold-start a fresh worker.
        setTimeout(spawn, 2000);
      }
    } else if (m.type === "fatal") {
      if (logCb) logCb("[FATAL] " + m.error);
      if (connCb) connCb(false);
    }
  }

  function spawn() {
    // Reset ring indices for the fresh worker.
    Atomics.store(i32, 0, 0);
    Atomics.store(i32, 1, 0);
    Atomics.store(i32, 2, 0);
    worker = new Worker("js/worker_panel.js", { type: "module" });
    worker.onmessage = onWorkerMessage;
    worker.postMessage({
      type: "init",
      sab: sab,
      swissFont: options.swissFont || null, // ArrayBuffer or null
      config: {
        env: options.env || {},
        fb_width: 720, fb_height: 480, fb_bpp: 32,
        touch_abs_max: 4095,
        // Resolve to an absolute URL: the worker's relative base differs.
        pyodide_base: options.pyodideBase
          ? new URL(options.pyodideBase, location.href).href : null,
      },
    });
  }

  return {
    capabilities: { readOnly: false, live: true },
    start: function () {
      if (!window.crossOriginIsolated) {
        throw new Error("crossOriginIsolated is false - SharedArrayBuffer unavailable");
      }
      sab = new SharedArrayBuffer(64 + 64 * 4096);
      i32 = new Int32Array(sab, 0, 16);
      u8 = new Uint8Array(sab, 64);
      spawn();
    },
    onFrame: function (cb) { frameCb = cb; },
    onState: function (cb) { stateCb = cb; },
    onConnection: function (cb) { connCb = cb; },
    onLog: function (cb) { logCb = cb; },
    frameUrl: function (_seq) { return frameDataUrl; },
    sendMqtt: function (topic, payload, retain) {
      writeRecord({ t: "mqtt", topic: topic, payload: payload, retain: !!retain });
    },
    sendTouch: function (x, y) { writeRecord({ t: "touch", x: x, y: y }); },
    brokerDrop: function () { writeRecord({ t: "ctl", op: "drop" }); },
    brokerRestart: function () { writeRecord({ t: "ctl", op: "restart" }); },
  };
}
