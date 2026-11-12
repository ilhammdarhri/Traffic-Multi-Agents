"""Utility function of one signal phase.

    Q_k(g_k) = max(0, Q0_k + lambda_k * C - s * g_k)     predicted queue after one cycle
    U_k(g_k) = 100 - w_k * Q_k(g_k)                      utility of giving g_k seconds of green
"""
from dataclasses import dataclass, replace

from sim import config


@dataclass(frozen=True)
class UtilityFunction:
    weight: float = config.WEIGHTS["default"]      # w_k (bus lane, main axis...)
    arrival_rate: float = 0.0                      # lambda_k, vehicles/s
    q0: float = 0.0                                # current queue, vehicles
    cycle: float = config.CYCLE                    # C, s
    saturation: float = config.SATURATION_FLOW     # s, vehicles/s during green
    base: float = config.BASE_UTILITY              # 100

    def predicted_queue(self, g):
        """Q_k(g): queue left after one cycle with g seconds of green."""
        return max(0.0, self.q0 + self.arrival_rate * self.cycle - self.saturation * g)

    def __call__(self, g):
        return self.base - self.weight * self.predicted_queue(g)

    def required_green(self):
        """Green needed to clear the queue completely (the selfish request)."""
        return (self.q0 + self.arrival_rate * self.cycle) / self.saturation

    def updated(self, **changes):
        """New function with other parameters (e.g. fresh q0 from a sensor)."""
        return replace(self, **changes)
