"""Abstract agent classes.

Agent        : perceive -> update state -> decide -> act (one decision cycle).
UtilityAgent : decide() = argmax over feasible actions of the utility U(a).
"""
from abc import ABC, abstractmethod


class Agent(ABC):
    def __init__(self, agent_id, mqtt=None, kb=None):
        self.agent_id = agent_id
        self.mqtt = mqtt            # MqttClient (optional, None in pure unit tests)
        self.kb = kb                # KnowledgeBase (optional)
        self.state = {}             # S_t
        self.last_action = None     # A_{t-1}

    def update_state(self, observation):
        """S_t = Model(S_{t-1}, O_t, A_{t-1}). Default model: merge observations.
        Subclasses override this with a real model (e.g. queue prediction)."""
        self.state.update(observation)

    @abstractmethod
    def decide(self):
        """Return the action A_t chosen from the current state."""

    def act(self, action):
        """Execute the action (e.g. publish a plan). Default: nothing."""

    def step(self, observation):
        """One full decision cycle."""
        self.update_state(observation)
        action = self.decide()
        self.act(action)
        self.last_action = action
        return action


class UtilityAgent(Agent):
    """Agent that maximises its utility: A_t = argmax_a U(a)."""

    @abstractmethod
    def feasible_actions(self):
        """Iterable of the actions allowed in the current state (constraints included)."""

    @abstractmethod
    def utility(self, action):
        """Utility U(a) of an action in the current state."""

    def decide(self):
        best_action, best_value = None, float("-inf")
        for action in self.feasible_actions():
            value = self.utility(action)
            if value > best_value:               # strict '>' : first maximum wins (deterministic)
                best_action, best_value = action, value
        if best_action is None:
            raise RuntimeError(f"{self.agent_id}: no feasible action")
        return best_action
