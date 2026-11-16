"""In-process MQTT broker with the same interface as sim.mqtt_client.MqttClient.

Used for fast, deterministic runs and tests (no network). Messages are serialised to
JSON and parsed back, so the message format is exercised exactly like on a real broker.
Supports wildcards, retained messages and the Last Will and Testament. Delivery is synchronous.
The real-broker experiments use sim.mqtt_client.MqttClient instead.

Status protocol (same as MqttClient): connect() publishes "online" (retained) on
sma/agent/{id}/statut; disconnect() publishes "offline" itself; crash() drops the client without
a goodbye and the broker publishes the Will ("offline", retained). A real Mosquitto fires the Will
about 1.5 x keepalive after the crash; here it is immediate.
A dead client publishes nothing and receives nothing; its subscriptions survive a reconnection.
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
        """A new client, already connected (it announces itself as online)."""
        c = LoopbackClient(self, agent_id)
        self.clients.append(c)
        c.connect()
        return c

    def route(self, topic, payload, retain, kind):
        self.log.append((topic, kind))
        if retain:
            self.retained[topic] = payload
        for client in list(self.clients):
            if not client.alive:
                continue
            for pattern, callback in list(client.subs):
                if topic_matches(pattern, topic):
                    callback(topic, Message.from_json(payload))


class LoopbackClient:
    def __init__(self, broker, agent_id):
        self.broker, self.agent_id = broker, agent_id
        self.subs = []
        self.alive = False

    def _announce(self, state):
        message = Message(source=self.agent_id, valeur=state, unite="status")
        self.broker.route(topics.agent_status(self.agent_id), message.to_json(),
                          topics.RETAINED["status"], "status")

    def connect(self, timeout=5):
        """(Re)connect: announce online, then receive the retained messages again."""
        self.alive = True
        self._announce(topics.STATUS_ONLINE)
        for pattern, callback in list(self.subs):
            self._replay_retained(pattern, callback)

    def disconnect(self):
        """Clean disconnection: the client announces offline itself."""
        if self.alive:
            self._announce(topics.STATUS_OFFLINE)
            self.alive = False

    def crash(self):
        """Dropped without a goodbye: the broker publishes the Last Will."""
        if self.alive:
            self.alive = False
            self._announce(topics.STATUS_OFFLINE)       # published by the broker, not by the client

    def publish(self, topic, message, kind):
        if self.alive:
            self.broker.route(topic, message.to_json(), topics.RETAINED[kind], kind)

    def subscribe(self, pattern, callback, kind="queue"):
        self.subs.append((pattern, callback))
        if self.alive:
            self._replay_retained(pattern, callback)

    def _replay_retained(self, pattern, callback):
        for topic, payload in list(self.broker.retained.items()):
            if topic_matches(pattern, topic):
                callback(topic, Message.from_json(payload))
