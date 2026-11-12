import pytest

from agents.base import Agent, UtilityAgent
from agents.utility import UtilityFunction
from sim import config


# --- UtilityFunction -------------------------------------------------------
def test_queue_and_utility_values():
    u = UtilityFunction(weight=1.0, arrival_rate=0.25, q0=5)
    # Q(40) = 5 + 22.5 - 20 = 7.5  ->  U = 92.5
    assert u.predicted_queue(40) == pytest.approx(7.5)
    assert u(40) == pytest.approx(92.5)


def test_queue_is_clipped_at_zero():
    u = UtilityFunction(arrival_rate=0.25, q0=5)
    assert u.predicted_queue(80) == 0.0
    assert u(80) == 100.0


def test_utility_never_decreases_with_green():
    u = UtilityFunction(weight=1.5, arrival_rate=0.30, q0=5)
    values = [u(g) for g in range(0, 81)]
    assert all(b >= a for a, b in zip(values, values[1:]))


def test_weight_scales_penalty():
    light = UtilityFunction(weight=1.0, arrival_rate=0.25, q0=5)
    bus = UtilityFunction(weight=1.5, arrival_rate=0.25, q0=5)
    assert 100 - bus(30) == pytest.approx(1.5 * (100 - light(30)))


def test_required_green_clears_queue():
    u = UtilityFunction(arrival_rate=0.25, q0=5)
    assert u.required_green() == pytest.approx(55.0)
    assert u.predicted_queue(u.required_green()) == pytest.approx(0.0)


def test_updated_returns_new_object():
    u = UtilityFunction(arrival_rate=0.25, q0=5)
    v = u.updated(q0=20)
    assert u.q0 == 5 and v.q0 == 20


# --- Agent / UtilityAgent --------------------------------------------------
def test_agent_is_abstract():
    with pytest.raises(TypeError):
        Agent("x")
    with pytest.raises(TypeError):
        UtilityAgent("x")


class TwoPhaseToy(UtilityAgent):
    """Toy intersection: chooses (g_avenue, g_side) maximising the summed utility."""

    def __init__(self, agent_id, avenue, side):
        super().__init__(agent_id)
        self.fn = (avenue, side)
        self.sent = []

    def feasible_actions(self):
        total = config.GREEN_BUDGET
        for g_a in range(config.G_MIN, total - config.G_MIN + 1):
            yield (g_a, total - g_a)

    def utility(self, action):
        return sum(f(g) for f, g in zip(self.fn, action))

    def act(self, action):
        self.sent.append(action)


def test_decide_is_argmax_and_respects_constraints():
    avenue = UtilityFunction(arrival_rate=0.25, q0=5)
    side = UtilityFunction(arrival_rate=0.10, q0=5)
    agent = TwoPhaseToy("ia-c1", avenue, side)
    g_a, g_s = agent.decide()
    assert g_a + g_s == config.GREEN_BUDGET
    assert g_a >= config.G_MIN and g_s >= config.G_MIN
    # optimum is a plateau (total residual queue 1.5) for g_a in [52, 55]
    assert 52 <= g_a <= 55
    best = agent.utility((g_a, g_s))
    assert all(agent.utility(a) <= best + 1e-9 for a in agent.feasible_actions())
    assert best > agent.utility((40, 40))            # better than an even split


def test_heavier_weight_attracts_green():
    # Oversaturated: both phases want more than the 80 s budget. With equal weights the
    # utility is flat (every split ties, first maximum wins); a heavier weight on the
    # avenue breaks the tie and pulls green towards it until its queue is cleared (64 s).
    side = UtilityFunction(arrival_rate=0.25, q0=5)
    avenue_light = UtilityFunction(weight=1.0, arrival_rate=0.30, q0=5)
    avenue_bus = UtilityFunction(weight=3.0, arrival_rate=0.30, q0=5)
    g_light = TwoPhaseToy("a", avenue_light, side).decide()[0]
    g_bus = TwoPhaseToy("b", avenue_bus, side).decide()[0]
    assert g_bus > g_light
    assert g_bus == 64                      # avenue queue fully cleared, rest to the side


def test_step_runs_full_cycle():
    avenue = UtilityFunction(arrival_rate=0.25, q0=5)
    side = UtilityFunction(arrival_rate=0.10, q0=5)
    agent = TwoPhaseToy("ia-c1", avenue, side)
    action = agent.step({"queue_avenue": 7})
    assert agent.state["queue_avenue"] == 7
    assert agent.sent == [action] and agent.last_action == action


def test_no_feasible_action_raises():
    class Empty(UtilityAgent):
        def feasible_actions(self):
            return []
        def utility(self, action):
            return 0
    with pytest.raises(RuntimeError):
        Empty("e").decide()
