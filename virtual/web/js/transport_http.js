/* HTTP transport for the live virtual panel (Phase 1).
 * Implements the transport interface consumed by viewer.js:
 *   { start(), onFrame(cb), onState(cb), frameUrl(seq),
 *     sendMqtt(topic, payload, retain), sendTouch(x, y),
 *     brokerDrop(), brokerRestart(), capabilities }
 * Frames arrive as SSE 'frame' events carrying a sequence number; the viewer
 * loads /frame.png?seq=N (the query only busts caches). SSE reconnects with
 * backoff, which also covers the respawn gap after the panel restart command.
 */
function TransportHttp() {
  var frameCb = null, stateCb = null, connCb = null;
  var es = null, retryMs = 500;

  function connect() {
    es = new EventSource("/events");
    es.addEventListener("frame", function (ev) {
      retryMs = 500;
      if (connCb) connCb(true);
      if (frameCb) frameCb(JSON.parse(ev.data));
    });
    es.addEventListener("state", function (ev) {
      retryMs = 500;
      if (connCb) connCb(true);
      if (stateCb) stateCb(JSON.parse(ev.data));
    });
    es.onerror = function () {
      if (connCb) connCb(false);
      es.close();
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 5000);
    };
  }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  return {
    capabilities: { readOnly: false, live: true },
    start: function () { connect(); },
    onFrame: function (cb) { frameCb = cb; },
    onState: function (cb) { stateCb = cb; },
    onConnection: function (cb) { connCb = cb; },
    frameUrl: function (seq) { return "/frame.png?seq=" + seq; },
    sendMqtt: function (topic, payload, retain) {
      return post("/mqtt", { topic: topic, payload: payload, retain: !!retain });
    },
    sendTouch: function (x, y) { return post("/touch", { x: x, y: y }); },
    brokerDrop: function () { return post("/broker/drop"); },
    brokerRestart: function () { return post("/broker/restart"); },
  };
}
