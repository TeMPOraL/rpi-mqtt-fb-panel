"""Fake `paho.mqtt.client` presenting the paho-mqtt 1.5.x (v1) API surface.

Installed into sys.modules as 'paho.mqtt.client' by install.py. The panel's
`hasattr(mqtt, "CallbackAPIVersion")` check must take the 1.x branch, exactly
as on the device (Raspbian bullseye ships paho 1.5.1) — therefore this module
deliberately does NOT define CallbackAPIVersion. Guarded by a unit test.

Callbacks are invoked with the v1 MQTTv5 signatures the panel implements:
  on_connect(client, userdata, flags_dict, ReasonCode, properties=None)
  on_subscribe(client, userdata, mid, [ReasonCode], properties=None)
  on_disconnect(client, userdata, rc, properties=None)
  on_message(client, userdata, MQTTMessage)
and are delivered from a dedicated per-client network thread, preserving the
device's threading semantics (the panel mutates shared state from callbacks
while the main loop renders — the harness must not serialize that).
"""
import itertools
import queue
import threading
import time
from typing import Any, Optional

from virtual.shims.broker import MiniBroker

MQTTv31 = 3
MQTTv311 = 4
MQTTv5 = 5
MQTT_ERR_SUCCESS = 0
MQTT_ERR_NO_CONN = 4
MQTT_ERR_CONN_LOST = 7
# NOTE: no CallbackAPIVersion here, on purpose (see module docstring).

_BROKER: Optional[MiniBroker] = None
# Inline mode (Pyodide: no threads): loop_start() registers synchronously and
# events are processed by explicit pump_all() calls instead of a network
# thread. CPython keeps the threaded default, preserving device threading.
_INLINE = False
_inline_clients = []


def configure(broker: MiniBroker, inline: bool = False) -> None:
    global _BROKER, _INLINE
    _BROKER = broker
    _INLINE = inline


def pump_all(max_events: int = 100) -> None:
    """Inline mode only: process queued broker events on the calling thread."""
    for client in list(_inline_clients):
        client._pump(max_events)


_REASON_NAMES = {
    0: "Success",
    4: "Disconnect with Will Message",
    7: "Connection lost",
    128: "Unspecified error",
    135: "Not authorized",
}


class ReasonCode:
    """Duck-type of paho.mqtt.reasoncodes.ReasonCodes: .value + readable str."""

    def __init__(self, value: int):
        self.value = value

    def __str__(self) -> str:
        return _REASON_NAMES.get(self.value, "Reason code %d" % self.value)

    def __repr__(self) -> str:
        return "ReasonCode(%d)" % self.value

    def __eq__(self, other):
        return self.value == getattr(other, "value", other)


class MQTTMessage:
    __slots__ = ("topic", "payload", "qos", "retain", "mid")

    def __init__(self, topic: str = "", payload: bytes = b"", qos: int = 0,
                 retain: bool = False, mid: int = 0):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain
        self.mid = mid


class MQTTMessageInfo:
    def __init__(self, mid: int):
        self.mid = mid
        self.rc = MQTT_ERR_SUCCESS

    def wait_for_publish(self, timeout: Optional[float] = None) -> None:
        return None

    def is_published(self) -> bool:
        return True


