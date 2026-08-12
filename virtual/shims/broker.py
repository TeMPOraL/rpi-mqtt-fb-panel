"""In-process MQTT mini-broker backing the fake paho client.

Transport-neutral (no paho imports): sessions receive plain event tuples on
per-session queues; the fake client's network thread turns them into paho v1
callbacks. The broker never invokes callbacks itself and never blocks a
caller — all methods only mutate state under one lock and enqueue.

Semantics deliberately mirrored from real brokers (encoded as unit tests):
- Live fan-out delivers retain=0 even for retained publishes; retained-store
  delivery on subscribe uses retain=1 [MQTT-3.3.1-9]. This is what makes the
  panel's "ignore RETAINED restart command" guard behave like with Mosquitto.
- Publishing an empty payload with retain=True deletes the retained message.
- LWT fires on abnormal disconnect (drop, loop_stop) but NOT on broker
  restart (the broker died before it could act) and not on clean disconnect.
"""
import itertools
import queue
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

# Event tuples placed on session queues:
#   ("connack", session_present: bool)
#   ("suback", mid: int, granted_qos: int)
#   ("msg", topic: str, payload: bytes, qos: int, retain: bool)
#   ("disconnect", rc: int)

RC_CONNECTION_LOST = 7  # paho MQTT_ERR_CONN_LOST


def topic_matches(topic_filter: str, topic: str) -> bool:
    """MQTT topic filter matching supporting '+' and trailing '#'."""
    if topic_filter == "#":
        return True
    f_parts = topic_filter.split("/")
    t_parts = topic.split("/")
    for i, f in enumerate(f_parts):
        if f == "#":
            return True  # matches remaining levels, including zero
        if i >= len(t_parts):
            return False
        if f != "+" and f != t_parts[i]:
            return False
    return len(f_parts) == len(t_parts)


class _Session:
    def __init__(self, client_id: str, lwt: Optional[Tuple[str, bytes, int, bool]]):
        self.client_id = client_id
        self.lwt = lwt
        self.subscriptions: List[Tuple[str, int]] = []
        self.events: "queue.Queue" = queue.Queue()


class MiniBroker:
    def __init__(self, traffic_log_size: int = 1000):
        self._lock = threading.RLock()
        self._sessions: Dict[str, _Session] = {}
        self._retained: Dict[str, Tuple[bytes, int]] = {}
        self._traffic: deque = deque(maxlen=traffic_log_size)
        self._traffic_counter = itertools.count(1)
        self._refuse_connections = False

    # -- session lifecycle --------------------------------------------------

    def register_session(self, client_id: str,
                         lwt: Optional[Tuple[str, bytes, int, bool]] = None) -> Optional["queue.Queue"]:
        """Connect a client (clean start). Returns its event queue, or None if
        the broker is refusing connections. Enqueues the CONNACK event."""
        with self._lock:
            if self._refuse_connections:
                return None
            session = _Session(client_id, lwt)
            self._sessions[client_id] = session
            session.events.put(("connack", False))  # clean start: no session present
            return session.events

    def subscribe(self, client_id: str, topic_filter: str, qos: int, mid: int) -> bool:
        """Add a subscription; enqueue SUBACK then any retained matches."""
        with self._lock:
            session = self._sessions.get(client_id)
            if session is None:
                return False
            session.subscriptions.append((topic_filter, qos))
            session.events.put(("suback", mid, qos))
            for topic, (payload, r_qos) in self._retained.items():
                if topic_matches(topic_filter, topic):
                    session.events.put(("msg", topic, payload, min(qos, r_qos), True))
            return True

    def clean_disconnect(self, client_id: str) -> None:
        with self._lock:
            self._sessions.pop(client_id, None)

    def abnormal_disconnect(self, client_id: str) -> None:
        """Connection died without DISCONNECT: publish the LWT, drop session."""
        with self._lock:
            session = self._sessions.pop(client_id, None)
            if session and session.lwt:
                topic, payload, qos, retain = session.lwt
                self._route("lwt", topic, payload, qos, retain)

    # -- publishing ---------------------------------------------------------

    def publish(self, origin: str, topic: str, payload: bytes, qos: int = 0,
                retain: bool = False) -> None:
        with self._lock:
            self._route(origin, topic, payload, qos, retain)

    def inject(self, topic: str, payload, qos: int = 0, retain: bool = False) -> None:
        """Synthetic control: publish as if from an external client."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        elif payload is None:
            payload = b""
        self.publish("inject", topic, payload, qos, retain)

    def _route(self, origin: str, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        # Caller holds the lock.
        if retain:
            if payload == b"":
                self._retained.pop(topic, None)
            else:
                self._retained[topic] = (payload, qos)
        self._traffic.append({
            "n": next(self._traffic_counter),
            "ts": time.time(),
            "origin": origin,
            "topic": topic,
            "payload": payload.decode("utf-8", errors="replace")[:500],
            "qos": qos,
            "retain": retain,
        })
        for session in self._sessions.values():
            for topic_filter, sub_qos in session.subscriptions:
                if topic_matches(topic_filter, topic):
                    # Live fan-out: retain flag is always False [MQTT-3.3.1-9].
                    session.events.put(("msg", topic, payload, min(qos, sub_qos), False))
                    break  # one delivery per session even if several filters match

    # -- chaos / synthetic controls ------------------------------------------

    def drop_client(self, client_id: Optional[str] = None) -> None:
        """Simulate TCP loss client-side: LWT fires, DISCONNECT delivered,
        session gone. The client's auto-reconnect will bring it back."""
        with self._lock:
            ids = [client_id] if client_id else list(self._sessions)
            for cid in ids:
                session = self._sessions.pop(cid, None)
                if session is None:
                    continue
                if session.lwt:
                    topic, payload, qos, retain = session.lwt
                    self._route("lwt", topic, payload, qos, retain)
                session.events.put(("disconnect", RC_CONNECTION_LOST))

    def restart_broker(self) -> None:
        """Simulate the production incident: broker restarts, sessions and
        subscriptions wiped ("Restored 0 clients"), retained store persisted,
        NO LWT delivery (the broker died before it could act)."""
        with self._lock:
            for session in self._sessions.values():
                session.events.put(("disconnect", RC_CONNECTION_LOST))
            self._sessions.clear()

    def set_refuse_connections(self, refuse: bool) -> None:
        with self._lock:
            self._refuse_connections = refuse

    # -- introspection -------------------------------------------------------

    def retained_snapshot(self) -> Dict[str, str]:
        with self._lock:
            return {t: p.decode("utf-8", errors="replace")
                    for t, (p, _q) in self._retained.items()}

    def traffic_log(self, since: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            return [e for e in self._traffic if e["n"] > since][-limit:]

    def panel_publishes(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [e for e in self._traffic if e["origin"] in ("panel", "lwt")][-limit:]

    def is_connected(self, client_id: str) -> bool:
        with self._lock:
            return client_id in self._sessions

    def subscription_count(self, client_id: str) -> int:
        """Active subscription filters for a client; 0 after a broker restart
        until the client resubscribes. This is the truthful "actually
        subscribed" signal — retained availability alone can lie right after
        a restart (the pre-restart retained 'online' persists)."""
        with self._lock:
            session = self._sessions.get(client_id)
            return len(session.subscriptions) if session else 0
