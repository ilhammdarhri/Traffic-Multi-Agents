import pytest

from kb.knowledge_base import KnowledgeBase
from kb.ontology import build_ontology
from sim import config
from sim.traffic import validate_plan


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    path = build_ontology(tmp_path_factory.mktemp("kb") / "traffic.owl")
    return KnowledgeBase(path)


def test_ontology_taxonomy(kb):
    assert issubclass(kb.onto.EmergencyVehicle, kb.onto.Vehicle)
    assert issubclass(kb.onto.Bus, kb.onto.Vehicle)
    assert issubclass(kb.onto.SchoolExit, kb.onto.Event)
    assert len(list(kb.onto.Phase.instances())) == 2 * config.N_INTERSECTIONS


def test_phase_weights(kb):
    assert kb.weight("carrefour1", "avenue") == config.WEIGHTS["default"]
    assert kb.weight("carrefour2", "side") == config.WEIGHTS["bus"]       # bus lane
    assert kb.has_bus_lane("carrefour2", "side") and not kb.has_bus_lane("carrefour2", "avenue")
    with pytest.raises(KeyError):
        kb.weight("carrefour9", "avenue")


def test_emergency_rule_is_preemption(kb):
    rule = kb.priority_rule("emergency")
    assert rule["action"] == "preempt" and rule["level"] == 2


def test_bus_rule_boosts_weight(kb):
    rule = kb.priority_rule("bus")
    assert rule["action"] == "boost_weight" and rule["weight_factor"] == config.WEIGHTS["bus"]
    assert rule["level"] < kb.priority_rule("emergency")["level"]


def test_unknown_vehicle_has_no_priority(kb):
    assert kb.priority_rule("car") is None


def test_events_active_only_in_their_window(kb):
    assert kb.active_events(0) == []
    names = [e["name"] for e in kb.active_events(2000)]
    assert names == ["school_exit_c2"]
    assert kb.arrival_factor("carrefour2", "side", 2000) == 2.0
    assert kb.arrival_factor("carrefour2", "side", 2400) == 1.0          # end is exclusive
    assert kb.arrival_factor("carrefour2", "avenue", 2000) == 1.0        # other phase
    assert kb.arrival_factor("carrefour1", "avenue", 3000) == 1.5


def test_fallback_plans_are_valid(kb):
    for i in range(1, config.N_INTERSECTIONS + 1):
        assert validate_plan(kb.fallback_plan(f"carrefour{i}"))


def test_constraints_match_config(kb):
    assert kb.constraints() == {"cycle": config.CYCLE, "lost_time": config.LOST_TIME,
                                "min_green": config.G_MIN}


def test_committed_owl_file_loads_and_is_in_sync():
    kb = KnowledgeBase()                      # kb/traffic.owl (built if missing)
    assert kb.weight("carrefour2", "side") == config.WEIGHTS["bus"]
    assert kb.priority_rule("emergency")["action"] == "preempt"


def test_intersection_agent_uses_kb_weights(kb):
    from agents.intersection import IntersectionAgent
    from tests.test_traffic_devices import FakeMqtt
    peak = config.ARRIVALS["peak"]
    plain = IntersectionAgent("carrefour1", FakeMqtt(), arrival_rates=peak, kb=kb)
    bus = IntersectionAgent("carrefour2", FakeMqtt(), arrival_rates=peak, kb=kb)   # bus lane on side phase
    for agent in (plain, bus):
        agent.update_state({"avenue": 5, "side": 5})
    assert plain.weight("side") == 1.0 and bus.weight("side") == 1.5
    assert bus.decide()[1] > plain.decide()[1]          # the bus phase gets more green