class Client:
    def __init__(self, client_id: str = "", clean_session: Optional[bool] = None,
                 userdata: Any = None, protocol: int = MQTTv311, transport: str = "tcp"):
        self._client_id = client_id or "auto-%x" % id(self)
        self._userdata = userdata
        self._protocol = protocol
        self._lwt = None
        self._reconnect_min = 1.0
        self._reconnect_max = 120.0
        self._mid_counter = itertools.count(1)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._connect_requested = False
        self._events: Optional["queue.Queue"] = None
        self._inline_backoff = self._reconnect_min
        self._inline_retry_at = 0.0

        self.on_connect = None
        self.on_subscribe = None
        self.on_disconnect = None
        self.on_message = None
        self.on_publish = None

    # -- configuration (stored; mostly irrelevant virtually) -----------------

    def username_pw_set(self, username: str, password: Optional[str] = None) -> None:
        self._username = username

    def reconnect_delay_set(self, min_delay: int = 1, max_delay: int = 120) -> None:
        self._reconnect_min = float(min_delay)
        self._reconnect_max = float(max_delay)

    def will_set(self, topic: str, payload=None, qos: int = 0, retain: bool = False) -> None:
        self._lwt = (topic, _to_bytes(payload), qos, retain)

    # -- connection lifecycle -------------------------------------------------

    def connect(self, host: str, port: int = 1883, keepalive: int = 60,
                bind_address: str = "", bind_port: int = 0,
                clean_start=True, properties=None) -> int:
        # Real paho establishes TCP here and processes CONNACK in the network
        # loop; we mirror that: fail fast if the broker refuses, otherwise
        # defer the handshake to loop_start()'s thread.
        if _BROKER is None:
            raise ConnectionRefusedError("virtual broker not configured")
        if getattr(_BROKER, "_refuse_connections", False):
            raise ConnectionRefusedError("virtual broker is refusing connections")
        self._connect_requested = True
        return MQTT_ERR_SUCCESS

    def loop_start(self) -> None:
        if not self._connect_requested:
            return
        if _INLINE:
            if self not in _inline_clients:
                _inline_clients.append(self)
                self._inline_register()
            return
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._network_loop,
                                        name="virtual-mqtt-network", daemon=True)
        self._thread.start()

    def loop_stop(self) -> None:
        if _INLINE and self in _inline_clients:
            _inline_clients.remove(self)
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._thread = None
        # The device's bye() never sends DISCONNECT; the socket dies with the
        # process and the broker fires the LWT. Mirror that here.
        if self._connected.is_set():
            self._connected.clear()
            _BROKER.abnormal_disconnect(self._client_id)

    def disconnect(self) -> int:  # unused by the panel; clean = no LWT
        self._connected.clear()
        _BROKER.clean_disconnect(self._client_id)
        return MQTT_ERR_SUCCESS

    def is_connected(self) -> bool:
        return self._connected.is_set()

    # -- pub/sub --------------------------------------------------------------

    def subscribe(self, topic: str, qos: int = 0, options=None, properties=None):
        if not self._connected.is_set():
            return (MQTT_ERR_NO_CONN, None)
        mid = next(self._mid_counter)
        _BROKER.subscribe(self._client_id, topic, qos, mid)
        return (MQTT_ERR_SUCCESS, mid)

    def publish(self, topic: str, payload=None, qos: int = 0, retain: bool = False,
                properties=None) -> MQTTMessageInfo:
        mid = next(self._mid_counter)
        _BROKER.publish("panel", topic, _to_bytes(payload), qos, retain)
        return MQTTMessageInfo(mid)

    # -- event dispatch (shared by the network thread and inline pump) --------

    def _dispatch_event(self, ev) -> bool:
        """Deliver one broker event via the v1 callbacks. Returns True if the
        event was a disconnect."""
        kind = ev[0]
        if kind == "connack":
            self._connected.set()
            flags = {"session present": 1 if ev[1] else 0}
            self._safe_call("on_connect", self.on_connect,
                            self, self._userdata, flags, ReasonCode(0), None)
        elif kind == "suback":
            self._safe_call("on_subscribe", self.on_subscribe,
                            self, self._userdata, ev[1], [ReasonCode(ev[2])], None)
        elif kind == "msg":
            msg = MQTTMessage(topic=ev[1], payload=ev[2], qos=ev[3], retain=ev[4])
            self._safe_call("on_message", self.on_message,
                            self, self._userdata, msg)
        elif kind == "disconnect":
            self._connected.clear()
            self._safe_call("on_disconnect", self.on_disconnect,
                            self, self._userdata, ev[1], None)
            return True
        return False

    # -- network thread (CPython) ---------------------------------------------

    def _network_loop(self) -> None:
        backoff = self._reconnect_min
        first = True
        while not self._stop.is_set():
            if not first:
                # Auto-reconnect with the configured backoff.
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, self._reconnect_max)
            first = False

            events = _BROKER.register_session(self._client_id, lwt=self._lwt)
            if events is None:
                continue  # broker refusing; retry after backoff
            self._events = events

            disconnected = False
            while not self._stop.is_set() and not disconnected:
                try:
                    ev = events.get(timeout=0.1)
                except queue.Empty:
                    continue
                if ev[0] == "connack":
                    backoff = self._reconnect_min
                disconnected = self._dispatch_event(ev)

    # -- inline pump (Pyodide: single-threaded) -------------------------------

    def _inline_register(self) -> None:
        self._events = _BROKER.register_session(self._client_id, lwt=self._lwt)
        if self._events is None:
            self._inline_retry_at = time.monotonic() + self._inline_backoff
            self._inline_backoff = min(self._inline_backoff * 2, self._reconnect_max)

    def _pump(self, max_events: int = 100) -> None:
        if self._events is None:
            if time.monotonic() >= getattr(self, "_inline_retry_at", 0):
                self._inline_register()
            if self._events is None:
                return
        for _ in range(max_events):
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                return
            if ev[0] == "connack":
                self._inline_backoff = self._reconnect_min
            if self._dispatch_event(ev):
                # Disconnected: schedule an inline reconnect with backoff.
                self._events = None
                self._inline_retry_at = time.monotonic() + self._inline_backoff
                self._inline_backoff = min(self._inline_backoff * 2,
                                           self._reconnect_max)
                return

    @staticmethod
    def _safe_call(name, callback, *args) -> None:
        # Real paho catches and logs callback exceptions instead of letting
        # them kill the network thread; mirror that.
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as e:
            print("virtual-paho: caught exception in %s: %r" % (name, e), flush=True)


def _to_bytes(payload) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return str(payload).encode("utf-8")
