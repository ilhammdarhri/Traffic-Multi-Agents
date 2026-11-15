import pytest

from agents.intersection import IntersectionAgent
from coordination.strategies import (STRATEGIES, CentralizedStrategy, CoordinationStrategy,
                                     NashStrategy, SelfishStrategy, make_strategy,
                                     resolve_strategy)
from sim import config
from sim.corridor import Corridor
from sim.traffic import AVENUE, SIDE, validate_plan
from tests.test_intersection_agent import LoopbackMqtt
from tests.test_traffic_devices import FakeMqtt

NORMAL, PEAK = config.ARRIVALS["normal"], config.ARRIVALS["peak"]


def agent(strategy, rates=NORMAL, queues=(5, 5)):
    ia = IntersectionAgent("carrefour1", FakeMqtt(), arrival_rates=rates, strategy=strategy)
    ia.update_state({AVENUE: queues[0], SIDE: queues[1]})
    return ia


# --- the pattern --------------------------------------------------------------------
def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        CoordinationStrategy()


def test_registry_and_factory():
    assert set(STRATEGIES) == {"selfish", "nash", "consensus", "centralized"}
    assert isinstance(make_strategy("nash"), NashStrategy)
    with pytest.raises(ValueError):
        make_strategy("telepathy")


def test_resolve_strategy():
    assert isinstance(resolve_strategy(None), CentralizedStrategy)        # default
    assert isinstance(resolve_strategy("selfish"), SelfishStrategy)
    s = NashStrategy()
    assert resolve_strategy(s) is s


# --- each strategy decides differently on the same state ----------------------------------
@pytest.mark.parametrize("strategy,expected", [
    ("selfish", (40, 40)), ("nash", (52, 28)), ("consensus", (52, 28)), ("centralized", (53, 27))])
def test_agent_decision_per_strategy(strategy, expected):
    assert agent(strategy).decide() == expected


def test_default_strategy_keeps_the_previous_behaviour():
    assert agent(None).decide() == (53, 27)


def test_strategy_can_be_swapped_at_runtime():
    ia = agent("selfish")
    assert ia.decide() == (40, 40)
    ia.strategy = CentralizedStrategy()
    assert ia.decide() == (53, 27)


def test_every_strategy_publishes_valid_plans():
    for name in STRATEGIES:
        for rates in (NORMAL, PEAK):
            for queues in ((0, 0), (5, 5), (30, 2), (2, 60)):
                ia = agent(name, rates, queues)
                action = ia.decide()
                assert validate_plan({AVENUE: action[0], SIDE: action[1]}), (name, rates, queues)
                ia.act(action)
                assert ia.mqtt.published[-1][2] == "plan"


# --- closed loop: sensors -> agent(strategy) -> actuator -> simulator -------------------------
def run_corridor(strategy, rates, seed=1, seconds=3600, platoon=0.0):
    """Independent intersections (platoon = 0): isolates the effect of the green split."""
    cor = Corridor(rates=rates, seed=seed, strategy=strategy, platoon=platoon)
    worst = 0
    for _ in range(seconds):
        cor.step()
        worst = max(worst, *(max(s.queue_lengths().values()) for s in cor.sims.values()))
    return cor.mean_wait(), worst


def test_scenarios_are_ordered_on_normal_demand():
    results = {name: run_corridor(name, NORMAL) for name in ("selfish", "nash", "centralized")}
    wait = {n: r[0] for n, r in results.items()}
    worst = {n: r[1] for n, r in results.items()}
    # selfish agents (equal split) starve the avenue, which needs 55 s of green
    assert wait["selfish"] > 5 * wait["nash"]
    assert worst["selfish"] > 3 * worst["nash"]
    # negotiation gets close to the optimum
    assert wait["nash"] < 1.5 * wait["centralized"] + 2
    assert wait["centralized"] <= wait["nash"] + 1.0


def test_corridor_accepts_a_strategy_instance_and_a_name():
    a = Corridor(strategy=SelfishStrategy())
    b = Corridor(strategy="selfish")
    assert all(isinstance(ag.strategy, SelfishStrategy) for ag in list(a.agents.values()) + list(b.agents.values()))
