"""Multi-seed experiment runner.

    python -m sim.run_experiments --seeds 20                 # 2 demands x 4 scenarios x 20 seeds
    python -m sim.run_experiments --seeds 3 --duration 900   # quick check
    python -m sim.run_experiments --broker mqtt --seeds 1 --duration 900
        # same runs over a real MQTT broker (localhost:1883), checked against the loopback runs

Writes  results/runs.csv     one row per (demand, scenario, seed)
        results/summary.csv  mean, standard deviation and 95 % confidence half-width per metric
Everything is seeded: the same command gives the same files.
"""
import argparse
import csv
import math
import os
import time

from sim import config
from sim.metrics import run_experiment
from sim.scenarios import SCENARIOS

DEMANDS = ("normal", "peak")
METRICS = ("mean_wait", "max_queue", "stops_per_vehicle", "jain_wait", "poa_cycle", "pos_cycle",
           "poa_defined", "convergence_cycles", "offset_gap", "wave_cycle", "vehicles")
# two-sided 95 % Student t quantiles by degrees of freedom (n - 1)
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23,
       11: 2.20, 12: 2.18, 13: 2.16, 14: 2.14, 15: 2.13, 16: 2.12, 17: 2.11, 18: 2.10, 19: 2.09,
       20: 2.09, 24: 2.06, 29: 2.05}


def t_quantile(df):
    if df < 1:
        return math.nan
    keys = [k for k in T95 if k >= df]
    return T95[min(keys)] if keys else 1.96


def aggregate(values):
    """(mean, std, ci95 half-width, n) of the defined values; None if there are none."""
    xs = [v for v in values if v is not None and v == v]
    if not xs:
        return None
    n, mean = len(xs), sum(xs) / len(xs)
    std = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    ci = t_quantile(n - 1) * std / math.sqrt(n) if n > 1 else math.nan
    return mean, std, ci, n


def run_grid(seeds, duration, demands=DEMANDS, scenarios=SCENARIOS, broker_factory=None, log=print):
    rows = []
    for demand in demands:
        for scenario in scenarios:
            for seed in range(seeds):
                broker = broker_factory() if broker_factory else None
                t0 = time.time()
                try:
                    r = run_experiment(scenario, config.ARRIVALS[demand], seed, duration, broker=broker)
                finally:
                    if broker is not None and hasattr(broker, "close"):
                        broker.close()
                rows.append({"demand": demand, "scenario": scenario, "seed": seed, **r})
                log(f"  {demand:6s} {scenario:12s} seed {seed:2d}  wait {r['mean_wait']:7.1f} s"
                    f"  ({time.time() - t0:.1f} s)")
    return rows


def summarize(rows):
    out = []
    for demand in dict.fromkeys(r["demand"] for r in rows):
        for scenario in dict.fromkeys(r["scenario"] for r in rows if r["demand"] == demand):
            group = [r for r in rows if r["demand"] == demand and r["scenario"] == scenario]
            line = {"demand": demand, "scenario": scenario, "n": len(group)}
            for m in METRICS:
                agg = aggregate([r[m] for r in group])
                line[f"{m}_mean"], line[f"{m}_std"], line[f"{m}_ci95"] = agg[:3] if agg else (None,) * 3
            out.append(line)
    return out


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def print_table(summary):
    print(f"\n{'demand':7s}{'scenario':13s}{'mean wait (s)':>18s}{'max queue':>11s}{'stops/veh':>11s}"
          f"{'Jain':>7s}{'conv. cycles':>14s}")
    for s in summary:
        conv = s["convergence_cycles_mean"]
        print(f"{s['demand']:7s}{s['scenario']:13s}"
              f"{s['mean_wait_mean']:11.1f} ±{s['mean_wait_ci95']:5.1f}"
              f"{s['max_queue_mean']:11.0f}{s['stops_per_vehicle_mean']:11.2f}{s['jain_wait_mean']:7.2f}"
              f"{(f'{conv:.1f}' if conv is not None else '-'):>14s}")


def compare_with_loopback(rows_mqtt, seeds, duration):
    """The real broker must give the loopback results exactly (lockstep run)."""
    ref = run_grid(seeds, duration, log=lambda *_: None)
    key = lambda r: (r["demand"], r["scenario"], r["seed"])
    ref = {key(r): r for r in ref}
    bad = [key(r) for r in rows_mqtt if r != ref[key(r)]]
    print(f"\nreal broker vs loopback: {len(rows_mqtt) - len(bad)}/{len(rows_mqtt)} runs identical")
    for k in bad:
        print("  DIFFERENT:", k)
    return not bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--duration", type=int, default=config.DURATION)
    ap.add_argument("--out", default="results")
    ap.add_argument("--broker", choices=("loopback", "mqtt"), default="loopback")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    a = ap.parse_args(argv)

    factory = None
    suffix = ""
    if a.broker == "mqtt":
        from sim.real_broker import RealBroker
        factory = lambda: RealBroker(a.host, a.port)
        suffix = "_mqtt"
    print(f"{len(DEMANDS) * len(SCENARIOS) * a.seeds} runs of {a.duration} s over the {a.broker} broker")
    rows = run_grid(a.seeds, a.duration, broker_factory=factory)
    summary = summarize(rows)
    write_csv(os.path.join(a.out, f"runs{suffix}.csv"), rows)
    write_csv(os.path.join(a.out, f"summary{suffix}.csv"), summary)
    print_table(summary)
    print(f"\nwritten: {a.out}/runs{suffix}.csv, {a.out}/summary{suffix}.csv")
    if a.broker == "mqtt":
        return 0 if compare_with_loopback(rows, a.seeds, a.duration) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
