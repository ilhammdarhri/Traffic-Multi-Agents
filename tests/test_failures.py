"""Step 13: failures. Last Will semantics, consensus with a dead neighbour, fail-safe fallbacks."""
import threading
import time
import uuid

import pytest

from agents.intersection import IntersectionAgent
from coordination.consensus import OffsetConsensus
from coordination.strategies import ConsensusStrategy
from sim import config, topics
from sim.devices import Actuator
from sim.loopback import LoopbackBroker
from sim.message import Message
from sim.mqtt_client import MqttClient
from sim.scenarios import make_corridor
from sim.traffic import AVENUE, SIDE, IntersectionSim
from tests.test_mqtt_client import needs_broker
from tests.test_traffic_devices import FakeMqtt

NORMAL = config.ARRIVALS["normal"]


def status_of(broker, agent_id):
    return Message.from_json(broker.retained[topics.agent_status(agent_id)]).valeur


# --- loopback Last Will ------------------------------------------------------------
def test_loopback_online_offline_and_crash():
    b = LoopbackBroker()
    a, c = b.client("a"), b.client("c")
    assert status_of(b, "a") == topics.STATUS_ONLINE
    a.disconnect()
    assert status_of(b, "a") == topics.STATUS_OFFLINE
    c.crash()
    assert status_of(b, "c") == topics.STATUS_OFFLINE
    a.connect()
    assert status_of(b, "a") == topics.STATUS_ONLINE


def test_dead_client_neither_sends_nor_receives_and_replays_on_reconnect():
    b = LoopbackBroker()
    pub, sub = b.client("pub"), b.client("sub")
    got = []
    sub.subscribe("x/+", lambda t, m: got.append(m.valeur), kind="plan")
    sub.crash()
    pub.publish("x/1", Message("pub", 1, "u"), "plan")      # retained, missed
    assert got == []
    sub.crash()
    sub.publish("x/2", Message("sub", 2, "u"), "plan")
    assert "x/2" not in b.retained                           # dropped
    sub.connect()
    assert got == [1]                                        # retained replayed


# --- consensus node ------------------------------------------------------------------
def test_unheard_offline_neighbour_does_not_block():
    n = OffsetConsensus(1, {"a": 0, "b": 2})
    n.receive("a", 0)
    assert not n.ready()
    n.mark_offline("b")
    assert n.ready()


def test_heard_offline_neighbour_stays_anchor_and_can_return():
    n = OffsetConsensus(1, {"a": 0})
    n.receive("a", 0)
    n.mark_offline("a")
    assert n.update(40) != 0                                 # still pulled towards the anchor
    n.mark_online("a")
    assert "a" not in n.offline


def test_no_value_no_convergence():
    n = OffsetConsensus(0, {"a": 1})
    n.mark_offline("a")
    for _ in range(5):
        assert n.update(0) == 0
    assert not n.converged


# --- strategy status handling ------------------------------------------------------------
def test_strategy_marks_neighbour_from_status():
    mq = FakeMqtt()
    ia = IntersectionAgent("carrefour2", mq, strategy=ConsensusStrategy(),
                           position=1, neighbors={"carrefour1": 0, "carrefour3": 2})
    node = ia.strategy.node
    off = Message("x", topics.STATUS_OFFLINE, "status")
    mq.deliver(topics.agent_status("ia-carrefour1"), off)
    mq.deliver(topics.agent_status("ia-other"), off)         # not a neighbour: ignored
    mq.deliver(topics.agent_status("ia-carrefour3"), Message("x", "garbage", "status"))
    assert node.offline == {"carrefour1"}
    mq.deliver(topics.agent_status("ia-carrefour1"), Message("x", topics.STATUS_ONLINE, "status"))
    assert node.offline == set()


# --- actuator watchdog -------------------------------------------------------------------
def test_actuator_watchdog_falls_back_and_recovers():
    sim = IntersectionSim("c", NORMAL, seed=0, plan={"avenue": 60, "side": 20})
    mq = FakeMqtt()
    act = Actuator("c", sim, mq, fallback_plan=config.FALLBACK_PLAN, plan_timeout=100)
    for _ in range(99):
        sim.step(); act.tick()
    assert not act.fallback_active
    sim.step(); act.tick()
    assert act.fallback_active and act.fallbacks == 1
    mq.deliver(topics.signal_plan("c"), Message("a", {"avenue": 40, "side": 40}, "s"))
    assert not act.fallback_active


