"""Distributed consensus on the offsets of neighbouring intersections (green wave).

Intersections sit along the avenue at positions i = 0, 1, 2, ... A platoon leaving
intersection i reaches i + 1 after T seconds, so the ideal offsets satisfy
    offset_{i+1} - offset_i = T   (mod C).
Define the aligned offset  a_i = (offset_i - i * T) mod C.  A green wave means that all a_i
are equal, so the agents run an average consensus on the a_i. Offsets live on a circle of
length C, hence differences are taken with wrap() (shortest signed arc).

One iteration per cycle, for the node i that knows the last a_j received from each neighbour j:
    delta_i = gain * sum_{j in N(i)} wrap(a_j - a_i)
    shift_i = round(clip(delta_i, -max_shift, +max_shift))     seconds, applied to the next cycle

Convergence  : |delta_i| < eps for `stable_rounds` consecutive iterations, once every neighbour
               has been heard (the node then reports `converged`).
Timeout      : if not converged after `max_iter` iterations the node freezes (`timed_out`):
               offsets stay where they are instead of drifting on stale data.
Failures     : when the Last Will of a neighbour says "offline" (mark_offline), its agent is down
               but its signal controller keeps cycling at its last offset. A neighbour that was
               heard stays in the average as a FIXED ANCHOR: the others align with it, so the green
               wave survives. A neighbour that was never heard cannot anchor anything: it no longer
               blocks the node (ready() ignores it). mark_online() restores it. forget() removes it.
This class is pure (no MQTT): ConsensusStrategy feeds it the messages.
"""
from sim import config


def wrap(x, period=config.CYCLE):
    """Shortest signed circular difference, in [-period/2, period/2)."""
    return (x + period / 2) % period - period / 2


class OffsetConsensus:
    def __init__(self, position, neighbors, travel_time=config.TRAVEL_TIME, cycle=config.CYCLE,
                 gain=config.CONSENSUS_GAIN, eps=config.CONSENSUS_EPS,
                 max_iter=config.CONSENSUS_MAX_ITER, max_shift=config.MAX_SHIFT, stable_rounds=2):
        self.position = position
        self.neighbors = dict(neighbors)          # {name: position along the avenue}
        self.travel_time, self.cycle = travel_time, cycle
        self.gain, self.eps = gain, eps
        self.max_iter, self.max_shift = max_iter, max_shift
        self.stable_rounds = stable_rounds
        self.aligned = {}                         # last a_j received from each neighbour
        self.offline = set()                      # neighbours whose Last Will said "offline"
        self.iteration = 0
        self.last_delta = 0.0
        self.converged = False
        self.converged_at = None                  # iteration at which convergence was detected
        self.timed_out = False
        self._stable = 0

    # --- inputs ---------------------------------------------------------------
    def align(self, offset, position):
        return (offset - position * self.travel_time) % self.cycle

    def receive(self, neighbor, offset):
        """Store the offset announced by a neighbour (ignored if it is not a neighbour)."""
        if neighbor in self.neighbors:
            self.aligned[neighbor] = self.align(offset, self.neighbors[neighbor])

    def forget(self, neighbor):
        """Drop a neighbour (e.g. it went offline): it no longer takes part in the average."""
        self.neighbors.pop(neighbor, None)
        self.aligned.pop(neighbor, None)
        self.offline.discard(neighbor)

    def mark_offline(self, neighbor):
        """The neighbour's agent is down (Last Will). Its last offset stays as a fixed anchor."""
        if neighbor in self.neighbors:
            self.offline.add(neighbor)

    def mark_online(self, neighbor):
        self.offline.discard(neighbor)

    def ready(self):
        """Every neighbour that is not known to be down has been heard."""
        return all(n in self.aligned for n in self.neighbors if n not in self.offline)

    # --- one iteration -----------------------------------------------------------
    def update(self, own_offset):
        """Run one iteration; return the shift (integer seconds) to apply next cycle."""
        self.iteration += 1
        if self.timed_out or not self.aligned or not self.ready():
            return 0                              # nothing (usable) heard yet: no decision, no "convergence"
        own = self.align(own_offset, self.position)
        delta = self.gain * sum(wrap(a - own, self.cycle) for a in self.aligned.values())
        self.last_delta = delta
        if abs(delta) < self.eps:
            self._stable += 1
            if self._stable >= self.stable_rounds and not self.converged:
                self.converged, self.converged_at = True, self.iteration
        else:
            self._stable, self.converged = 0, False
        if not self.converged and self.iteration >= self.max_iter:
            self.timed_out = True
            return 0
        return int(round(max(-self.max_shift, min(self.max_shift, delta))))
