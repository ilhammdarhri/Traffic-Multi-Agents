import pytest

from agents.vehicles import BusAgent, EmergencyVehicleAgent
from agents.intersection import IntersectionAgent
from kb.knowledge_base import KnowledgeBase
from kb.ontology import build_ontology
from sim import config, topics
from sim.corridor import Corridor
from sim.devices import Actuator
from sim.loopback import LoopbackBroker
from sim.message import Message
from sim.traffic import AVENUE, RED, SIDE, IntersectionSim
from tests.test_traffic_devices import FakeMqtt

NORMAL = config.ARRIVALS["normal"]
ROUTE = [("carrefour1", AVENUE), ("carrefour2", AVENUE), ("carrefour3", AVENUE)]


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    return KnowledgeBase(build_ontology(tmp_path_factory.mktemp("kb") / "traffic.owl"))


def sim_at(t, plan=None, **kw):
    sim = IntersectionSim("c", NORMAL, plan=plan or {"avenue": 50, "side": 30}, **kw)
    sim.run(t)
    return sim


def signals(sim, seconds):
    out = []
    for _ in range(seconds):
        out.append(sim.current_signal())
        sim.step()
    return out


# --- IntersectionSim.preempt ---------------------------------------------------
def test_preempt_from_other_phase_inserts_all_red_clearance():
    sim = sim_at(60)                                      # side is green at t = 60 (55..84)
    assert sim.current_signal() == SIDE
    assert sim.preempt(AVENUE, duration=12, delay=0)
    seen = signals(sim, 22)
    assert seen[:5] == [RED] * 5                          # clearance, never SIDE -> AVENUE directly
    assert seen[5:12] == [AVENUE] * 7
    assert seen[12:17] == [RED] * 5                       # clearance after the window
    assert SIDE not in seen[:12]


def test_preempt_when_phase_already_green_keeps_green():
    sim = sim_at(10)                                      # avenue green until t = 50
    sim.preempt(AVENUE, duration=60)                      # longer than the remaining green
    seen = signals(sim, 60)
    assert seen == [AVENUE] * 60


def test_preempt_with_delay_starts_later():
    sim = sim_at(60)
    sim.preempt(AVENUE, duration=10, delay=10)
    seen = signals(sim, 25)
    assert seen[:10] == [SIDE] * 10                       # normal cycle until the window starts
    assert seen[10:15] == [RED] * 5
    assert seen[15:20] == [AVENUE] * 5


def test_preempt_then_normal_cycle_resumes():
    sim = sim_at(60)
    sim.preempt(AVENUE, duration=12)
    sim.run(40)
    assert sim._override is None
    assert sim.current_signal() in (AVENUE, SIDE, RED)
    assert sim.local_time() == (sim.t - sim.offset) % config.CYCLE


def test_invalid_preempt_rejected():
    sim = sim_at(0)
    assert not sim.preempt("diagonal", 10)
    assert not sim.preempt(AVENUE, 0)
    assert not sim.preempt(AVENUE, 10, delay=-1)


def test_preempt_never_shows_two_phases_back_to_back():
    sim = sim_at(0)
    for t0 in (7, 33, 61, 80):
        sim = sim_at(t0)
        sim.preempt(AVENUE if t0 % 2 else SIDE, duration=12, delay=3)
        seen = signals(sim, 60)
        for a, b in zip(seen, seen[1:]):
            assert {a, b} != {AVENUE, SIDE}               # always an all-red between greens


# --- Actuator ------------------------------------------------------------------
def test_actuator_applies_and_rejects_preempt_commands():
    sim, mq = sim_at(0), FakeMqtt()
    act = Actuator("c", sim, mq)
    topic = topics.signal_preempt("c")
    mq.deliver(topic, Message("ia", {"phase": "side", "duration_s": 10, "delay_s": 0}, "s"))
    mq.deliver(topic, Message("ia", {"phase": "side", "duration_s": "ten"}, "s"))
    mq.deliver(topic, Message("ia", "garbage", "s"))
    assert act.preemptions == 1 and act.rejected == 2


# --- IntersectionAgent: knowledge-base rules --------------------------------------
def test_emergency_request_triggers_preempt_command(kb):
    mq = FakeMqtt()
    ia = IntersectionAgent("carrefour1", mq, kb=kb)
    ia.now = 100
    req = {"carrefour": "carrefour1", "phase": "avenue", "kind": "emergency", "eta_s": 30}
    mq.deliver(topics.PRIORITY_REQUEST, Message("ev1", req, "request"))
    topic, msg, kind = mq.published[-1]
    assert topic == "traffic/carrefour1/signal/preempt" and kind == "preempt"
    assert msg.valeur == {"phase": "avenue", "delay_s": 23, "duration_s": 13}   # 30 - 7 ; 7 + 6


def test_request_for_another_carrefour_is_ignored(kb):
    mq = FakeMqtt()
    IntersectionAgent("carrefour1", mq, kb=kb)
    req = {"carrefour": "carrefour2", "phase": "avenue", "kind": "emergency", "eta_s": 30}
    mq.deliver(topics.PRIORITY_REQUEST, Message("ev1", req, "request"))
    assert mq.published == []


