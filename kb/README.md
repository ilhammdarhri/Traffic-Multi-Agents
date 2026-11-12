# Knowledge base (`kb/`)

Ontology in OWL (built with Owlready2) + a thin query layer.
No reasoner is used, so Java is **not** required.

| File | Role |
|------|------|
| `traffic.owl` | The ontology (RDF/XML). Open it in Protege to browse it. Generated, but committed. |
| `ontology.py` | Builds `traffic.owl`. Regenerate with `python -m kb.ontology`. |
| `knowledge_base.py` | `KnowledgeBase`: the query interface used by the agents. |

## Concepts

- **Intersection** (`carrefour1..3`), **Phase** (`carrefourN_avenue`, `carrefourN_side`) with
  `belongs_to`, `direction`, `has_bus_lane`, `has_weight` (the utility weight `w_k`).
- **Vehicle** > **EmergencyVehicle**, **Bus**.
- **Event** > **SchoolExit**, **Match**, **RushHour**, with `affects_phase`, `start_s`, `end_s`,
  `arrival_factor` (multiplier on the arrival rate during the event).
- **PriorityRule**: `vehicle_kind`, `priority_level`, `action`, `weight_factor`.
- **LightPlan**: fixed-time fallback plan of an intersection (`green_avenue`, `green_side`).
- **NetworkRules**: cycle, lost time, minimum green (same values as `sim/config.py`).

## Rules

| Rule | Where | Effect |
|------|-------|--------|
| Emergency vehicle approaching => priority green | `priority_rule("emergency")` -> `action = "preempt"`, level 2 | the intersection gives green to the vehicle's phase |
| Bus on a phase => heavier weight | `priority_rule("bus")` -> `"boost_weight"`, factor 1.5; phases with a bus lane have `has_weight = 1.5` | the phase attracts more green in the utility maximisation |
| Event active (school exit, match, rush hour) => more arrivals | `arrival_factor(carrefour, phase, t)` | `lambda_k` is multiplied by the factor |
| No data / consensus failure => fixed-time plan | `fallback_plan(carrefour)` | 50 s / 30 s |

## Query interface

```python
from kb.knowledge_base import KnowledgeBase
kb = KnowledgeBase()                           # loads kb/traffic.owl (builds it if missing)

kb.weight("carrefour2", "side")                # 1.5  (bus lane)
kb.arrival_factor("carrefour2", "side", 2000)  # 2.0  (school exit between 1800 s and 2400 s)
kb.priority_rule("emergency")                  # {'kind': 'emergency', 'level': 2, 'action': 'preempt', ...}
kb.fallback_plan("carrefour1")                 # {'avenue': 50, 'side': 30}
kb.active_events(2000)                         # [{'name': 'school_exit_c2', ...}]
kb.constraints()                               # {'cycle': 90, 'lost_time': 10, 'min_green': 10}
```

An `IntersectionAgent` receives a `KnowledgeBase` (`kb=`) and asks it for the weight of
each phase every decision cycle.

## Editing the knowledge

Change the facts in `ontology.py` (events, weights, plans, rules), run
`python -m kb.ontology`, and commit the new `traffic.owl`. Times are in simulation seconds.
