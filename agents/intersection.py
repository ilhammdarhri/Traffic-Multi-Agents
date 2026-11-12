"""IntersectionAgent: chooses the green split of one intersection.

Observes the queues published by the ApproachAgents, forecasts with the utility
model, and picks the split (g_avenue, g_side) maximising the summed utility
under the coupling constraint  g_avenue + g_side = GREEN_BUDGET,  g_k >= G_MIN.
The chosen plan is published on traffic/{carrefour}/signal/plan (QoS 1, retained).

Arrival rates are forecasts (lambda_k); the queues Q0_k are measured.
Ties (the utility is flat when both queues stay positive) are broken in favour of
the split closest to proportional to the green each phase needs.
"""
from agents.base import UtilityAgent
from agents.utility import UtilityFunction
from sim import config, topics
from sim.message import Message
from sim.traffic import AVENUE, SIDE

PHASES = (AVENUE, SIDE)


class IntersectionAgent(UtilityAgent):
    def __init__(self, carrefour, mqtt, arrival_rates=None, weights=None, kb=None, agent_id=None):
        super().__init__(agent_id or f"ia-{carrefour}", mqtt=mqtt, kb=kb)
        self.carrefour = carrefour
        self.arrival_rates = dict(arrival_rates or config.ARRIVALS["normal"])
        self.weights = dict(weights or {})          # explicit overrides {phase: w}
        self.queues = {}                            # latest measure per direction
        self.state = {"queues": {}, "functions": {}}
        mqtt.subscribe(topics.queue(carrefour, "+"), self._on_queue, kind="queue")

    # --- perception -------------------------------------------------------
    def _on_queue(self, topic, message):
        direction = topic.split("/")[3]
        if direction in PHASES:
            self.queues[direction] = message.valeur

    def weight(self, phase):
        if phase in self.weights:
            return self.weights[phase]
        if self.kb is not None:
            return self.kb.weight(self.carrefour, phase)
        return config.WEIGHTS["default"]

    def set_forecast(self, arrival_rates):
        self.arrival_rates = dict(arrival_rates)

    def update_state(self, observation):
        """S_t: measured queues and the utility function of each phase."""
        queues = {p: observation.get(p, 0) for p in PHASES}
        self.state = {
            "queues": queues,
            "functions": {p: UtilityFunction(weight=self.weight(p),
                                             arrival_rate=self.arrival_rates[p],
                                             q0=queues[p]) for p in PHASES},
        }

    # --- decision ---------------------------------------------------------
    def _proportional_target(self):
        fa, fs = (self.state["functions"][p] for p in PHASES)
        need = fa.required_green() + fs.required_green()
        share = fa.required_green() / need if need > 0 else 0.5
        return config.GREEN_BUDGET * share

    def feasible_actions(self):
        total, gmin = config.GREEN_BUDGET, config.G_MIN
        target = self._proportional_target()
        actions = [(ga, total - ga) for ga in range(gmin, total - gmin + 1)]
        return sorted(actions, key=lambda a: (abs(a[0] - target), a[0]))

    def utility(self, action):
        return sum(self.state["functions"][p](g) for p, g in zip(PHASES, action))

    def act(self, action):
        plan = {AVENUE: action[0], SIDE: action[1]}
        msg = Message(source=self.agent_id, valeur=plan, unite="s")
        self.mqtt.publish(topics.signal_plan(self.carrefour), msg, "plan")

    def decide_cycle(self):
        """One decision cycle from the latest received queue measures."""
        return self.step(dict(self.queues))
