"""IoT devices: Sensor (publishes measures) and Actuator (applies commands).

Both talk only through MQTT; they never call agents directly.
"""
from sim import topics
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
    """Traffic light controller: applies green plans received on signal/plan and
    reports the phase really displayed on signal/etat (retained)."""

    def __init__(self, carrefour, intersection, mqtt):
        self.carrefour = carrefour
        self.intersection = intersection
        self.mqtt = mqtt
        self.source = f"actuator-{carrefour}"
        self.rejected = 0                   # invalid plans received
        self._last_state = None
        mqtt.subscribe(topics.signal_plan(carrefour), self._on_plan, kind="plan")

    def _on_plan(self, topic, message):
        if not self.intersection.set_plan(message.valeur):
            self.rejected += 1              # safety: never apply an invalid plan

    def tick(self):
        """Call once per simulated second; publishes only when the display changes."""
        state = self.intersection.current_signal()
        if state != self._last_state:
            self._last_state = state
            msg = Message(source=self.source, valeur=state, unite="phase")
            self.mqtt.publish(topics.signal_etat(self.carrefour), msg, "etat")
            return msg
        return None
