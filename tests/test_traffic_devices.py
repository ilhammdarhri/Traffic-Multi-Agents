import socket
import threading
import time
import uuid

import pytest

from sim import config, topics
from sim.devices import Actuator, Sensor
from sim.message import Message
from sim.mqtt_client import MqttClient, topic_matches
from sim.traffic import AVENUE, RED, SIDE, IntersectionSim, validate_plan

NORMAL = config.ARRIVALS["normal"]


def make(seed=0, **kw):
    return IntersectionSim("carrefour1", NORMAL, seed=seed, **kw)


# --- plan validation ---------------------------------------------------------
def test_validate_plan():
    assert validate_plan({"avenue": 50, "side": 30})
    assert not validate_plan({"avenue": 50, "side": 40})     # sum != 80
    assert not validate_plan({"avenue": 75, "side": 5})      # below g_min
    assert not validate_plan({"avenue": 50})
    assert not validate_plan("garbage")


# --- signal timing -------------------------------------------------------------
def test_signal_timing_plan_50_30():
    sim = make(plan={"avenue": 50, "side": 30})
    seen = []
    for _ in range(config.CYCLE):
        seen.append(sim.current_signal())
        sim.step()
    assert seen[:50] == [AVENUE] * 50
    assert seen[50:55] == [RED] * 5
    assert seen[55:85] == [SIDE] * 30
    assert seen[85:90] == [RED] * 5


def test_offset_shifts_cycle():
    sim = make(plan={"avenue": 50, "side": 30}, offset=10)
    sim.run(10)                                  # t = 10 -> start of this intersection's cycle
    assert sim.local_time() == 0 and sim.current_signal() == AVENUE


def test_new_plan_waits_for_next_cycle():
    sim = make(plan={"avenue": 40, "side": 40})
    sim.run(20)
    assert sim.set_plan({"avenue": 60, "side": 20})
    assert sim.plan == {"avenue": 40, "side": 40}            # unchanged mid-cycle
    sim.run(config.CYCLE - 20)                               # reach t = 90
    assert sim.plan == {"avenue": 60, "side": 20}


def test_invalid_plan_rejected_by_sim():
    sim = make()
    assert sim.set_plan({"avenue": 70, "side": 30}) is False
    with pytest.raises(ValueError):
        make(plan={"avenue": 70, "side": 30})


# --- queue dynamics ------------------------------------------------------------
def test_vehicle_conservation():
    sim = make(seed=3)
    sim.run(3600)
    for p in sim.phases.values():
        assert p.arrived == p.departed + len(p)
        assert len(p.waits) == p.departed


def test_no_departures_during_red():
    sim = make(plan={"avenue": 50, "side": 30})
    for _ in range(config.CYCLE * 3):
        before = {n: p.departed for n, p in sim.phases.items()}
        signal = sim.current_signal()
        sim.step()
        for n, p in sim.phases.items():
            if signal != n:
                assert p.departed == before[n]


def test_discharge_rate_equals_saturation_flow():
    sim = IntersectionSim("c", {AVENUE: 0.0, SIDE: 0.0}, plan={"avenue": 50, "side": 30}, q0=100)
    sim.run(50)                                  # one full avenue green
    assert 24 <= sim.phases[AVENUE].departed <= 25   # s * g = 0.5 * 50
    assert sim.phases[SIDE].departed == 0


def test_queue_bounded_when_undersaturated():
    sim = make(seed=1, plan={"avenue": 50, "side": 30})
    worst = 0
    for _ in range(40 * config.CYCLE):
        sim.step()
        worst = max(worst, max(sim.queue_lengths().values()))
    assert worst < 60


def test_queue_grows_when_green_too_short():
    sim = make(seed=1, plan={"avenue": 10, "side": 70})      # avenue starved
    sim.run(10 * config.CYCLE)
    assert len(sim.phases[AVENUE]) > 100


def test_same_seed_same_result():
    a, b = make(seed=7), make(seed=7)
    a.run(600); b.run(600)
    assert a.queue_lengths() == b.queue_lengths()
    assert a.phases[AVENUE].waits == b.phases[AVENUE].waits


# --- devices with a fake MQTT client (no broker) -----------------------------
class FakeMqtt:
    def __init__(self):
        self.published, self.subs = [], []

    def publish(self, topic, message, kind):
        self.published.append((topic, message, kind))

    def subscribe(self, pattern, callback, kind="queue"):
        self.subs.append((pattern, callback))

    def deliver(self, topic, message):
        for pattern, cb in self.subs:
            if topic_matches(pattern, topic):
                cb(topic, message)


def test_sensor_publishes_queue_measure():
    sim, mq = make(), FakeMqtt()
    sensor = Sensor("carrefour1", AVENUE, lambda: len(sim.phases[AVENUE]), mq)
    msg = sensor.publish()
    topic, sent, kind = mq.published[0]
    assert topic == "traffic/carrefour1/approach/avenue/queue" and kind == "queue"
    assert sent.valeur == config.INITIAL_QUEUE and sent.unite == "vehicules"
    assert sent.source == "loop-carrefour1-avenue" and msg is sent


def test_actuator_applies_valid_plan_and_rejects_invalid():
    sim, mq = make(), FakeMqtt()
    act = Actuator("carrefour1", sim, mq)
    mq.deliver(topics.signal_plan("carrefour1"), Message("ia-c1", {"avenue": 60, "side": 20}, "s"))
    mq.deliver(topics.signal_plan("carrefour1"), Message("ia-c1", {"avenue": 90, "side": 90}, "s"))
    assert act.rejected == 1
    sim.run(config.CYCLE)
    assert sim.plan == {"avenue": 60, "side": 20}


def test_actuator_reports_display_changes_only():
    sim, mq = make(plan={"avenue": 50, "side": 30}), FakeMqtt()
    act = Actuator("carrefour1", sim, mq)
    for _ in range(config.CYCLE):
        act.tick()
        sim.step()
    states = [m.valeur for _, m, kind in mq.published if kind == "etat"]
    assert states == [AVENUE, RED, SIDE, RED]


# --- full loop through a real broker -------------------------------------------
def broker_up():
    try:
        socket.create_connection(("localhost", 1883), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not broker_up(), reason="no MQTT broker on localhost:1883")
def test_plan_to_actuator_to_etat_via_broker():
    cx = "cx" + uuid.uuid4().hex[:5]
    sim = IntersectionSim(cx, NORMAL)
    mq_act, mq_ia, mq_watch = (MqttClient(f"{n}-{cx}") for n in ("act", "ia", "watch"))
    for c in (mq_act, mq_ia, mq_watch):
        c.connect()
    act = Actuator(cx, sim, mq_act)
    got, ev = [], threading.Event()
    mq_watch.subscribe(topics.signal_etat(cx), lambda t, m: (got.append(m.valeur), ev.set()), kind="etat")
    time.sleep(0.5)
    # IA -> broker -> actuator: the plan arrives and is queued for the next cycle
    mq_ia.publish(topics.signal_plan(cx), Message("ia", {"avenue": 55, "side": 25}, "s"), "plan")
    time.sleep(0.5)
    assert sim._pending == {"avenue": 55, "side": 25}
    # actuator -> broker -> watcher: the displayed phase is reported
    act.tick()
    assert ev.wait(3) and got[-1] == AVENUE
    for c in (mq_act, mq_ia, mq_watch):
        c.disconnect()