def test_no_kb_means_no_priority_handling():
    mq = FakeMqtt()
    IntersectionAgent("carrefour1", mq)
    req = {"carrefour": "carrefour1", "phase": "avenue", "kind": "emergency", "eta_s": 30}
    mq.deliver(topics.PRIORITY_REQUEST, Message("ev1", req, "request"))
    assert mq.published == []


def test_bus_request_boosts_weight_for_one_decision(kb):
    mq = FakeMqtt()
    ia = IntersectionAgent("carrefour1", mq, kb=kb, arrival_rates=config.ARRIVALS["peak"])
    req = {"carrefour": "carrefour1", "phase": "side", "kind": "bus", "eta_s": 60}
    mq.deliver(topics.PRIORITY_REQUEST, Message("bus1", req, "request"))
    ia.queues = {AVENUE: 5, SIDE: 5}
    with_bus = ia.decide_cycle()
    assert ia.state["functions"][SIDE].weight == config.WEIGHTS["bus"]
    without = ia.decide_cycle()                           # boost expired
    assert ia.state["functions"][SIDE].weight == config.WEIGHTS["default"]
    assert with_bus[1] >= without[1]


def test_event_forecast_raises_arrival_rate(kb):
    ia = IntersectionAgent("carrefour2", FakeMqtt(), kb=kb)
    ia.now = 2000                                          # school exit on carrefour2 side
    assert ia.forecast(SIDE) == pytest.approx(NORMAL["side"] * 2.0)
    assert ia.forecast(AVENUE) == pytest.approx(NORMAL["avenue"])
    ia.now = 100
    assert ia.forecast(SIDE) == pytest.approx(NORMAL["side"])


# --- vehicle agents -------------------------------------------------------------
def test_vehicle_requests_once_then_passes_on_green():
    mq = FakeMqtt()
    ev = EmergencyVehicleAgent("ev1", [("c", AVENUE)], mq, first_eta=45)
    for t in range(60):
        ev.step({"t": t, "signals": {"c": AVENUE}})       # always green
    requests = [m for _, m, k in mq.published if k == "priority"]
    assert len(requests) == 1 and requests[0].valeur["kind"] == "emergency"
    assert requests[0].valeur["eta_s"] == EmergencyVehicleAgent.HORIZON
    assert ev.done and ev.total_delay == 0 and ev.passed_at[0] == 44


def test_vehicle_waits_while_red():
    ev = EmergencyVehicleAgent("ev1", [("c", AVENUE)], FakeMqtt(), first_eta=5, priority=False)
    for t in range(5):
        ev.step({"t": t, "signals": {"c": RED}})
    for t in range(5, 12):
        ev.step({"t": t, "signals": {"c": RED}})
    for t in range(12, 15):
        ev.step({"t": t, "signals": {"c": AVENUE}})
    assert ev.done and ev.total_delay == 8                 # arrives at t = 4, passes at t = 12


def test_baseline_vehicle_never_requests():
    mq = FakeMqtt()
    ev = EmergencyVehicleAgent("ev1", ROUTE, mq, first_eta=30, priority=False)
    for t in range(200):
        ev.step({"t": t, "signals": {c: AVENUE for c, _ in ROUTE}})
    assert ev.done and mq.published == []


# --- corridor experiment (question 3) ---------------------------------------------
def run_ev(kb, start, priority, seed=1, extra=250):
    cor = Corridor(rates=NORMAL, seed=seed, kb=kb)
    ev = EmergencyVehicleAgent("ev1", ROUTE, cor.broker.client("ev1"), first_eta=40, priority=priority)
    cor.add_vehicle(ev, start_t=start)
    cor.run(start + extra)
    return ev, cor


def test_priority_reduces_emergency_delay_and_costs_others_little(kb):
    starts = range(900, 990, 7)
    delay_off, delay_on, wait_off, wait_on = [], [], [], []
    for s in starts:
        ev0, cor0 = run_ev(kb, s, priority=False)
        ev1, cor1 = run_ev(kb, s, priority=True)
        assert ev0.done and ev1.done
        delay_off.append(ev0.total_delay); delay_on.append(ev1.total_delay)
        wait_off.append(cor0.mean_wait()); wait_on.append(cor1.mean_wait())
    mean = lambda xs: sum(xs) / len(xs)
    assert mean(delay_off) > 5                              # without priority it does wait
    assert mean(delay_on) < 0.25 * mean(delay_off)          # with priority it (almost) never waits
    assert mean(wait_on) < 1.15 * mean(wait_off)            # others lose less than 15 %


def test_preemption_is_sent_through_the_broker(kb):
    ev, cor = run_ev(kb, 900, priority=True)
    topics_seen = [t for t, k in cor.broker.log if k == "preempt"]
    assert len(topics_seen) == 3                            # one command per intersection
    assert sum(a.preemptions for a in cor.actuators.values()) == 3
