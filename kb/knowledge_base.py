"""KnowledgeBase: query interface used by the agents.

The facts live in the OWL ontology kb/traffic.owl; the rules ("emergency vehicle
approaching => priority green", "bus => heavier weight", "event => more arrivals")
are small functions over those facts. No reasoner is used (no Java needed).

Agents call:
    kb.weight(carrefour, phase)            -> float      utility weight w_k
    kb.arrival_factor(carrefour, phase, t) -> float      multiplier on lambda_k (events)
    kb.priority_rule(kind)                 -> dict|None  rule for "emergency" / "bus"
    kb.fallback_plan(carrefour)            -> dict       fixed-time plan {"avenue","side"}
    kb.active_events(t)                    -> list[dict]
    kb.constraints()                       -> dict       cycle, lost time, minimum green
"""
from pathlib import Path

from owlready2 import World

from kb.ontology import DEFAULT_PATH, build_ontology


class KnowledgeBase:
    def __init__(self, path=DEFAULT_PATH):
        path = Path(path)
        if not path.exists():
            build_ontology(path)
        self.world = World()                           # private world: no global state
        self.onto = self.world.get_ontology(path.resolve().as_uri()).load()

    # --- facts ----------------------------------------------------------------
    def _phase(self, carrefour, phase):
        individual = self.onto[f"{carrefour}_{phase}"]
        if individual is None:
            raise KeyError(f"unknown phase {carrefour}/{phase}")
        return individual

    def weight(self, carrefour, phase):
        return float(self._phase(carrefour, phase).has_weight)

    def has_bus_lane(self, carrefour, phase):
        return bool(self._phase(carrefour, phase).has_bus_lane)

    def fallback_plan(self, carrefour):
        for plan in self.onto.LightPlan.instances():
            if plan.plan_for.name == carrefour:
                return {"avenue": plan.green_avenue, "side": plan.green_side}
        raise KeyError(f"no light plan for {carrefour}")

    def constraints(self):
        rules = self.onto["network_rules"]
        return {"cycle": rules.cycle_s, "lost_time": rules.lost_time_s,
                "min_green": rules.min_green_s}

    # --- rules ----------------------------------------------------------------
    def priority_rule(self, kind):
        """Rule for a vehicle kind ("emergency", "bus"); None when no priority."""
        for rule in self.onto.PriorityRule.instances():
            if rule.vehicle_kind == kind:
                return {"kind": kind, "level": rule.priority_level,
                        "action": rule.action, "weight_factor": rule.weight_factor}
        return None

    def active_events(self, t):
        events = []
        for ev in self.onto.Event.instances():
            if ev.start_s <= t < ev.end_s:
                events.append({"name": ev.name, "type": type(ev).__name__,
                               "carrefour": ev.affects_phase.belongs_to.name,
                               "phase": ev.affects_phase.direction,
                               "factor": ev.arrival_factor})
        return events

    def arrival_factor(self, carrefour, phase, t):
        """Product of the factors of the events active at time t on this phase."""
        factor = 1.0
        for ev in self.active_events(t):
            if ev["carrefour"] == carrefour and ev["phase"] == phase:
                factor *= ev["factor"]
        return factor
