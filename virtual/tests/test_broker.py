"""MiniBroker semantics: the MQTT behaviors the panel's hardening relies on."""
import queue

import pytest

from virtual.shims.broker import MiniBroker, topic_matches


# -- wildcard matching -------------------------------------------------------

@pytest.mark.parametrize("filt,topic,expected", [
    ("#", "a/b/c", True),
    ("a/#", "a", True),            # '#' matches the parent level itself
    ("a/#", "a/b/c", True),
    ("a/#", "b", False),
    ("a/+/c", "a/b/c", True),
    ("a/+/c", "a/b/d", False),
    ("a/+", "a/b", True),
    ("a/+", "a/b/c", False),
    ("home/alert/#", "home/alert/test/info", True),
    ("lcars/alert-panel/#", "lcars/alert-panel/mode-select", True),
    ("lcars/alert-panel/#", "lcars/other/mode-select", False),
    ("a/b", "a/b", True),
    ("a/b", "a", False),
])
def test_topic_matches(filt, topic, expected):
    assert topic_matches(filt, topic) is expected


# -- helpers -----------------------------------------------------------------

def drain(q):
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            return events


def connect_and_subscribe(broker, cid="c1", lwt=None, filters=("t/#",)):
    q = broker.register_session(cid, lwt=lwt)
    for i, f in enumerate(filters, start=1):
        broker.subscribe(cid, f, 1, i)
    return q


# -- retained / delivery flags ----------------------------------------------

def test_live_delivery_has_retain_false_even_for_retained_publish():
    broker = MiniBroker()
    q = connect_and_subscribe(broker)
    drain(q)
    broker.inject("t/x", "hello", retain=True)
    events = drain(q)
    assert ("msg", "t/x", b"hello", 0, False) in events  # live => retain flag 0


def test_retained_delivery_on_subscribe_has_retain_true():
    broker = MiniBroker()
    broker.inject("t/x", "hello", retain=True)
    q = connect_and_subscribe(broker)
    events = drain(q)
    kinds = [e[0] for e in events]
    assert kinds == ["connack", "suback", "msg"]  # SUBACK before retained
    msg = events[-1]
    assert msg[1] == "t/x" and msg[2] == b"hello" and msg[4] is True


def test_empty_retained_payload_deletes():
    broker = MiniBroker()
    broker.inject("t/x", "hello", retain=True)
    broker.inject("t/x", "", retain=True)
    assert broker.retained_snapshot() == {}


# -- LWT ---------------------------------------------------------------------

def test_lwt_fires_on_drop_not_on_clean_disconnect():
    broker = MiniBroker()
    watcher = connect_and_subscribe(broker, "watcher", filters=("status/#",))
    drain(watcher)

    broker.register_session("panel", lwt=("status/avail", b"offline", 1, True))
    broker.drop_client("panel")
    events = drain(watcher)
    assert any(e[0] == "msg" and e[1] == "status/avail" and e[2] == b"offline"
               for e in events)
    assert broker.retained_snapshot().get("status/avail") == "offline"

    broker.register_session("panel2", lwt=("status/avail2", b"offline", 1, True))
    broker.clean_disconnect("panel2")
    assert "status/avail2" not in broker.retained_snapshot()


def test_broker_restart_wipes_sessions_keeps_retained_no_lwt():
    broker = MiniBroker()
    broker.inject("keep/me", "kept", retain=True)
    q = broker.register_session("panel", lwt=("status/avail", b"offline", 1, True))
    drain(q)
    broker.restart_broker()
    events = drain(q)
    assert ("disconnect", 7) in events
    # No LWT was fired (broker died before it could act)...
    assert "status/avail" not in broker.retained_snapshot()
    # ...but retained store persisted, like mosquitto's persistence file.
    assert broker.retained_snapshot().get("keep/me") == "kept"
    # Session is gone: "Restored 0 clients".
    assert not broker.is_connected("panel")


def test_one_delivery_per_session_with_overlapping_filters():
    broker = MiniBroker()
    q = connect_and_subscribe(broker, filters=("t/#", "t/+"))
    drain(q)
    broker.inject("t/x", "once")
    msgs = [e for e in drain(q) if e[0] == "msg"]
    assert len(msgs) == 1
