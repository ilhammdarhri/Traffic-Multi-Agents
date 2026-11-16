"""IoT devices: Sensor (publishes measures) and Actuator (applies commands).

Both talk only through MQTT; they never call agents directly.
"""
from sim import config, topics
from sim.message import Message
from sim.traffic import validate_plan


class Sensor:
    """Inductive loop / camera on one approach: publishes the queue length."""

    def __init__(self, carrefour, direction, read_fn, mqtt):
        self.carrefour, self.direction = carrefour, direction
        self.read_fn = read_fn              # callable returning the current queue length
        self.mqtt = mqtt
        self.source = f"loop-{carrefour}-{direction}"

    def publish(self):
        msg = Message(source=self.source, valeur=int(self.read_fn()), unite="vehicules")
        self.mqtt.publish(topics.queue(self.carrefour, self.direction), msg, "queue")
        return msg


class Actuator:
    """Traffic light controller. Applies green plans received on signal/plan (next
    cycle) and preemption commands received on signal/preempt (immediately), and
    reports the phase really displayed on signal/etat (retained).

    Fail-safe: the controller keeps cycling on the last plan when its agent dies. If a
    `fallback_plan` is given and no valid plan arrives for `plan_timeout` seconds
    (default PLAN_TIMEOUT_CYCLES cycles), it switches to that fixed-time plan until a new
    plan arrives. The cycle length, hence the offset, is not touched."""

    def __init__(self, carrefour, intersection, mqtt, fallback_plan=None, plan_timeout=None):
        self.carrefour = carrefour
        self.intersection = intersection
        self.mqtt = mqtt
        self.source = f"actuator-{carrefour}"
        self.rejected = 0                   # invalid plans / commands received
        self.preemptions = 0                # preemption commands applied
        self.shifts = 0                     # offset shifts accepted
        self.fallback_plan = dict(fallback_plan) if fallback_plan else None
        self.plan_timeout = plan_timeout if plan_timeout is not None \
            else config.PLAN_TIMEOUT_CYCLES * config.CYCLE
        self.fallback_active = False
        self.fallbacks = 0                  # times the fixed-time plan was activated
        self._last_plan_t = intersection.t
        self._last_state = None
        mqtt.subscribe(topics.signal_plan(carrefour), self._on_plan, kind="plan")
        mqtt.subscribe(topics.signal_preempt(carrefour), self._on_preempt, kind="preempt")
        mqtt.subscribe(topics.signal_shift(carrefour), self._on_shift, kind="shift")

    def _on_shift(self, topic, message):
        v = message.valeur
        shift = v.get("shift_s") if isinstance(v, dict) else None
        if self.intersection.shift_next_cycle(shift):
            self.shifts += 1
        else:
            self.rejected += 1              # not an integer, or larger than MAX_SHIFT

    def _on_plan(self, topic, message):
        if self.intersection.set_plan(message.valeur):
            self._last_plan_t = self.intersection.t
            self.fallback_active = False
        else:
            self.rejected += 1              # safety: never apply an invalid plan

    def _on_preempt(self, topic, message):
        v = message.valeur
        try:
            ok = isinstance(v, dict) and self.intersection.preempt(
                v.get("phase"), v.get("duration_s", 0), v.get("delay_s", 0))
        except TypeError:
            ok = False
        if ok:
            self.preemptions += 1
        else:
            self.rejected += 1

    def tick(self):
        """Call once per simulated second; publishes only when the display changes."""
        if (self.fallback_plan and not self.fallback_active
                and self.intersection.t - self._last_plan_t >= self.plan_timeout
                and self.intersection.set_plan(self.fallback_plan)):
            self.fallback_active = True     # the agent is silent: fixed-time plan from the next cycle
            self.fallbacks += 1
        state = self.intersection.current_signal()
        if state != self._last_state:
            self._last_state = state
            msg = Message(source=self.source, valeur=state, unite="phase")
            self.mqtt.publish(topics.signal_etat(self.carrefour), msg, "etat")
            return msg
        return None
