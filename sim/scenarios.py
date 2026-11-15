"""The four comparison scenarios of the subject.

    selfish      phases grab the maximum green (Nash equilibrium); clocks are not coordinated
    nash         phases bargain the split (Nash bargaining);       clocks are not coordinated
    consensus    Nash bargaining + consensus on the offsets between neighbours (MQTT)
    centralized  social optimum for every split + ideal offsets (green wave from the start)

"Clocks not coordinated" = every controller starts at its own random offset. The random offsets
depend only on the seed, so scenarios 1-3 start from the same offsets (paired comparison).
"""
import numpy as np

from sim import config
from sim.corridor import Corridor

SCENARIOS = ("selfish", "nash", "consensus", "centralized")


def ideal_offsets(n=config.N_INTERSECTIONS):
    """Green wave: each intersection starts TRAVEL_TIME after the previous one."""
    return [(i * config.TRAVEL_TIME) % config.CYCLE for i in range(n)]


def random_offsets(seed, n=config.N_INTERSECTIONS):
    rng = np.random.default_rng(10_000 + seed)
    return [int(x) for x in rng.integers(0, config.CYCLE, n)]


def initial_offsets(scenario, seed, n=config.N_INTERSECTIONS):
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {SCENARIOS}")
    return ideal_offsets(n) if scenario == "centralized" else random_offsets(seed, n)


def make_corridor(scenario, rates, seed, kb=None, broker=None):
    return Corridor(rates=rates, offsets=initial_offsets(scenario, seed), seed=seed, kb=kb,
                    broker=broker, strategy=scenario)
