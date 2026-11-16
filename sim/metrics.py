"""Metrics of a corridor run (subject no. 11) and a one-call experiment runner.

    mean_wait          mean waiting time (s) per vehicle, queued vehicles included
    max_queue          largest queue seen on any approach (vehicles)
    stops_per_vehicle  share of vehicles that had to stop (waited > 0 s): one stop per intersection
    jain_wait          Jain index of the mean wait of the 6 approaches (1 = equal for all)
    poa_cycle          mean over the decisions where it is defined of PoA = max_a sum U / sum U(worst Nash)
    poa_defined        share of decisions where PoA is defined (welfares > 0, i.e. queues below 100)
    pos_cycle          same with the best Nash equilibrium (price of stability)
    convergence_cycles consensus only: iterations until every agent detected convergence (None: never)
    offset_gap         final distance (s) from a perfect green wave
    wave_cycle         first cycle where the gap is <= 2 s (None: never)
"""
from coordination.game import jain_index
from sim import config
from sim.scenarios import make_corridor


class Recorder:
    """Watches a Corridor second by second without touching it."""

    def __init__(self, corridor):
        self.cor = corridor
        self.max_queue = 0
        self.wave_cycle = None
        self._poa, self._pos = [], []
        self._seen = {c: 0 for c in corridor.carrefours}

    def step(self):
        cor = self.cor
        cor.step()
        for c, sim in cor.sims.items():
            self.max_queue = max(self.max_queue, *sim.queue_lengths().values())
            agent = cor.agents[c]
            if agent.cycles > self._seen[c] and not agent.degraded:      # a new decision was taken
                self._seen[c] = agent.cycles
                game = agent.game()
                self._poa.append(game.price_of_anarchy())
                self._pos.append(game.price_of_stability())
        if self.wave_cycle is None and cor.offset_spread() <= 2:
            self.wave_cycle = cor.t // config.CYCLE

    def summary(self):
        cor, t = self.cor, self.cor.t
        phases = [p for s in cor.sims.values() for p in s.phases.values()]
        arrived = sum(p.arrived for p in phases)
        stopped = sum(sum(w > 0 for w in p.waits) + sum(t - a > 0 for a in p.queue) for p in phases)
        per_phase = [p.total_wait(t) / p.arrived for p in phases if p.arrived]
        nodes = [a.strategy.node for a in cor.agents.values() if getattr(a.strategy, "node", None)]
        done = [n.converged_at for n in nodes]
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        poa = [x for x in self._poa if x == x]           # PoA is undefined (nan) once a welfare is <= 0
        pos = [x for x in self._pos if x == x]
        return {
            "mean_wait": cor.mean_wait(),
            "max_queue": self.max_queue,
            "stops_per_vehicle": stopped / arrived if arrived else 0.0,
            "jain_wait": jain_index(per_phase),
            "poa_cycle": mean(poa),
            "pos_cycle": mean(pos),
            "poa_defined": len(poa) / len(self._poa) if self._poa else None,
            "convergence_cycles": (max(done) if nodes and all(d is not None for d in done) else None),
            "offset_gap": cor.offset_spread(),
            "wave_cycle": self.wave_cycle,
            "vehicles": arrived,
        }


def run_experiment(scenario, rates, seed, duration=config.DURATION, kb=None, broker=None):
    """Run one scenario with one seed and return its metrics (a dict)."""
    rec = Recorder(make_corridor(scenario, rates, seed, kb=kb, broker=broker))
    for _ in range(duration):
        rec.step()
    return rec.summary()
