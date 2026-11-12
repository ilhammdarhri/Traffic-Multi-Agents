"""Tests for MqttClient. Unit tests run anywhere; integration tests need a
broker on localhost:1883 (Mosquitto) and are skipped otherwise."""
import socket
import threading
import time
import uuid

import pytest

from sim import topics
from sim.message import Message
from sim.mqtt_client import MqttClient, topic_matches


def broker_up():
    try:
        socket.create_connection(("localhost", 1883), timeout=1).close()
        return True
    except OSError:
        return False


needs_broker = pytest.mark.skipif(not broker_up(), reason="no MQTT broker on localhost:1883")


# --- unit tests (no broker) -----------------------------------------------
@pytest.mark.parametrize("pattern,topic,expected", [
    ("traffic/+/approach/+/queue", "traffic/carrefour3/approach/nord/queue", True),
    ("traffic/+/approach/+/queue", "traffic/carrefour3/signal/plan", False),
    ("traffic/carrefour3/#", "traffic/carrefour3/approach/nord/queue", True),
    ("traffic/carrefour3/#", "traffic/carrefour2/signal/plan", False),
    ("traffic/priority/request", "traffic/priority/request", True),
    ("traffic/priority/request", "traffic/priority/request/x", False),
    ("sma/agent/+/statut", "sma/agent/ia-c1/statut", True),
])
def test_topic_matches(pattern, topic, expected):
    assert topic_matches(pattern, topic) is expected


# --- integration tests (real broker) ---------------------------------------
def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


@needs_broker
def test_publish_subscribe_roundtrip():
    got = []
    ev = threading.Event()
    sub, pub = MqttClient(uid("sub")), MqttClient(uid("pub"))
    sub.connect(); pub.connect()
    sub.subscribe(topics.ALL_QUEUES, lambda t, m: (got.append((t, m)), ev.set()))
    time.sleep(0.5)
    pub.publish(topics.queue("c3", "nord"), Message(source="loop-c3-n", valeur=14, unite="vehicules"), "queue")
    assert ev.wait(3)
    assert got[0][0] == "traffic/c3/approach/nord/queue" and got[0][1].valeur == 14
    sub.disconnect(); pub.disconnect()


@needs_broker
def test_retained_plan_reaches_late_subscriber():
    c = uid("cx")
    pub = MqttClient(uid("pub")); pub.connect()
    pub.publish(topics.signal_plan(c), Message(source="ia", valeur={"avenue": 50, "side": 30}, unite="s"), "plan")
    time.sleep(0.5)
    got, ev = [], threading.Event()
    late = MqttClient(uid("late")); late.connect()
    late.subscribe(topics.signal_plan(c), lambda t, m: (got.append(m), ev.set()), kind="plan")
    assert ev.wait(3)
    assert got[0].valeur == {"avenue": 50, "side": 30}
    pub.disconnect(); late.disconnect()


@needs_broker
def test_last_will_published_on_crash():
    victim_id = uid("ia")
    states, ev = [], threading.Event()
    watcher = MqttClient(uid("watch")); watcher.connect()

    def on_status(t, m):
        states.append(m.valeur)
        if m.valeur == topics.STATUS_OFFLINE:
            ev.set()

    watcher.subscribe(f"sma/agent/{victim_id}/statut", on_status, kind="status")
    victim = MqttClient(victim_id, keepalive=2); victim.connect()
    time.sleep(0.5)
    victim.crash()
    assert ev.wait(8), f"no LWT received, saw {states}"
    assert states[0] == topics.STATUS_ONLINE and states[-1] == topics.STATUS_OFFLINE
    watcher.disconnect()
