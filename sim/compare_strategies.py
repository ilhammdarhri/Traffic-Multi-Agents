"""Quick comparison of the four scenarios: selfish, nash, consensus, centralized.

    python -m sim.compare_strategies [--seeds 5]

Part 1  one-cycle game (queues 5 / 5): outcome of each split strategy, price of anarchy.
Part 2  closed loop on the 3-intersection corridor, 3600 s, averaged over the seeds, starting
        from random controller clocks (ideal green-wave offsets for 'centralized').
(The full experiment runner with CSV export comes in the experiments phase.)
"""
import argparse
from statistics import mean

from agents.utility import UtilityFunction
from coordination.game import GreenGame
from coordination.strategies import make_strategy
from sim import config
from sim.scenarios import SCENARIOS, make_corridor
from sim.traffic import AVENUE, SIDE


def one_cycle_game(rates, q0=5):
    return GreenGame({AVENUE: UtilityFunction(arrival_rate=rates[AVENUE], q0=q0),
                      SIDE: UtilityFunction(arrival_rate=rates[SIDE], q0=q0)})


def closed_loop(scenario, rates, seed):
    """Returns (mean wait, max queue, final offset spread, first cycle with spread <= 2 s)."""
    cor = make_corridor(scenario, rates, seed)
    worst, wave_at = 0, None
    for _ in range(config.DURATION):
        cor.step()
        worst = max(worst, *(max(s.queue_lengths().values()) for s in cor.sims.values()))
        if wave_at is None and cor.offset_spread() <= 2:
            wave_at = cor.t // config.CYCLE
    return cor.mean_wait(), worst, cor.offset_spread(), wave_at


def main(n_seeds):
    print("Part 1 - one-cycle game, queues 5/5 (split = green avenue/side in s, W = summed utility)")
    print(f"{'demand':8s} {'selfish':>16s} {'nash':>16s} {'centralized':>16s} {'PoA':>7s} {'PoS':>7s}")
    for regime, rates in config.ARRIVALS.items():
        game = one_cycle_game(rates)
        cells = []
        for name in ("selfish", "nash", "centralized"):
            split = make_strategy(name).choose_split(game)
            cells.append(f"{split[0]:2d}/{split[1]:2d}  W={game.welfare(split):6.1f}")
        print(f"{regime:8s} {cells[0]:>16s} {cells[1]:>16s} {cells[2]:>16s} "
              f"{game.price_of_anarchy():7.4f} {game.price_of_stability():7.4f}")

    print(f"\nPart 2 - closed loop, 3 intersections, {config.DURATION} s, {n_seeds} seeds")
    print(f"{'demand':8s} {'scenario':12s} {'mean wait (s)':>14s} {'max queue':>10s} "
          f"{'offset gap (s)':>15s} {'wave after (cycles)':>20s}")
    for regime, rates in config.ARRIVALS.items():
        for name in SCENARIOS:
            runs = [closed_loop(name, rates, seed) for seed in range(n_seeds)]
            reached = [r[3] for r in runs if r[3] is not None]
            wave = f"{mean(reached):.1f}" if len(reached) == len(runs) else "never"
            print(f"{regime:8s} {name:12s} {mean(r[0] for r in runs):14.1f} {mean(r[1] for r in runs):10.0f} "
                  f"{mean(r[2] for r in runs):15.1f} {wave:>20s}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=5)
    main(parser.parse_args().seeds)
