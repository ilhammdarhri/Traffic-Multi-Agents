"""Corridor: N intersections along the avenue, wired through an MQTT-like broker.

Per intersection: IntersectionSim + 2 ApproachAgents + IntersectionAgent + Actuator.
Every simulated second:
    1. actuators report the displayed phase,
    2. DECISION_LEAD seconds before the end of its cycle (last all-red) each intersection agent
       measures, publishes the plan for the next cycle and runs one consensus iteration,
    3. vehicle agents see the signals and move/request/pass,
    4. platoon vehicles scheduled to reach an intersection are added to its avenue queue,
    5. the queue simulators advance by 1 s,
    6. vehicles that left an intersection on the avenue are sent to the next one (TRAVEL_TIME later).
"""
import copy
from collections import defaultdict

from agents.approach import ApproachAgent
from agents.intersection import IntersectionAgent
from coordination.consensus import wrap
from coordination.strategies import CoordinationStrategy, resolve_strategy
from sim import config
from sim.devices import Actuator
from sim.loopback import LoopbackBroker
from sim.traffic import AVENUE, IntersectionSim

DECISION_LEAD = config.LOST_PER_PHASE        # decide at the start of the last all-red (5 s before the end)


def fresh_strategy(strategy):
    """One strategy instance per agent (a strategy may keep per-agent state)."""
    if isinstance(strategy, CoordinationStrategy):
        return copy.deepcopy(strategy)
    return resolve_strategy(strategy)


class Corridor:
    def __init__(self, rates=None, offsets=None, seed=0, kb=None, broker=None, strategy=None,
                 platoon=config.PLATOON_FRACTION):
        self.rates = rates or config.ARRIVALS["normal"]
        n = config.N_INTERSECTIONS
        offsets = list(offsets) if offsets is not None else [0] * n
        self.platoon = platoon                    # share of avenue departures reaching the next intersection
        self.broker = broker or LoopbackBroker()
        self.carrefours = [f"carrefour{i}" for i in range(1, n + 1)]
        self.sims, self.approaches, self.agents, self.actuators = {}, {}, {}, {}
        for i, c in enumerate(self.carrefours):
            neighbors = {self.carrefours[j]: j for j in (i - 1, i + 1) if 0 <= j < n}
            rates_i = dict(self.rates)
            if i > 0:                             # the rest of the avenue flow comes from upstream
                rates_i[AVENUE] = (1 - platoon) * self.rates[AVENUE]
            sim = IntersectionSim(c, rates_i, offset=offsets[i], seed=seed + i)
            self.sims[c] = sim
            self.approaches[c] = [
                ApproachAgent(c, p, (lambda p=p, sim=sim: len(sim.phases[p])), self.broker.client(f"aa-{c}-{p}"))
                for p in (sim.phases)]
            self.agents[c] = IntersectionAgent(
                c, self.broker.client(f"ia-{c}"), arrival_rates=self.rates, kb=kb,
                strategy=fresh_strategy(strategy), position=i, offset=offsets[i], neighbors=neighbors)
            fallback = config.FALLBACK_PLAN
            if kb is not None:
                try:
                    fallback = kb.fallback_plan(c)
                except KeyError:
                    pass
            self.actuators[c] = Actuator(c, sim, self.broker.client(f"act-{c}"), fallback_plan=fallback)
        self._inflight = [defaultdict(int) for _ in range(n)]   # per intersection: arrival time -> vehicles
        self._carry = [0.0] * n                   # fractional vehicles kept between two seconds
        self.vehicles = []                        # (start_time, agent)
        self.t = 0

    def add_vehicle(self, vehicle, start_t=0):
        self.vehicles.append((start_t, vehicle))
        return vehicle

    def _settle(self):
        settle = getattr(self.broker, "settle", None)
        if settle:
            settle()

    # --- failures ------------------------------------------------------------
    def crash_agent(self, c):
        """The intersection agent dies without a goodbye (Last Will); its controller keeps cycling."""
        self.agents[c].mqtt.crash()

    def crash_sensor(self, c, direction):
        """One loop detector stops publishing."""
        for aa in self.approaches[c]:
            if aa.direction == direction:
                aa.mqtt.crash()

    def recover_agent(self, c):
        """The agent restarts: reconnects and resynchronises its offset with the real controller."""
        agent = self.agents[c]
        agent.mqtt.connect()
        agent.offset = self.sims[c].offset % config.CYCLE

    def step(self):
        t = self.t
        for act in self.actuators.values():
            act.tick()
        for c in self.carrefours:
            if (self.sims[c].cycle_remaining() == DECISION_LEAD
                    and getattr(self.agents[c].mqtt, "alive", True)):
                for aa in self.approaches[c]:
                    aa.sense()
                self._settle()                  # real broker: measures delivered before deciding
                self.agents[c].decide_cycle(t)
                self._settle()                  # ... and plans / offsets delivered before moving on
        signals = {c: self.sims[c].current_signal() for c in self.carrefours}
        for start_t, v in self.vehicles:
            if t >= start_t and not v.done:
                v.step({"t": t, "signals": signals})
        for i, c in enumerate(self.carrefours):          # platoon vehicles reaching the stop line now
            arriving = self._inflight[i].pop(t, 0)
            if arriving:
                self.sims[c].phases[AVENUE].inject(t, arriving)
        for sim in self.sims.values():
            sim.step()
        for i, c in enumerate(self.carrefours[:-1]):     # departures travel to the next intersection
            left = self.sims[c].phases[AVENUE].last_departed
            self._carry[i] += self.platoon * left
            through = int(self._carry[i] + 1e-9)
            self._carry[i] -= through
            if through:
                self._inflight[i + 1][t + config.TRAVEL_TIME] += through
        self.t += 1

    def run(self, seconds):
        for _ in range(seconds):
            self.step()

    # --- metrics ------------------------------------------------------------------
    def mean_wait(self):
        """Mean waiting time (s) of all vehicles that arrived so far, queued ones included."""
        waits = sum(p.total_wait(self.t) for s in self.sims.values() for p in s.phases.values())
        arrived = sum(p.arrived for s in self.sims.values() for p in s.phases.values())
        return waits / arrived if arrived else 0.0

    def offset_spread(self):
        """Distance (s) from a perfect green wave: the largest circular gap between the aligned
        offsets a_i = offset_i - i * T of two intersections (0 = perfect wave)."""
        aligned = [self.sims[c].offset - i * config.TRAVEL_TIME for i, c in enumerate(self.carrefours)]
        return max(abs(wrap(a - b, config.CYCLE)) for a in aligned for b in aligned)
