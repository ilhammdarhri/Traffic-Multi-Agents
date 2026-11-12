"""Thin wrapper around paho-mqtt used by every agent, sensor and actuator.

Features: publish Message objects with the QoS/retained flags of sim.topics,
subscribe with per-pattern callbacks, online status + Last Will and Testament.
Works with paho-mqtt 1.x and 2.x.
"""
import threading

import paho.mqtt.client as mqtt

from sim import topics
from sim.message import Message


def topic_matches(pattern, topic):
    """MQTT wildcard matching: '+' = one level, '#' = all remaining levels."""
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t):
            return False
        if part != "+" and part != t[i]:
            return False
    return len(p) == len(t)


class MqttClient:
    def __init__(self, agent_id, host="localhost", port=1883, keepalive=10):
        self.agent_id = agent_id
        self.host, self.port, self.keepalive = host, port, keepalive
        self._subs = []                # list of (pattern, qos, callback)
        self._lock = threading.Lock()
        self._connected = threading.Event()

        if hasattr(mqtt, "CallbackAPIVersion"):
            self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=agent_id)
        else:
            self._c = mqtt.Client(client_id=agent_id)

        # Last Will: if this agent dies without a clean disconnect, the broker
        # publishes "offline" (retained) on its status topic.
        self._status_topic = topics.agent_status(agent_id)
        self._c.will_set(self._status_topic, self._status_payload(topics.STATUS_OFFLINE),
                         qos=topics.QOS["status"], retain=topics.RETAINED["status"])
        self._c.on_connect = self._on_connect
        self._c.on_message = self._on_message

    def _status_payload(self, state):
        return Message(source=self.agent_id, valeur=state, unite="status").to_json()

    # --- connection -------------------------------------------------------
    def connect(self, timeout=5):
        self._c.connect(self.host, self.port, self.keepalive)
        self._c.loop_start()
        if not self._connected.wait(timeout):
            raise ConnectionError(f"no broker answer on {self.host}:{self.port}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        # (re)subscribe after every (re)connection
        with self._lock:
            for pattern, qos, _ in self._subs:
                client.subscribe(pattern, qos)
        self.publish_status(topics.STATUS_ONLINE)
        self._connected.set()

    def disconnect(self):
        """Clean disconnect: announce offline ourselves (the Will is not sent)."""
        self.publish_status(topics.STATUS_OFFLINE)
        self._c.disconnect()
        self._c.loop_stop()

    def crash(self):
        """Simulate a crash: drop the socket without a clean DISCONNECT,
        so the broker fires the Last Will. Used by failure tests."""
        self._c.loop_stop()
        sock = self._c.socket()
        if sock is not None:
            sock.close()

    # --- publish / subscribe ----------------------------------------------
    def publish_status(self, state):
        self._c.publish(self._status_topic, self._status_payload(state),
                        qos=topics.QOS["status"], retain=topics.RETAINED["status"])

    def publish(self, topic, message, kind):
        """Publish a Message; QoS and retained come from sim.topics by `kind`
        (queue, plan, etat, offset, priority, status)."""
        return self._c.publish(topic, message.to_json(),
                               qos=topics.QOS[kind], retain=topics.RETAINED[kind])

    def subscribe(self, pattern, callback, kind="queue"):
        """callback(topic: str, message: Message). Invalid payloads are dropped."""
        qos = topics.QOS[kind]
        with self._lock:
            self._subs.append((pattern, qos, callback))
        self._c.subscribe(pattern, qos)

    def _on_message(self, client, userdata, msg):
        try:
            message = Message.from_json(msg.payload)
        except ValueError:
            return
        with self._lock:
            subs = list(self._subs)
        for pattern, _, cb in subs:
            if topic_matches(pattern, msg.topic):
                cb(msg.topic, message)
