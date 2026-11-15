import pytest

from sim import config, topics
from sim.corridor import Corridor
from sim.devices import Actuator
from sim.message import Message
from sim.scenarios import ideal_offsets
from sim.traffic import AVENUE, RED, SIDE, IntersectionSim
from tests.test_traffic_devices import FakeMqtt

NORMAL = config.ARRIVALS["normal"]
PLAN = {"avenue": 50, "side": 30}


def make(offset=0, plan=PLAN, **kw):
    return IntersectionSim("c", NORMAL, offset=offset, plan=plan, **kw)


def signals(sim, seconds):
    out = []
    for _ in range(seconds):
        out.append(sim.current_signal())
        sim.step()
    return out


# --- cycle bookkeeping ----------------------------------------------------------------
def test_offset_and_cycle_remaining():
    sim = make(offset=30)
    assert sim.offset == 30 and sim.local_time() == 60 and sim.cycle_remaining() == 30
    sim.run(30)                                              # a new cycle starts at t = 30
    assert sim.local_time() == 0 and sim.cycle_remaining() == 90


# --- shift of the next cycle ------------------------------------------------------------
def test_positive_shift_stretches_one_cycle_then_moves_the_offset():
    sim = make()
    sim.run(10)
    assert sim.shift_next_cycle(7)
    assert sim.cycle_len == 90                               # nothing changes mid-cycle
    sim.run(80)                                              # t = 90: the shifted cycle starts
    assert sim.cycle_len == 97 and sim.cycle_plan == {"avenue": 57, "side": 30}
    assert sim.offset == 0                                   # the offset moves when it ends
    sim.run(97)                                              # t = 187
    assert sim.cycle_len == 90 and sim.offset == 7           # 187 mod 90
    assert sim.plan == PLAN                                  # the plan itself is untouched


def test_negative_shift_shortens_the_avenue_green():
    sim = make()
    sim.shift_next_cycle(-6)
    sim.run(90)
    assert sim.cycle_len == 84 and sim.cycle_plan[AVENUE] == 44
    sim.run(84)
    assert sim.offset == (90 + 84) % 90 == 84


def test_negative_shift_never_goes_below_minimum_green():
    sim = make(plan={"avenue": 15, "side": 65})
    sim.shift_next_cycle(-10)
    sim.run(90)
    assert sim.cycle_plan[AVENUE] == config.G_MIN and sim.cycle_len == 85


def test_shifts_in_the_same_cycle_add_up_and_are_capped():
    sim = make()
    assert sim.shift_next_cycle(6) and sim.shift_next_cycle(8)
    sim.run(90)
    assert sim.cycle_len == 90 + config.MAX_SHIFT            # 14 capped to MAX_SHIFT


@pytest.mark.parametrize("bad", [1.5, "3", None, True, config.MAX_SHIFT + 1, -config.MAX_SHIFT - 1])
def test_invalid_shift_rejected(bad):
    sim = make()
    assert sim.shift_next_cycle(bad) is False
    sim.run(90)
    assert sim.cycle_len == 90


def test_shift_never_puts_two_phases_green_back_to_back():
    sim = make()
    seen = []
    for cycle in range(30):
        if cycle % 2 == 0:
            sim.shift_next_cycle(config.MAX_SHIFT if cycle % 4 == 0 else -config.MAX_SHIFT)
        seen += signals(sim, 90)
    for a, b in zip(seen, seen[1:]):
        assert {a, b} != {AVENUE, SIDE}
    assert RED in seen and AVENUE in seen and SIDE in seen


def test_plan_and_shift_apply_together_at_the_cycle_start():
    sim = make()
    sim.set_plan({"avenue": 60, "side": 20})
    sim.shift_next_cycle(5)
    sim.run(90)
    assert sim.plan == {"avenue": 60, "side": 20}
    assert sim.cycle_plan == {"avenue": 65, "side": 20} and sim.cycle_len == 95