def test_actuator_without_fallback_never_switches():
    sim = IntersectionSim("c", NORMAL, seed=0)
    act = Actuator("c", sim, FakeMqtt())
    for _ in range(1000):
        sim.step(); act.tick()
    assert not act.fallback_active


# --- stale sensor ------------------------------------------------------------------------------
def test_stale_sensor_triggers_fixed_plan_then_recovers():
    mq = FakeMqtt()
    ia = IntersectionAgent("c", mq, strategy="nash")
    q = topics.queue("c", "+")
    deliver = lambda d, v: mq.deliver(topics.queue("c", d), Message("s", v, "vehicules"))
    deliver(AVENUE, 20); deliver(SIDE, 5)
    ia.decide_cycle(0)
    assert not ia.degraded
    for _ in range(config.STALE_CYCLES):                     # sensors silent
        ia.decide_cycle(0)
    assert ia.degraded and ia.fallbacks >= 1
    topic, msg, kind = mq.published[-1]
    assert kind == "plan" and msg.valeur == config.FALLBACK_PLAN
    deliver(AVENUE, 20); deliver(SIDE, 5)
    ia.decide_cycle(0)
    assert not ia.degraded


def test_injected_queues_are_never_stale():
    ia = IntersectionAgent("c", FakeMqtt(), strategy="nash")
    ia.queues = {AVENUE: 10, SIDE: 10}
    for _ in range(5):
        ia.decide_cycle(0)
    assert not ia.degraded and ia.fallbacks == 0


# --- corridor scenarios --------------------------------------------------------------------------
def run(crash=None, recover=None, T=2700, seed=1):
    c = make_corridor("consensus", None, seed)
    for t in range(T):
        if crash and t == crash[0]:
            c.crash_agent(crash[1])
        if recover and t == recover[0]:
            c.recover_agent(recover[1])
        c.step()
    return c


@pytest.mark.parametrize("victim", ["carrefour2", "carrefour3"])
def test_corridor_survives_agent_crash(victim):
    c = run(crash=(300, victim))
    assert c.offset_spread() <= 3
    assert c.actuators[victim].fallbacks == 1
    others = [k for k in c.carrefours if k != victim]
    assert all(c.actuators[k].fallbacks == 0 for k in others)
    assert any(victim in c.agents[k].strategy.node.offline for k in others)


def test_corridor_crash_then_recover_reconverges():
    c = run(crash=(300, "carrefour2"), recover=(900, "carrefour2"))
    assert c.offset_spread() <= 3
    assert all(not a.strategy.node.offline for a in c.agents.values())


def test_sensor_crash_makes_agent_fall_back():
    c = make_corridor("consensus", None, 1)
    for t in range(1500):
        if t == 300:
            c.crash_sensor("carrefour1", AVENUE)
        c.step()
    assert c.agents["carrefour1"].fallbacks >= 1
    assert c.agents["carrefour2"].fallbacks == 0


# --- real broker ------------------------------------------------------------------------------------
@needs_broker
def test_real_broker_neighbour_sees_crash():
    sfx = uuid.uuid4().hex[:6]
    c1, c2 = f"carrefourA{sfx}", f"carrefourB{sfx}"
    m1, m2 = MqttClient(f"ia-{c1}", keepalive=2), MqttClient(f"ia-{c2}", keepalive=2)
    m1.connect(); m2.connect()
    a1 = IntersectionAgent(c1, m1, strategy=ConsensusStrategy(), position=0, neighbors={c2: 1})
    a2 = IntersectionAgent(c2, m2, strategy=ConsensusStrategy(), position=1, neighbors={c1: 0})
    time.sleep(1)
    assert not a2.strategy.node.offline
    m1.crash()
    deadline = time.time() + 10
    while time.time() < deadline and c1 not in a2.strategy.node.offline:
        time.sleep(0.2)
    assert c1 in a2.strategy.node.offline
    m2.disconnect()
