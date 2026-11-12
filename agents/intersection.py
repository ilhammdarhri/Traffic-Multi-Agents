"""IntersectionAgent: chooses the green split of one intersection.

Every cycle it observes the queues published by the ApproachAgents, forecasts with
the utility model, and picks the split (g_avenue, g_side) maximising the summed
utility under the coupling constraint  g_avenue + g_side = GREEN_BUDGET,  g_k >= G_MIN.
The plan is published on traffic/{carrefour}/signal/plan (QoS 1, retained).

Knowledge base (optional) supplies:
  - the phase weights w_k                       kb.weight(...)
  - event forecasts (lambda_k x event factor)   kb.arrival_factor(...)
  - priority rules for requests on traffic/priority/request:
        "preempt"      (emergency vehicle) -> immediate command on signal/preempt
        "boost_weight" (bus)               -> heavier weight in the next decision only
Without a knowledge base, priority requests are ignored.

Ties (the utility is flat when both queues stay positive) are broken in favour of
the split closest to proportional to the green each phase needs.
"""
from agents.base import UtilityAgent
from agents.utility import UtilityFunction
from sim import config, topics
from sim.message import Message
from sim.traffic import AVENUE, SIDE

PHASES = (AVENUE, SIDE)
EMERGENCY_MARGIN_S = 2          # green is shown this long before the vehicle arrives
EMERGENCY_HOLD_S = 6            # and kept this long after its expected arrival


class IntersectionAgent(UtilityAgent):
    def __init__(self, carrefour, mqtt, arrival_rates=None, weights=None, kb=None, agent_id=None):
        super().__init__(agent_id or f"ia-{carrefour}", mqtt=mqtt, kb=kb)
        self.carrefour = carrefour
        self.arrival_rates = dict(arrival_rates or config.ARRIVALS["normal"])
        self.weights = dict(weights or {})          # explicit overrides {phase: w}
        self.queues = {}                            # latest measure per direction
        self.now = 0                                # simulation time, for event forecasts
        self._boosts = {}                           # phase -> weight announced by a bus
        self.preemptions = []                       # log of preemption commands sent
        self.state = {"queues": {}, "functions": {}}
        mqtt.subscribe(topics.queue(carrefour, "+"), self._on_queue, kind="queue")
        mqtt.subscribe(topics.PRIORITY_REQUEST, self._on_priority, kind="priority")

    # --- perception -------------------------------------------------------
    def _on_queue(self, topic, message):
        direction = topic.split("/")[3]
        if direction in PHASES:
            self.queues[direction] = message.valeur

    def _on_priority(self, topic, message):
        v = message.valeur
        if self.kb is None or not isinstance(v, dict) or v.get("carrefour") != self.carrefour:
            return
        phase, rule = v.get("phase"), self.kb.priority_rule(v.get("kind"))
        if phase not in PHASES or rule is None:
            return
        if rule["action"] == "preempt":
            self._preempt(phase, v.get("eta_s", 0))
        elif rule["action"] == "boost_weight":
            self._boosts[phase] = max(self._boosts.get(phase, 1.0), rule["weight_factor"])

    def _preempt(self, phase, eta_s):
        """Rule: emergency vehicle approaching => priority green on its phase, timed so
        that green appears just before it arrives (disturbs the others as little as possible)."""
        lead = config.LOST_PER_PHASE + EMERGENCY_MARGIN_S
        command = {"phase": phase,
                   "delay_s": max(0, int(round(eta_s)) - lead),
                   "duration_s": lead + EMERGENCY_HOLD_S}
        self.preemptions.append(dict(command, at=self.now))
        msg = Message(source=self.agent_id, valeur=command, unite="s")
        self.mqtt.publish(topics.signal_preempt(self.carrefour), msg, "preempt")

    # --- model ------------------------------------------------------------
    def weight(self, phase):
        if phase in self.weights:
            base = self.weights[phase]
        elif self.kb is not None:
            base = self.kb.weight(self.carrefour, phase)
        else:
            base = config.WEIGHTS["default"]
        boost = self._boosts.get(phase)
        return max(base, boost) if boost else base

    def forecast(self, phase):
        """lambda_k: nominal rate times the factor of the events active now."""
        rate = self.arrival_rates[phase]
        if self.kb is not None:
            rate *= self.kb.arrival_factor(self.carrefour, phase, self.now)
        return rate

    def set_forecast(self, arrival_rates):
        self.arrival_rates = dict(arrival_rates)

    def update_state(self, observation):
        """S_t: measured queues and the utility function of each phase."""
        queues = {p: observation.get(p, 0) for p in PHASES}
        self.state = {
            "queues": queues,
            "functions": {p: UtilityFunction(weight=self.weight(p),
                                             arrival_rate=self.forecast(p),
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

    def decide_cycle(self, t=None):
        """One decision cycle from the latest received queue measures."""
        if t is not None:
            self.now = t
        action = self.step(dict(self.queues))
        self._boosts.clear()                        # a bus announcement lasts one decision
        return action
