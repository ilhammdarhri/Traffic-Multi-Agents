"""Coordination strategies (Strategy pattern).

An IntersectionAgent holds one CoordinationStrategy and asks it for the green split of the
current cycle. Swapping the strategy switches between the comparison scenarios:

    SelfishStrategy      scenario 1  phases act alone: Nash equilibrium of the request game
    NashStrategy         scenario 2  phases negotiate: Nash bargaining solution
    ConsensusStrategy    scenario 3  Nash negotiation + consensus on offsets between neighbours
    CentralizedStrategy  scenario 4  social optimum (reference; the ideal offsets are set by
                                     sim.scenarios, as a central controller would)

A strategy has two jobs: choose_split() every cycle, and coordinate_offsets() every cycle
(a no-op except for consensus). A strategy instance belongs to ONE agent.
"""
import math
from abc import ABC, abstractmethod

from sim import config, topics
from sim.message import Message


class CoordinationStrategy(ABC):
    name = "abstract"

    def attach(self, agent):
        """Called once by the IntersectionAgent that owns this strategy (subscriptions...)."""

    @abstractmethod
    def choose_split(self, game):
        """Return the split (g_avenue, g_side) for this cycle, given a GreenGame."""

    def coordinate_offsets(self, agent):
        """Called by the agent once per cycle, after the plan was published."""

    def __repr__(self):
        return f"{type(self).__name__}()"


class SelfishStrategy(CoordinationStrategy):
    """Every phase asks for as much green as possible; the proportional rule decides."""
    name = "selfish"

    def choose_split(self, game):
        return game.selfish_split()


class NashStrategy(CoordinationStrategy):
    """Phases bargain from the selfish outcome (Nash bargaining solution)."""
    name = "nash"

    def choose_split(self, game):
        return game.nash_bargaining_split()


class CentralizedStrategy(CoordinationStrategy):
    """Maximise the summed utility: what a controller with full information would do."""
    name = "centralized"

    def choose_split(self, game):
        return game.social_optimum_split()


class ConsensusStrategy(NashStrategy):
    """Phases negotiate the split (Nash bargaining) and neighbouring intersections reach
    consensus on their offsets, one iteration per cycle, through MQTT:
        publish  traffic/{c}/offset/{id}   own offset (QoS 1)
        receive  traffic/{neighbour}/offset/+
        publish  traffic/{c}/signal/shift  correction for the next cycle (QoS 2)
    """
    name = "consensus"

    def __init__(self, **options):
        self.options = options              # gain, eps, max_iter, max_shift, stable_rounds
        self.node = None

    def attach(self, agent):
        from coordination.consensus import OffsetConsensus
        if self.node is not None:
            raise RuntimeError("a ConsensusStrategy belongs to one agent: create one per agent")
        self.node = OffsetConsensus(agent.position, agent.neighbors, **self.options)
        for neighbor in agent.neighbors:
            agent.mqtt.subscribe(topics.offset(neighbor, "+"), self._on_offset, kind="offset")

    def _on_offset(self, topic, message):
        value = message.valeur
        offset = value.get("offset") if isinstance(value, dict) else None
        if isinstance(offset, (int, float)) and not isinstance(offset, bool) and math.isfinite(offset):
            self.node.receive(topic.split("/")[1], offset)

    def coordinate_offsets(self, agent):
        shift = self.node.update(agent.offset)
        agent.offset = (agent.offset + shift) % config.CYCLE
        announce = {"offset": agent.offset, "cycle": agent.cycles}
        agent.mqtt.publish(topics.offset(agent.carrefour, agent.agent_id),
                           Message(source=agent.agent_id, valeur=announce, unite="s"), "offset")
        if shift:
            agent.mqtt.publish(topics.signal_shift(agent.carrefour),
                               Message(source=agent.agent_id, valeur={"shift_s": shift}, unite="s"),
                               "shift")


STRATEGIES = {cls.name: cls for cls in (SelfishStrategy, NashStrategy, ConsensusStrategy,
                                        CentralizedStrategy)}


def make_strategy(name):
    try:
        return STRATEGIES[name]()
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}") from None


def resolve_strategy(strategy):
    """None -> CentralizedStrategy, a name -> that strategy, an instance -> itself."""
    if strategy is None:
        return CentralizedStrategy()
    if isinstance(strategy, str):
        return make_strategy(strategy)
    return strategy
