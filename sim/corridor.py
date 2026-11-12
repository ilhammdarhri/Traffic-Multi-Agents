"""Corridor: N intersections along the avenue, wired through an MQTT-like broker.

Per intersection: IntersectionSim + 2 ApproachAgents + IntersectionAgent + Actuator.
Every simulated second:
    1. actuators report the displayed phase,
    2. at local time DECISION_AT of its cycle (last red) each intersection agent measures
       and publishes the plan for the next cycle,
    3. vehicle agents see the signals and move/request/pass,
    4. the queue simulators advance by 1 s.
"""
from agents.approach import ApproachAgent
from agents.intersection import IntersectionAgent
from sim import config
from sim.devices import Actuator
from sim.loopback import LoopbackBroker
from sim.traffic import AVENUE, SIDE, IntersectionSim

DECISION_AT = 85


class Corridor:
    def __init__(self, rates=None, offsets=None, seed=0, kb=None, broker=None):
        self.rates = rates or config.ARRIVALS["normal"]
        n = config.N_INTERSECTIONS
        offsets = offsets or [0] * n
        self.broker = broker or LoopbackBroker()
        self.carrefours = [f"carrefour{i}" for i in range(1, n + 1)]
        self.sims, self.approaches, self.agents, self.actuators = {}, {}, {}, {}
        for i, c in enumerate(self.carrefours):
            sim = IntersectionSim(c, self.rates, offset=offsets[i], seed=seed + i)
            self.sims[c] = sim
            self.approaches[c] = [
                ApproachAgent(c, p, (lambda p=p, sim=sim: len(sim.phases[p])), self.broker.client(f"aa-{c}-{p}"))
                for p in (AVENUE, SIDE)]
            self.agents[c] = IntersectionAgent(c, self.broker.client(f"ia-{c}"),
                                               arrival_rates=self.rates, kb=kb)
            self.actuators[c] = Actuator(c, sim, self.broker.client(f"act-{c}"))
        self.vehicles = []                 # (start_time, agent)
        self.t = 0

    def add_vehicle(self, vehicle, start_t=0):
        self.vehicles.append((start_t, vehicle))
        return vehicle

    def step(self):
        t = self.t
        for act in self.actuators.values():
            act.tick()
        for c in self.carrefours:
            if self.sims[c].local_time() == DECISION_AT:
                for aa in self.approaches[c]:
                    aa.sense()
                self.agents[c].decide_cycle(t)
        signals = {c: self.sims[c].current_signal() for c in self.carrefours}
        for start_t, v in self.vehicles:
            if t >= start_t and not v.done:
                v.step({"t": t, "signals": signals})
        for sim in self.sims.values():
            sim.step()
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
