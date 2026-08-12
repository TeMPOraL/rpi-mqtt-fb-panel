/* Recording replayer: plays back frames + timeline recorded by
 * `snapshot.py run --record` and committed under virtual/recordings/<name>/.
 * Static-only — works from GitHub Pages, `python3 -m http.server` at the
 * repo root, or the live harness server (which maps /recordings/ too). */
(function () {
  function $(id) { return document.getElementById(id); }

  var rec = new URLSearchParams(location.search).get("rec") || "demo";
  var base = "../recordings/" + rec + "/";
  var manifest = null;
  var frames = [];        // preloaded Image objects
  var idx = 0;
  var playing = false;
  var timer = null;

  function fmt(ms) { return (ms / 1000).toFixed(1) + "s"; }

  function show(i) {
    if (!manifest || !manifest.frames.length) return;
    idx = Math.max(0, Math.min(i, manifest.frames.length - 1));
    var f = manifest.frames[idx];
    $("screen").src = frames[idx].src;
    $("scrub").value = idx;
    $("chip-frame").textContent = "FRAME: " + (idx + 1) + "/" + manifest.frames.length;
    var total = manifest.frames[manifest.frames.length - 1].t_ms;
    $("time").textContent = fmt(f.t_ms) + " / " + fmt(total);
  }

  function scheduleNext() {
    if (!playing) return;
    if (idx >= manifest.frames.length - 1) { setPlaying(false); return; }
    var speed = parseFloat($("speed").value);
    var dt = (manifest.frames[idx + 1].t_ms - manifest.frames[idx].t_ms) / speed;
    timer = setTimeout(function () { show(idx + 1); scheduleNext(); },
                       Math.max(30, Math.min(dt, 5000)));
  }

  function setPlaying(p) {
    playing = p;
    $("play").textContent = p ? "PAUSE" : "PLAY";
    clearTimeout(timer);
    if (p) {
      if (idx >= manifest.frames.length - 1) show(0);
      scheduleNext();
    }
  }

  fetch(base + "manifest.json")
    .then(function (r) {
      if (!r.ok) throw new Error("manifest not found: " + base);
      return r.json();
    })
    .then(function (m) {
      manifest = m;
      $("chip-rec").textContent = "REC: " + (m.name || rec);
      $("rec-meta").textContent = m.description || "";
      if (m.dims) {
        $("screen").style.width = m.dims.w + "px";
        $("screen").style.height = m.dims.h + "px";
      }
      $("scrub").max = m.frames.length - 1;
      m.frames.forEach(function (f) {
        var img = new Image();
        img.src = base + f.file;
        frames.push(img);
      });
      var list = $("event-list");
      m.events.forEach(function (e) {
        var li = document.createElement("li");
        var t = document.createElement("span");
        t.className = "t";
        t.textContent = fmt(e.t_ms);
        li.appendChild(t);
        li.appendChild(document.createTextNode(
          e.type + " " + JSON.stringify(e.detail)));
        li.addEventListener("click", function () {
          // Jump to the last frame at or before this event.
          var target = 0;
          m.frames.forEach(function (f, i) { if (f.t_ms <= e.t_ms) target = i; });
          setPlaying(false);
          show(target);
        });
        list.appendChild(li);
      });
      $("hint").classList.add("hidden");
      show(0);
    })
    .catch(function (err) {
      $("hint").textContent = "Failed to load recording '" + rec + "': " + err.message;
    });

  $("play").addEventListener("click", function () { setPlaying(!playing); });
  $("scrub").addEventListener("input", function (ev) {
    setPlaying(false);
    show(parseInt(ev.target.value, 10));
  });
})();
