"""Builds the traffic ontology (OWL, Owlready2) and saves it to kb/traffic.owl.

Run:  python -m kb.ontology          (regenerates kb/traffic.owl)

Taxonomy
    Thing
    |- Intersection          carrefour1..3
    |- Phase                 carrefourN_avenue / carrefourN_side
    |- Vehicle
    |   |- EmergencyVehicle
    |   `- Bus
    |- Event
    |   |- SchoolExit
    |   |- Match
    |   `- RushHour
    |- PriorityRule          what to do for each kind of vehicle
    |- LightPlan             default (fixed-time) green plan of an intersection
    `- NetworkRules          global constraints (cycle, lost time, minimum green)
"""
from pathlib import Path

from owlready2 import (DataProperty, FunctionalProperty, ObjectProperty, Thing, World)

from sim import config

IRI = "http://example.org/traffic-sma.owl"
DEFAULT_PATH = Path(__file__).with_name("traffic.owl")
CARREFOURS = [f"carrefour{i}" for i in range(1, config.N_INTERSECTIONS + 1)]
BUS_LANE_PHASES = {"carrefour2_side"}            # phases that carry a bus line


def build_ontology(path=DEFAULT_PATH):
    world = World()
    onto = world.get_ontology(IRI)

    with onto:
        # --- classes ------------------------------------------------------
        class Intersection(Thing): pass
        class Phase(Thing): pass
        class Vehicle(Thing): pass
        class EmergencyVehicle(Vehicle): pass
        class Bus(Vehicle): pass
        class Event(Thing): pass
        class SchoolExit(Event): pass
        class Match(Event): pass
        class RushHour(Event): pass
        class PriorityRule(Thing): pass
        class LightPlan(Thing): pass
        class NetworkRules(Thing): pass

        # --- object properties --------------------------------------------
        class belongs_to(ObjectProperty, FunctionalProperty):
            domain, range = [Phase], [Intersection]

        class affects_phase(ObjectProperty, FunctionalProperty):
            domain, range = [Event], [Phase]

        class plan_for(ObjectProperty, FunctionalProperty):
            domain, range = [LightPlan], [Intersection]

        # --- data properties ----------------------------------------------
        class direction(DataProperty, FunctionalProperty):
            domain, range = [Phase], [str]

        class has_bus_lane(DataProperty, FunctionalProperty):
            domain, range = [Phase], [bool]

        class has_weight(DataProperty, FunctionalProperty):
            domain, range = [Phase], [float]

        class start_s(DataProperty, FunctionalProperty):
            domain, range = [Event], [int]

        class end_s(DataProperty, FunctionalProperty):
            domain, range = [Event], [int]

        class arrival_factor(DataProperty, FunctionalProperty):
            domain, range = [Event], [float]

        class vehicle_kind(DataProperty, FunctionalProperty):
            domain, range = [PriorityRule], [str]

        class priority_level(DataProperty, FunctionalProperty):
            domain, range = [PriorityRule], [int]

        class action(DataProperty, FunctionalProperty):
            domain, range = [PriorityRule], [str]          # "preempt" | "boost_weight"

        class weight_factor(DataProperty, FunctionalProperty):
            domain, range = [PriorityRule], [float]

        class green_avenue(DataProperty, FunctionalProperty):
            domain, range = [LightPlan], [int]

        class green_side(DataProperty, FunctionalProperty):
            domain, range = [LightPlan], [int]

        class cycle_s(DataProperty, FunctionalProperty):
            domain, range = [NetworkRules], [int]

        class lost_time_s(DataProperty, FunctionalProperty):
            domain, range = [NetworkRules], [int]

        class min_green_s(DataProperty, FunctionalProperty):
            domain, range = [NetworkRules], [int]

        # --- individuals: intersections, phases, default plans ------------
        for c in CARREFOURS:
            inter = Intersection(c)
            for d in ("avenue", "side"):
                p = Phase(f"{c}_{d}")
                p.belongs_to = inter
                p.direction = d
                p.has_bus_lane = p.name in BUS_LANE_PHASES
                p.has_weight = float(config.WEIGHTS["bus"] if p.has_bus_lane
                                     else config.WEIGHTS["default"])
            plan = LightPlan(f"plan_{c}")                # fixed-time fallback plan
            plan.plan_for = inter
            plan.green_avenue, plan.green_side = 50, config.GREEN_BUDGET - 50

        # --- individuals: events (simulation seconds) ---------------------
        e = SchoolExit("school_exit_c2")
        e.affects_phase, e.start_s, e.end_s, e.arrival_factor = (
            onto["carrefour2_side"], 1800, 2400, 2.0)
        e = Match("match_c1")
        e.affects_phase, e.start_s, e.end_s, e.arrival_factor = (
            onto["carrefour1_avenue"], 2700, 3300, 1.5)
        e = RushHour("rush_c3")
        e.affects_phase, e.start_s, e.end_s, e.arrival_factor = (
            onto["carrefour3_avenue"], 600, 1500, 1.3)

        # --- individuals: priority rules ----------------------------------
        r = PriorityRule("rule_emergency")
        r.vehicle_kind, r.priority_level, r.action, r.weight_factor = "emergency", 2, "preempt", 1.0
        r = PriorityRule("rule_bus")
        r.vehicle_kind, r.priority_level, r.action, r.weight_factor = (
            "bus", 1, "boost_weight", float(config.WEIGHTS["bus"]))

        # --- individual: global rules -------------------------------------
        n = NetworkRules("network_rules")
        n.cycle_s, n.lost_time_s, n.min_green_s = config.CYCLE, config.LOST_TIME, config.G_MIN

    onto.save(file=str(path), format="rdfxml")
    return path


if __name__ == "__main__":
    print("written:", build_ontology())
