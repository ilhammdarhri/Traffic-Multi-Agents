"""ApproachAgent: the agent of one access lane (loop detector or camera).

Each decision cycle it senses the queue and publishes it on
traffic/{carrefour}/approach/{dir}/queue (QoS 0, not retained).
"""
from agents.base import Agent
from sim.devices import Sensor


class ApproachAgent(Agent):
    def __init__(self, carrefour, direction, read_fn, mqtt):
        super().__init__(f"aa-{carrefour}-{direction}", mqtt=mqtt)
        self.carrefour, self.direction = carrefour, direction
        self.read_fn = read_fn
        self.sensor = Sensor(carrefour, direction, read_fn, mqtt)

    def decide(self):
        """The only decision of this agent: report the measured queue."""
        return self.state["queue"]

    def act(self, action):
        self.sensor.publish()

    def sense(self):
        """One full cycle: measure -> state -> publish. Returns the queue length."""
        return self.step({"queue": int(self.read_fn())})
