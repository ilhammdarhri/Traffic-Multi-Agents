"""Vehicle agents that ask for priority: EmergencyVehicleAgent and BusAgent.

A vehicle follows a route of (carrefour, phase) stops. When it is within HORIZON
seconds of the next stop line it publishes ONE request on traffic/priority/request
(QoS 2). It then drives to the stop line and passes as soon as its phase is green;
otherwise it waits (this waiting time is its delay).

Simplification: the vehicle is assumed not to be blocked by the queue ahead (other
vehicles make way), so its delay is only the wait for green.

Each tick (1 s) the runner calls  vehicle.step({"t": t, "signals": {carrefour: signal}}).
"""
from agents.base import Agent
from sim import topics
from sim.message import Message


class PriorityVehicleAgent(Agent):
    KIND = None
    TRAVEL_TIME = 30            # s between two stop lines
    HORIZON = 40                # s before the stop line at which the request is sent

    def __init__(self, agent_id, route, mqtt, first_eta, priority=True):
        super().__init__(agent_id, mqtt=mqtt)
        self.route = list(route)            # [(carrefour, phase), ...]
        self.priority = priority            # False = baseline (never asks for priority)
        self.idx = 0                        # index of the next stop line
        self.eta = first_eta                # s to reach it
        self.status = "driving"             # driving | at_line | done
        self.requested = set()
        self.delays = [0] * len(self.route)         # s waited at each stop line
        self.passed_at = [None] * len(self.route)   # simulation time of each crossing
        self.t = 0

    @property
    def done(self):
        return self.status == "done"

    @property
    def total_delay(self):
        return sum(self.delays)

    def update_state(self, observation):
        self.state = observation
        self.t = observation["t"]
        if self.status == "driving":
            self.eta -= 1
            if self.eta <= 0:
                self.status = "at_line"

    def decide(self):
        if self.status == "done":
            return "finish"
        carrefour, phase = self.route[self.idx]
        if self.status == "at_line":
            return "pass" if self.state["signals"][carrefour] == phase else "wait"
        if self.priority and self.idx not in self.requested and self.eta <= self.HORIZON:
            return "request"
        return "drive"

    def act(self, action):
        carrefour, phase = self.route[self.idx] if self.status != "done" else (None, None)
        if action == "request":
            self.requested.add(self.idx)
            payload = {"carrefour": carrefour, "phase": phase, "kind": self.KIND, "eta_s": self.eta}
            self.mqtt.publish(topics.PRIORITY_REQUEST,
                              Message(source=self.agent_id, valeur=payload, unite="request"), "priority")
        elif action == "wait":
            self.delays[self.idx] += 1
        elif action == "pass":
            self.passed_at[self.idx] = self.t
            self.idx += 1
            if self.idx == len(self.route):
                self.status = "done"
            else:
                self.status, self.eta = "driving", self.TRAVEL_TIME


class EmergencyVehicleAgent(PriorityVehicleAgent):
    """Ambulance / fire truck: rule "emergency => priority green" (preemption)."""
    KIND = "emergency"
    TRAVEL_TIME = 20
    HORIZON = 40


class BusAgent(PriorityVehicleAgent):
    """Bus: rule "bus => heavier weight" in the next green-split decision."""
    KIND = "bus"
    TRAVEL_TIME = 30
    HORIZON = 90                # one cycle, so that a decision happens before it arrives
