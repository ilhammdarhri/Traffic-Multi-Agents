"""Run a corridor through a REAL MQTT broker (Mosquitto) instead of the in-process loopback.

RealBroker has the same interface as sim.loopback.LoopbackBroker (client(id), log), plus
settle(): the simulation is a lockstep one, so before an agent decides, its sensor messages must
have arrived, and before the clock moves on the plans must have reached the actuators. settle()
is that barrier: two echo round trips through the broker for every client (first so that every
publication has been routed, then so that every delivery has been made).
With it a run over the real broker gives exactly the same results as the loopback run.
"""
import time
import uuid

from sim.mqtt_client import MqttClient


class _CountingClient(MqttClient):
    def __init__(self, broker, agent_id, **kw):
        super().__init__(agent_id, **kw)
        self._broker = broker

    def publish(self, topic, message, kind):
        self._broker.log.append((topic, kind))
        return super().publish(topic, message, kind)


class RealBroker:
    def __init__(self, host="localhost", port=1883, clean=True, pace=0.1):
        self.host, self.port, self.pace = host, port, pace   # pace: pause between two connections
        self.clients = []
        self.run_id = uuid.uuid4().hex[:6]     # MQTT session ids are unique per run; agent ids and topics are not
        self.log = []                         # (topic, kind) of every publication (status excluded)
        if clean:
            self.clear_retained()

    def client(self, agent_id):
        c = _CountingClient(self, agent_id, host=self.host, port=self.port,
                            client_id=f"{agent_id}-{self.run_id}")
        c.connect()
        time.sleep(self.pace)                 # the light amqtt test broker races on simultaneous connects
        self.clients.append(c)
        return c

    def settle(self):
        for _ in range(2):
            for c in self.clients:
                c.ping_send()
            for c in self.clients:
                c.ping_wait()

    def clear_retained(self, wait=0.5):
        """Retained plans / states / statuses of an earlier run would be replayed to the new
        agents: delete them (publish an empty retained payload on each)."""
        seen = []
        probe = MqttClient("cleaner", host=self.host, port=self.port)
        probe._c.on_message = lambda cl, ud, msg: seen.append(msg.topic) if msg.retain else None
        probe._c.will_clear()
        probe.connect()
        probe._c.subscribe("traffic/#", 1)
        probe._c.subscribe("sma/agent/+/statut", 1)
        time.sleep(wait)
        for topic in set(seen):
            probe._c.publish(topic, b"", qos=1, retain=True)
        probe._c.disconnect()
        probe._c.loop_stop()

    def close(self):
        for c in self.clients:
            c.disconnect()
        self.clients = []
        time.sleep(0.3)
