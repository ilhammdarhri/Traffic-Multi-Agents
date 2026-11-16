import math

from sim import config
from sim.metrics import Recorder, run_experiment
from sim.scenarios import make_corridor

NORMAL = config.ARRIVALS["normal"]


def test_summary_fields_and_ranges():
    r = run_experiment("consensus", NORMAL, 1, duration=900)
    assert 0 <= r["stops_per_vehicle"] <= 1 and 0 < r["jain_wait"] <= 1
    assert r["mean_wait"] > 0 and r["max_queue"] >= config.INITIAL_QUEUE
    assert 1 <= r["poa_cycle"] < 1.2 and r["pos_cycle"] >= 1
    assert 0 < r["poa_defined"] <= 1 and r["vehicles"] > 0


def test_convergence_only_for_consensus():
    assert run_experiment("nash", NORMAL, 1, duration=900)["convergence_cycles"] is None
    r = run_experiment("consensus", NORMAL, 1, duration=900)
    assert 1 <= r["convergence_cycles"] <= 15 and r["wave_cycle"] is not None


def test_recorder_matches_corridor_and_is_deterministic():
    a = Recorder(make_corridor("nash", NORMAL, 2))
    for _ in range(600):
        a.step()
    assert math.isclose(a.summary()["mean_wait"], a.cor.mean_wait())
    assert run_experiment("nash", NORMAL, 2, duration=600) == a.summary()


def test_selfish_is_worst_in_peak():
    peak = config.ARRIVALS["peak"]
    waits = {s: run_experiment(s, peak, 1, duration=1800)["mean_wait"]
             for s in ("selfish", "nash", "centralized")}
    assert waits["selfish"] > waits["nash"] > waits["centralized"]
