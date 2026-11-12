"""Queue simulator for one signalised intersection (1 s time step).

Cycle layout for plan (g_avenue, g_side), offset o, cycle C, lost time l per phase:
    local = (t - o) mod C
    avenue green : 0 <= local < g_a
    all red      : g_a <= local < g_a + l
    side green   : g_a + l <= local < g_a + l + g_s
    all red      : the rest (l seconds)
A new plan only takes effect at the start of the next cycle.
"""
from collections import deque

import numpy as np

from sim import config

AVENUE, SIDE, RED = "avenue", "side", "red"


def validate_plan(plan):
    """plan = {"avenue": g_a, "side": g_s}. True if it respects the coupling
    constraint (sum = green budget) and the minimum green."""
    try:
        g_a, g_s = plan[AVENUE], plan[SIDE]
    except (KeyError, TypeError):
        return False
    return (g_a >= config.G_MIN and g_s >= config.G_MIN
            and abs((g_a + g_s) - config.GREEN_BUDGET) < 1e-9)


class PhaseQueue:
    """FIFO queue of one approach. Remembers each vehicle's arrival time."""

    def __init__(self, arrival_rate, rng, saturation=config.SATURATION_FLOW, q0=0):
        self.arrival_rate = arrival_rate
        self.rng = rng
        self.saturation = saturation
        self.queue = deque([0] * int(q0))       # initial vehicles arrived at t = 0
        self.arrived = int(q0)
        self.departed = 0
        self.waits = []                         # waiting time of each departed vehicle
        self._credit = 0.0                      # fractional discharge capacity

    def __len__(self):
        return len(self.queue)

    def step(self, t, green):
        n = int(self.rng.poisson(self.arrival_rate))
        self.queue.extend([t] * n)
        self.arrived += n
        if not green:
            self._credit = 0.0
            return
        self._credit += self.saturation
        while self._credit >= 1.0 and self.queue:
            self.waits.append(t - self.queue.popleft())
            self.departed += 1
            self._credit -= 1.0
        self._credit = min(self._credit, 1.0)

    def total_wait(self, t):
        """Waiting time summed over departed vehicles and those still queued."""
        return sum(self.waits) + sum(t - a for a in self.queue)


class IntersectionSim:
    def __init__(self, carrefour, arrival_rates, offset=0, plan=None, seed=0, q0=config.INITIAL_QUEUE):
        self.carrefour = carrefour
        self.offset = offset
        self.cycle = config.CYCLE
        self.lost = config.LOST_PER_PHASE
        half = config.GREEN_BUDGET // 2
        self.plan = dict(plan) if plan else {AVENUE: half, SIDE: config.GREEN_BUDGET - half}
        if not validate_plan(self.plan):
            raise ValueError(f"invalid plan {self.plan}")
        self._pending = None
        self.t = 0
        rng = np.random.default_rng(seed)
        self.phases = {name: PhaseQueue(arrival_rates[name], rng, q0=q0) for name in (AVENUE, SIDE)}

    # --- control ----------------------------------------------------------
    def set_plan(self, plan):
        """Queue a new plan for the next cycle start. Returns False if invalid."""
        if not validate_plan(plan):
            return False
        self._pending = {AVENUE: plan[AVENUE], SIDE: plan[SIDE]}
        return True

    def set_offset(self, offset):
        self.offset = offset

    # --- state ------------------------------------------------------------
    def local_time(self):
        return (self.t - self.offset) % self.cycle

    def current_signal(self):
        local, g_a, g_s = self.local_time(), self.plan[AVENUE], self.plan[SIDE]
        if local < g_a:
            return AVENUE
        if g_a + self.lost <= local < g_a + self.lost + g_s:
            return SIDE
        return RED

    def queue_lengths(self):
        return {name: len(p) for name, p in self.phases.items()}

    # --- dynamics ---------------------------------------------------------
    def step(self):
        """Simulate second self.t, then advance the clock by 1 s."""
        signal = self.current_signal()
        for name, phase in self.phases.items():
            phase.step(self.t, green=(signal == name))
        self.t += 1
        if self._pending and self.local_time() == 0:       # new cycle starts
            self.plan, self._pending = self._pending, None

    def run(self, seconds):
        for _ in range(seconds):
            self.step()
