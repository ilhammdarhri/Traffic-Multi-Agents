"""The three research questions (subject no. 11). Each study writes CSV files in results/.

    python -m sim.studies q1 --seeds 10     price of anarchy against the traffic load
    python -m sim.studies q2 --seeds 10     consensus convergence, loss of an intersection
    python -m sim.studies q3 --seeds 10     priority of an emergency vehicle
    python -m sim.studies all --seeds 10

Q1  Static PoA of the green-sharing game (one cycle) for a grid of loads and queues, and the
    dynamic cost of selfishness: closed-loop mean wait of selfish / nash / centralized agents.
Q2  (a) cycles to consensus from random clocks, for several gains;
    (b) an intersection agent dies at t = 0, during convergence, after convergence, or dies and
        restarts: green wave kept? what does it cost?
Q3  An ambulance crosses the three intersections with and without priority: its delay, and the
    cost for the other vehicles.
"""
import argparse
import os

from agents.intersection import IntersectionAgent
from agents.utility import UtilityFunction
from agents.vehicles import EmergencyVehicleAgent
from coordination.game import GreenGame
from coordination.strategies import ConsensusStrategy
from sim import config
from sim.corridor import Corridor
from sim.metrics import Recorder, run_experiment
from sim.run_experiments import aggregate, write_csv
from sim.scenarios import initial_offsets
from sim.traffic import AVENUE, SIDE

OUT = "results"
NORMAL = config.ARRIVALS["normal"]
LOADS = (0.5, 0.7, 0.85, 1.0, 1.1, 1.2, 1.3)         # multiples of the normal arrival rates


def scaled(f):
    return {k: v * f for k, v in NORMAL.items()}


def stat(rows, key):
    agg = aggregate([r[key] for r in rows])
    return agg if agg else (None, None, None, 0)


def fmt(agg, nd=1):
    return "-" if agg[0] is None else f"{agg[0]:.{nd}f}"


# ---------------------------------------------------------------------------------- Q1
def q1_static():
    rows = []
    for f in LOADS:
        for q0 in (0, 5, 20, 40):
            game = GreenGame({AVENUE: UtilityFunction(arrival_rate=NORMAL[AVENUE] * f, q0=q0),
                              SIDE: UtilityFunction(arrival_rate=NORMAL[SIDE] * f, q0=q0)})
            rows.append({"load": f, "q0": q0, "poa": game.price_of_anarchy(),
                         "pos": game.price_of_stability(),
                         "n_equilibria": len(game.nash_equilibria())})
    return rows


def q1_dynamic(seeds, duration, log=print):
    rows = []
    for f in LOADS:
        for scenario in ("selfish", "nash", "centralized"):
            for seed in range(seeds):
                r = run_experiment(scenario, scaled(f), seed, duration)
                rows.append({"load": f, "scenario": scenario, "seed": seed, **r})
        log(f"  q1 load x{f}")
    return rows


def q1_summary(rows):
    out = []
    for f in LOADS:
        wait = {s: aggregate([r["mean_wait"] for r in rows if r["load"] == f and r["scenario"] == s])
                for s in ("selfish", "nash", "centralized")}
        out.append({"load": f,
                    "wait_selfish": wait["selfish"][0], "wait_nash": wait["nash"][0],
                    "wait_centralized": wait["centralized"][0],
                    "dynamic_poa": wait["selfish"][0] / wait["centralized"][0],
                    "nash_over_optimum": wait["nash"][0] / wait["centralized"][0]})
    return out


# ---------------------------------------------------------------------------------- Q2
def consensus_corridor(seed, gain, kb=None):
    return Corridor(rates=NORMAL, offsets=initial_offsets("consensus", seed), seed=seed, kb=kb,
                    strategy=ConsensusStrategy(gain=gain))


def q2_convergence(seeds, duration=1800):
    rows = []
    for gain in (0.2, 0.3, 0.4, 0.6, 0.8, 1.0):
        for seed in range(seeds):
            rec = Recorder(consensus_corridor(seed, gain))
            for _ in range(duration):
                rec.step()
            s = rec.summary()
            rows.append({"gain": gain, "seed": seed, "convergence_cycles": s["convergence_cycles"],
                         "wave_cycle": s["wave_cycle"], "offset_gap": s["offset_gap"],
                         "mean_wait": s["mean_wait"]})
    return rows


def crash(c):
    return lambda cor: cor.crash_agent(c)


def restart(c):
    return lambda cor: cor.recover_agent(c)


FAILURES = {                       # name -> events (time, function(corridor))
    "none": [],
    "c1 dies at 0 s": [(0, crash("carrefour1"))],
    "c2 dies at 0 s": [(0, crash("carrefour2"))],
    "c2 dies at 300 s (converging)": [(300, crash("carrefour2"))],
    "c2 dies at 1800 s (converged)": [(1800, crash("carrefour2"))],
    "c3 dies at 300 s (converging)": [(300, crash("carrefour3"))],
    "c2 dies at 300 s, restarts at 1500 s": [(300, crash("carrefour2")), (1500, restart("carrefour2"))],
}


def q2_failures(seeds, duration, log=print):
    rows = []
    for name, events in FAILURES.items():
        for seed in range(seeds):
            r = run_experiment("consensus", NORMAL, seed, duration, events=events)
            rows.append({"case": name, "seed": seed, **r})
        log(f"  q2 {name}")
    for seed in range(seeds):                      # reference: agents never coordinate their offsets
        rows.append({"case": "no consensus (nash)", "seed": seed,
                     **run_experiment("nash", NORMAL, seed, duration)})
    return rows


