/* Transport-agnostic viewer UI. Works against the live HTTP transport
 * (Phase 1) and the recording replay transport (Phase 2a); a future Pyodide
 * worker transport (Phase 2b) plugs in the same way. */
var Viewer = (function () {
  var transport = null;
  var state = null;
  var zoom = 1;
  var logicalW = 720, logicalH = 480;

  function $(id) { return document.getElementById(id); }

  function controlTopic(suffix) {
    var prefix = (state && state.prefixes && state.prefixes.control) || "lcars/alert-panel/";
    return prefix + suffix;
  }

  function dataTopic(suffix) {
    var prefix = (state && state.prefixes && state.prefixes.topic) || "home/alert/";
    return prefix + suffix;
  }

  function applyZoom() {
    var img = $("screen");
    img.style.width = (logicalW * zoom) + "px";
    img.style.height = (logicalH * zoom) + "px";
  }

  function onFrame(info) {
    var img = $("screen");
    if (info.w) { logicalW = info.w; logicalH = info.h; applyZoom(); }
    img.src = transport.frameUrl(info.seq);
    $("chip-seq").textContent = "FRAME: " + info.seq;
    $("screen-hint").classList.add("hidden");
  }

  function onState(s) {
    state = s;
    window.__vpState = s;  // exposed for automated tests
    if (s.dims && s.dims.logical_w) { logicalW = s.dims.logical_w; logicalH = s.dims.logical_h; applyZoom(); }
    setChip("chip-conn", "CONN: " + (s.connected ? "UP" : "DOWN"), s.connected);
    var avail = s.availability || "—";
    setChip("chip-avail", "AVAIL: " + avail, avail === "online");
    $("chip-mode").textContent = "MODE: " + (s.mode || "—");

    var tbody = $("retained-table").querySelector("tbody");
    tbody.innerHTML = "";
    Object.keys(s.retained || {}).sort().forEach(function (topic) {
      var tr = document.createElement("tr");
      var td1 = document.createElement("td"); td1.textContent = topic;
      var td2 = document.createElement("td"); td2.textContent = s.retained[topic];
      tr.appendChild(td1); tr.appendChild(td2); tbody.appendChild(tr);
    });

    var log = $("publish-log");
    log.innerHTML = "";
    (s.panel_publishes || []).slice(-12).reverse().forEach(function (e) {
      var li = document.createElement("li");
      li.textContent = "[" + e.origin + "] " + e.topic + " = " + e.payload +
        (e.retain ? " (retained)" : "");
      log.appendChild(li);
    });
  }

  function setChip(id, text, ok) {
    var el = $(id);
    el.textContent = text;
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("bad", !ok);
  }

  function onConnection(up) {
    $("respawn-banner").classList.toggle("hidden", up);
  }

  function wire() {
    // Command buttons publish to the control topic.
    document.querySelectorAll("button[data-cmd]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        transport.sendMqtt(controlTopic(btn.dataset.cmd), btn.dataset.payload, false);
      });
    });

    // Sample events.
    document.querySelectorAll("button.sample").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var imp = btn.dataset.importance;
        transport.sendMqtt(dataTopic("virtual/" + imp), JSON.stringify({
          message: "Sample " + imp.toUpperCase() + " event from the virtual viewer",
          source: "virtual-ui",
          importance: imp,
        }), false);
      });
    });

    // Free-form publish.
    $("publish-form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      transport.sendMqtt($("pub-topic").value, $("pub-payload").value,
        $("pub-retain").checked);
    });

    // Broker chaos.
    $("btn-drop").addEventListener("click", function () { transport.brokerDrop(); });
    $("btn-broker-restart").addEventListener("click", function () { transport.brokerRestart(); });

    // Click = touch, mapped through the displayed scale.
    $("screen").addEventListener("click", function (ev) {
      var rect = ev.target.getBoundingClientRect();
      var x = (ev.clientX - rect.left) * (logicalW / rect.width);
      var y = (ev.clientY - rect.top) * (logicalH / rect.height);
      transport.sendTouch(Math.round(x), Math.round(y));
    });

    $("zoom").addEventListener("change", function (ev) {
      zoom = parseFloat(ev.target.value);
      applyZoom();
    });

    if (transport.capabilities.readOnly) {
      document.querySelectorAll("button, form input").forEach(function (el) {
        el.disabled = true;
      });
    }
  }

  return {
    init: function (t) {
      transport = t;
      transport.onFrame(onFrame);
      transport.onState(onState);
      if (transport.onConnection) transport.onConnection(onConnection);
      wire();
      applyZoom();
      transport.start();
    },
  };
})();
