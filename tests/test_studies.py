from kb.knowledge_base import KnowledgeBase
from sim import config
from sim.studies import (FAILURES, LOADS, q1_static, q1_summary, q2_convergence, q3_priority,
                         q3_summary)
from sim.metrics import run_experiment

NORMAL = config.ARRIVALS["normal"]


def test_q1_static_poa_is_one_when_everything_fits_and_small_otherwise():
    rows = q1_static()
    assert len(rows) == len(LOADS) * 4
    assert all(r["poa"] >= 1 - 1e-9 for r in rows if r["poa"] == r["poa"])
    light = [r for r in rows if r["load"] == 0.5 and r["q0"] == 0]
    assert abs(light[0]["poa"] - 1) < 1e-6                  # selfish asks for everything it needs: no loss


def test_q1_summary_selfishness_costs_more_under_load():
    from sim.studies import scaled
    rows = [{"load": f, "scenario": s, "seed": 0, **run_experiment(s, scaled(f), 0, 900)}
            for f in LOADS for s in ("selfish", "nash", "centralized")]
    out = {r["load"]: r for r in q1_summary(rows)}
    assert out[1.0]["dynamic_poa"] > out[0.5]["dynamic_poa"] > 1.0


def test_q2_convergence_every_gain_converges():
    rows = q2_convergence(1, duration=1500)
    assert all(r["convergence_cycles"] is not None for r in rows)


def test_q2_failure_cases_run_with_scheduled_events():
    r = run_experiment("consensus", NORMAL, 0, 900, events=FAILURES["c2 dies at 300 s (converging)"])
    assert r["offset_gap"] <= 3
    never_heard = run_experiment("consensus", NORMAL, 0, 900, events=FAILURES["c1 dies at 0 s"])
    assert never_heard["offset_gap"] > 3                    # a node that never spoke cannot be aligned with


def test_q3_priority_removes_emergency_delay():
    rows = q3_priority(1, KnowledgeBase(), demands=("normal",), n_starts=3, log=lambda *_: None)
    s = q3_summary(rows)[0]
    assert s["ev_delay_off"] > 5 and s["ev_delay_on"] < 0.25 * s["ev_delay_off"]
    assert s["cost_for_others_pct"] < 15
