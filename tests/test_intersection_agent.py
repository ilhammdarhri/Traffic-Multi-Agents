import pytest

from agents.approach import ApproachAgent
from agents.intersection import IntersectionAgent
from sim import config
from sim.devices import Actuator
from sim.message import Message
from sim.mqtt_client import topic_matches
from sim.traffic import AVENUE, SIDE, IntersectionSim
from tests.test_traffic_devices import FakeMqtt

NORMAL, PEAK = config.ARRIVALS["normal"], config.ARRIVALS["peak"]


class LoopbackMqtt(FakeMqtt):
    """Fake broker: a publish is delivered to every matching subscriber."""

    def publish(self, topic, message, kind):
        super().publish(topic, message, kind)
        self.deliver(topic, message)


def agent_with(queues, rates=NORMAL, **kw):
    mq = FakeMqtt()
    ia = IntersectionAgent("carrefour1", mq, arrival_rates=rates, **kw)
    ia.update_state(queues)
    return ia, mq


# --- decision ---------------------------------------------------------------
def test_feasible_actions_respect_coupling_constraint():
    ia, _ = agent_with({AVENUE: 5, SIDE: 5})
    actions = list(ia.feasible_actions())
    assert len(actions) == config.GREEN_BUDGET - 2 * config.G_MIN + 1      # 61
    assert all(a + b == config.GREEN_BUDGET and min(a, b) >= config.G_MIN for a, b in actions)


def test_normal_demand_split():
    ia, _ = agent_with({AVENUE: 5, SIDE: 5})
    g_a, g_s = ia.decide()
    assert (g_a, g_s) == (53, 27)             # in the plateau [52, 55], closest to proportional
    assert 52 <= g_a <= 55


def test_peak_demand_split_is_optimal_and_proportional():
    ia, _ = agent_with({AVENUE: 5, SIDE: 5}, rates=PEAK)
    action = ia.decide()
    best = max(ia.utility(a) for a in ia.feasible_actions())
    assert ia.utility(action) == pytest.approx(best)
    assert action == (51, 29)


def test_longer_queue_gets_more_green():
    long_avenue, _ = agent_with({AVENUE: 40, SIDE: 5})
    long_side, _ = agent_with({AVENUE: 5, SIDE: 40})
    assert long_avenue.decide()[0] > long_side.decide()[0]


def test_weight_breaks_the_plateau():
    # peak demand: heavier side weight pulls green to the side until its queue is cleared (37 s)
    ia, _ = agent_with({AVENUE: 5, SIDE: 5}, rates=PEAK, weights={SIDE: 3.0})
    assert ia.decide() == (43, 37)


def test_weights_from_knowledge_base():
    class KB:
        def weight(self, carrefour, phase):
            return 3.0 if phase == SIDE else 1.0
    ia, _ = agent_with({AVENUE: 5, SIDE: 5}, rates=PEAK, kb=KB())
    assert ia.decide() == (43, 37)


# --- messaging ----------------------------------------------------------------
def test_agent_publishes_plan_on_plan_topic():
    ia, mq = agent_with({AVENUE: 5, SIDE: 5})
    ia.act(ia.decide())
    topic, msg, kind = mq.published[-1]
    assert topic == "traffic/carrefour1/signal/plan" and kind == "plan"
    assert msg.valeur == {"avenue": 53, "side": 27} and msg.unite == "s"
    assert msg.source == "ia-carrefour1"


def test_agent_listens_to_its_own_carrefour_only():
    mq = FakeMqtt()
    ia = IntersectionAgent("carrefour1", mq)
    mq.deliver("traffic/carrefour1/approach/avenue/queue", Message("l", 12, "vehicules"))
    mq.deliver("traffic/carrefour2/approach/avenue/queue", Message("l", 99, "vehicules"))
    mq.deliver("traffic/carrefour1/approach/side/queue", Message("l", 7, "vehicules"))
    assert ia.queues == {AVENUE: 12, SIDE: 7}
    assert topic_matches(mq.subs[0][0], "traffic/carrefour1/approach/side/queue")


def test_approach_agent_publishes_measure():
    sim, mq = IntersectionSim("carrefour1", NORMAL), FakeMqtt()
    aa = ApproachAgent("carrefour1", AVENUE, lambda: len(sim.phases[AVENUE]), mq)
    assert aa.sense() == config.INITIAL_QUEUE
    topic, msg, kind = mq.published[0]
    assert topic == "traffic/carrefour1/approach/avenue/queue" and msg.valeur == config.INITIAL_QUEUE


# --- closed loop: sensors -> agent -> actuator -> simulator ---------------------
def run_closed_loop(rates, cycles=40, seed=1):
    mq = LoopbackMqtt()
    sim = IntersectionSim("carrefour1", rates, seed=seed)
    approaches = [ApproachAgent("carrefour1", p, (lambda p=p: len(sim.phases[p])), mq) for p in (AVENUE, SIDE)]
    ia = IntersectionAgent("carrefour1", mq, arrival_rates=rates)
    act = Actuator("carrefour1", sim, mq)
    worst = 0
    for _ in range(cycles):
        for _ in range(85):                      # measure at the end of the cycle (last red)
            act.tick(); sim.step()
            worst = max(worst, *sim.queue_lengths().values())
        for aa in approaches:
            aa.sense()
        ia.decide_cycle()                        # plan applied at the next cycle start
        for _ in range(config.CYCLE - 85):
            act.tick(); sim.step()
            worst = max(worst, *sim.queue_lengths().values())
    return sim, worst


def test_closed_loop_beats_fixed_even_split():
    sim_fixed = IntersectionSim("carrefour1", NORMAL, seed=1)       # default 40/40 plan
    worst_fixed = 0
    for _ in range(40 * config.CYCLE):
        sim_fixed.step()
        worst_fixed = max(worst_fixed, *sim_fixed.queue_lengths().values())

    sim_agent, worst_agent = run_closed_loop(NORMAL)
    assert worst_fixed > 100                      # 40 s of avenue green is not enough (needs 45)
    assert worst_agent < 60                       # the agent keeps both queues bounded
    now = 40 * config.CYCLE
    assert sim_agent.phases[AVENUE].total_wait(now) < sim_fixed.phases[AVENUE].total_wait(now)