# ---------------------------------------------------------------------------------- Q3
ROUTE = [("carrefour1", AVENUE), ("carrefour2", AVENUE), ("carrefour3", AVENUE)]


def q3_priority(seeds, kb, demands=("normal", "peak"), n_starts=8, log=print):
    rows = []
    for demand in demands:
        rates = config.ARRIVALS[demand]
        for seed in range(seeds):
            for k in range(n_starts):
                start = 900 + 11 * k + 3 * seed             # varied position in the cycle
                result = {}
                for priority in (False, True):
                    cor = Corridor(rates=rates, offsets=initial_offsets("centralized", seed), seed=seed,
                                   kb=kb, strategy="consensus")
                    ev = EmergencyVehicleAgent("ev1", ROUTE, cor.broker.client("ev1"), first_eta=40,
                                               priority=priority)
                    cor.add_vehicle(ev, start_t=start)
                    cor.run(start + 250)
                    result[priority] = (ev, cor)
                (ev0, c0), (ev1, c1) = result[False], result[True]
                rows.append({"demand": demand, "seed": seed, "start": start,
                             "ev_delay_off": ev0.total_delay, "ev_delay_on": ev1.total_delay,
                             "others_wait_off": c0.mean_wait(), "others_wait_on": c1.mean_wait(),
                             "preemptions": sum(a.preemptions for a in c1.actuators.values())})
        log(f"  q3 {demand}")
    return rows


def q3_summary(rows):
    out = []
    for demand in dict.fromkeys(r["demand"] for r in rows):
        g = [r for r in rows if r["demand"] == demand]
        m = lambda key: sum(r[key] for r in g) / len(g)
        out.append({"demand": demand, "n": len(g),
                    "ev_delay_off": m("ev_delay_off"), "ev_delay_on": m("ev_delay_on"),
                    "others_wait_off": m("others_wait_off"), "others_wait_on": m("others_wait_on"),
                    "cost_for_others_pct": 100 * (m("others_wait_on") / m("others_wait_off") - 1)})
    return out


# ---------------------------------------------------------------------------------- CLI
def run_q1(a):
    static, dyn = q1_static(), q1_dynamic(a.seeds, a.duration)
    summary = q1_summary(dyn)
    write_csv(f"{a.out}/q1_static.csv", static)
    write_csv(f"{a.out}/q1_dynamic.csv", dyn)
    write_csv(f"{a.out}/q1_summary.csv", summary)
    print("\nQ1 static PoA (one cycle), q0 = 5 vehicles:")
    for r in static:
        if r["q0"] == 5:
            print(f"  load x{r['load']:<4} PoA {r['poa']:.3f}  PoS {r['pos']:.3f}  equilibria {r['n_equilibria']}")
    print("\nQ1 dynamic cost of selfishness (mean wait, s):")
    for r in summary:
        print(f"  load x{r['load']:<4} selfish {r['wait_selfish']:6.1f}  nash {r['wait_nash']:6.1f}  "
              f"optimum {r['wait_centralized']:6.1f}  selfish/optimum {r['dynamic_poa']:.1f}")


def run_q2(a):
    conv = q2_convergence(a.seeds)
    write_csv(f"{a.out}/q2_convergence.csv", conv)
    print("\nQ2a cycles to consensus from random clocks (mean over seeds):")
    for gain in dict.fromkeys(r["gain"] for r in conv):
        g = [r for r in conv if r["gain"] == gain]
        print(f"  gain {gain}: convergence {fmt(stat(g, 'convergence_cycles'))} cycles "
              f"({sum(r['convergence_cycles'] is None for r in g)}/{len(g)} never), "
              f"wave after {fmt(stat(g, 'wave_cycle'))} cycles, final gap {fmt(stat(g, 'offset_gap'))} s")
    fail = q2_failures(a.seeds, a.duration)
    write_csv(f"{a.out}/q2_failures.csv", fail)
    print("\nQ2b loss of an intersection agent:")
    for case in dict.fromkeys(r["case"] for r in fail):
        g = [r for r in fail if r["case"] == case]
        print(f"  {case:40s} wait {fmt(stat(g, 'mean_wait'))} s  final gap {fmt(stat(g, 'offset_gap'))} s")


def run_q3(a):
    from kb.knowledge_base import KnowledgeBase
    rows = q3_priority(a.seeds, KnowledgeBase())
    write_csv(f"{a.out}/q3_priority.csv", rows)
    summary = q3_summary(rows)
    write_csv(f"{a.out}/q3_summary.csv", summary)
    print("\nQ3 emergency vehicle priority:")
    for r in summary:
        print(f"  {r['demand']:6s} EV delay {r['ev_delay_off']:5.1f} s -> {r['ev_delay_on']:4.1f} s   "
              f"others {r['others_wait_off']:.1f} -> {r['others_wait_on']:.1f} s "
              f"({r['cost_for_others_pct']:+.1f} %)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("study", choices=("q1", "q2", "q3", "all"))
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--duration", type=int, default=config.DURATION)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for name, fn in (("q1", run_q1), ("q2", run_q2), ("q3", run_q3)):
        if a.study in (name, "all"):
            fn(a)


if __name__ == "__main__":
    main()
