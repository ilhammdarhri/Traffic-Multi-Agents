"""In-process MQTT broker with the same interface as sim.mqtt_client.MqttClient.

Used for fast, deterministic runs and tests (no network). Messages are serialised to
JSON and parsed back, so the message format is exercised exactly like on a real broker.
Supports wildcards and retained messages. Delivery is synchronous.
The real-broker experiments use sim.mqtt_client.MqttClient instead.
"""
from sim import topics
from sim.message import Message
from sim.mqtt_client import topic_matches


class LoopbackBroker:
    def __init__(self):
        self.clients = []
        self.retained = {}                  # topic -> JSON payload
        self.log = []                       # (topic, kind) of every publication

    def client(self, agent_id):
        c = LoopbackClient(self, agent_id)
        self.clients.append(c)
        return c

    def route(self, topic, payload, retain, kind):
        self.log.append((topic, kind))
        if retain:
            self.retained[topic] = payload
        for client in list(self.clients):
            for pattern, callback in list(client.subs):
                if topic_matches(pattern, topic):
                    callback(topic, Message.from_json(payload))


class LoopbackClient:
    def __init__(self, broker, agent_id):
        self.broker, self.agent_id = broker, agent_id
        self.subs = []

    def connect(self, timeout=5):
        pass

    def disconnect(self):
        pass

    def publish(self, topic, message, kind):
        self.broker.route(topic, message.to_json(), topics.RETAINED[kind], kind)

    def subscribe(self, pattern, callback, kind="queue"):
        self.subs.append((pattern, callback))
        for topic, payload in list(self.broker.retained.items()):    # retained replay
            if topic_matches(pattern, topic):
                callback(topic, Message.from_json(payload))