# --- actuator and topics ----------------------------------------------------------------
def test_actuator_applies_and_rejects_shift_commands():
    sim, mq = make(), FakeMqtt()
    act = Actuator("c", sim, mq)
    topic = topics.signal_shift("c")
    mq.deliver(topic, Message("ia", {"shift_s": 4}, "s"))
    mq.deliver(topic, Message("ia", {"shift_s": 400}, "s"))
    mq.deliver(topic, Message("ia", {"shift_s": 2.5}, "s"))
    mq.deliver(topic, Message("ia", "garbage", "s"))
    assert act.shifts == 1 and act.rejected == 3
    sim.run(90)
    assert sim.cycle_len == 94


def test_shift_topic_qos_and_retained():
    assert topics.signal_shift("carrefour2") == "traffic/carrefour2/signal/shift"
    assert topics.QOS["shift"] == 2 and topics.RETAINED["shift"] is False


# --- platoons -------------------------------------------------------------------------------
def test_departures_reach_the_next_intersection_after_the_travel_time():
    cor = Corridor(rates=NORMAL, platoon=1.0, offsets=ideal_offsets(), seed=1)
    seen = 0
    for _ in range(400):
        cor.step()
        left = cor.sims["carrefour1"].phases[AVENUE].last_departed
        if left:
            seen += left
            assert cor._inflight[1][cor.t - 1 + config.TRAVEL_TIME] == left
    assert seen > 50


def test_platoon_conserves_vehicles():
    cor = Corridor(rates=NORMAL, platoon=1.0, offsets=[0, 20, 50], seed=2)
    cor.run(1200)
    for i in (1, 2):                                          # downstream: no external avenue flow
        up, down = (cor.sims[cor.carrefours[j]].phases[AVENUE] for j in (i - 1, i))
        in_flight = sum(cor._inflight[i].values())
        assert down.arrived - config.INITIAL_QUEUE + in_flight == up.departed


def test_platoon_fraction_splits_the_flow():
    cor = Corridor(rates=NORMAL, platoon=0.8, seed=3)
    cor.run(3000)
    up, down = (cor.sims[c].phases[AVENUE] for c in ("carrefour1", "carrefour2"))
    external = (1 - 0.8) * NORMAL[AVENUE] * 3000
    injected = down.arrived - config.INITIAL_QUEUE - external
    assert injected == pytest.approx(0.8 * up.departed, rel=0.12)


def test_no_platoon_means_independent_intersections():
    cor = Corridor(rates=NORMAL, platoon=0.0, seed=1)
    cor.run(600)
    assert all(not any(inflight.values()) for inflight in cor._inflight)


# --- the green wave pays off ------------------------------------------------------------------
def downstream_avenue_wait(offsets, seed):
    cor = Corridor(rates=NORMAL, offsets=offsets, seed=seed, strategy="centralized")
    cor.run(config.DURATION)
    phases = [cor.sims[c].phases[AVENUE] for c in cor.carrefours[1:]]
    return sum(p.total_wait(cor.t) for p in phases) / sum(p.arrived for p in phases)


def test_ideal_offsets_cut_the_waiting_time_on_the_avenue():
    seeds = range(3)
    wave = sum(downstream_avenue_wait(ideal_offsets(), s) for s in seeds) / 3
    aligned = sum(downstream_avenue_wait([0, 0, 0], s) for s in seeds) / 3
    reversed_ = sum(downstream_avenue_wait([60, 30, 0], s) for s in seeds) / 3
    assert wave < 0.6 * aligned < 0.6 * reversed_
    assert wave < 7 and reversed_ > 15


def test_offset_spread_measures_the_distance_to_a_green_wave():
    assert Corridor(offsets=ideal_offsets()).offset_spread() == 0
    assert Corridor(offsets=[0, 0, 0]).offset_spread() == 30       # aligned 0, -30, -60: 30 s apart on the 90 s circle
    assert Corridor(offsets=[10, 40, 70]).offset_spread() == 0     # a wave, whatever the start
