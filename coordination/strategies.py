"""Coordination strategies (Strategy pattern).

An IntersectionAgent holds one CoordinationStrategy and asks it for the green split of the
current cycle. Swapping the strategy switches between the comparison scenarios:

    SelfishStrategy      scenario 1  phases act alone: Nash equilibrium of the request game
    NashStrategy         scenario 2  phases negotiate: Nash bargaining solution
    CentralizedStrategy  scenario 4  social optimum (reference)
    ConsensusStrategy    scenario 3  = Nash negotiation + consensus on offsets  (step 12)
"""
from abc import ABC, abstractmethod


class CoordinationStrategy(ABC):
    name = "abstract"

    @abstractmethod
    def choose_split(self, game):
        """Return the split (g_avenue, g_side) for this cycle, given a GreenGame."""

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


STRATEGIES = {cls.name: cls for cls in (SelfishStrategy, NashStrategy, CentralizedStrategy)}


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
