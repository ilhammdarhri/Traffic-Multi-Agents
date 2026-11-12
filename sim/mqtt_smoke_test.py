"""MQTT smoke test: publish one JSON message and receive it back.

Usage (broker must be running on localhost:1883):
    python sim/mqtt_smoke_test.py
"""
import json
import sys
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

HOST, PORT = "localhost", 1883
TOPIC = "traffic/carrefour3/approach/nord/queue"
received = threading.Event()


def make_client(client_id):
    # paho-mqtt 2.x requires a callback API version; 1.x does not have it.
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    return mqtt.Client(client_id=client_id)


def on_connect(client, userdata, flags, rc, properties=None):
    print("subscriber connected, rc =", rc)
    client.subscribe("traffic/+/approach/+/queue", qos=0)


def on_message(client, userdata, msg):
    print("RECEIVED on", msg.topic, "->", json.loads(msg.payload))
    received.set()


sub = make_client("smoke-sub")
sub.on_connect = on_connect
sub.on_message = on_message
try:
    sub.connect(HOST, PORT)
except ConnectionRefusedError:
    sys.exit("Cannot reach the broker on localhost:1883. Is Mosquitto running?")
sub.loop_start()

pub = make_client("smoke-pub")
pub.connect(HOST, PORT)
pub.loop_start()

payload = {
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "source": "loop-c3-n",
    "valeur": 14,
    "unite": "vehicules",
}
# Wait a moment so the subscription is active before publishing.
threading.Event().wait(1.0)
pub.publish(TOPIC, json.dumps(payload), qos=0)

ok = received.wait(timeout=5)
pub.loop_stop()
sub.loop_stop()
print("SUCCESS" if ok else "FAILED: no message received")
sys.exit(0 if ok else 1)
