"""Green-sharing game between the two phases of one intersection.

Players     the phases (avenue, side).
Strategies  a green request r_k in {g_min, ..., G - g_min}, in seconds.
Coupling    the intersection has only G = C - L seconds of green. Requests become an
            allocation through the proportional rule  g_k = G * r_k / sum_j r_j  (rounded to
            whole seconds), so  sum_k g_k = G  and  g_k >= g_min  always hold.
Payoff      U_k(g_k) = 100 - w_k * Q_k(g_k)      (agents.utility.UtilityFunction)

Solution concepts
    selfish_split()          Nash equilibrium of the request game: every phase asks for the
                             maximum (asking for more never lowers one's own allocation, hence
                             never lowers one's own payoff: a weakly dominant strategy).
                             With equal requests the proportional rule gives an equal split.
    nash_equilibria()        all pure equilibria, by brute force (the payoff is flat once a
                             queue is cleared, so there are usually many).
    nash_bargaining_split()  Nash bargaining solution, threat point = the selfish outcome.
    social_optimum_split()   utilitarian optimum: maximum of the summed utility.
    price_of_anarchy()       W(optimum) / W(worst Nash equilibrium), with W = sum of utilities.

The game only needs, from each utility function, `f(g)` and `f.required_green()`.
"""
import math

from sim import config

TOL = 1e-9         # utilities are equal up to this tolerance (plateaus are exact ties)
EPS = 1e-6          # regularisation of the Nash product, see nash_bargaining_split()


def jain_index(values):
    """Jain's fairness index J = (sum x)^2 / (n * sum x^2), in [1/n, 1]."""
    values = [float(v) for v in values]
    squares = sum(v * v for v in values)
    if not values or squares == 0:
        return 1.0
    return sum(values) ** 2 / (len(values) * squares)


class GreenGame:
    def __init__(self, functions, budget=config.GREEN_BUDGET, g_min=config.G_MIN):
        """functions: {phase: utility function}, exactly two phases, in a fixed order."""
        if len(functions) != 2:
            raise ValueError("GreenGame models exactly two competing phases")
        self.phases = tuple(functions)
        self.functions = tuple(functions[p] for p in self.phases)
        self.budget, self.g_min = budget, g_min
        self.max_request = budget - g_min
        self.requests = range(g_min, self.max_request + 1)
        self._ordered = None

    # --- payoffs ------------------------------------------------------------
    def payoffs(self, split):
        return tuple(f(g) for f, g in zip(self.functions, split))

    def welfare(self, split):
        """Social welfare W: sum of the phase utilities."""
        return sum(self.payoffs(split))

    # --- feasible splits and tie-break ---------------------------------------
    def ordered_splits(self):
        """All feasible splits (g_first, G - g_first), best tie-break candidates first.

        The utility is flat while both queues stay positive, so many splits tie. Ties are
        broken in favour of the split closest to proportional to the green each phase needs.
        """
        if self._ordered is None:
            need_a, need_s = (f.required_green() for f in self.functions)
            total = need_a + need_s
            target = self.budget * need_a / total if total > 0 else self.budget / 2
            splits = [(g, self.budget - g) for g in self.requests]
            self._ordered = sorted(splits, key=lambda s: (abs(s[0] - target), s[0]))
        return list(self._ordered)

    # --- the request game -----------------------------------------------------
    def allocate(self, requests):
        """Proportional allocation rule: requests -> split (sum = budget, each >= g_min)."""
        ra, rs = requests
        for r in (ra, rs):
            if not self.g_min <= r <= self.max_request:
                raise ValueError(f"request {r} outside [{self.g_min}, {self.max_request}]")
        ga = math.floor(self.budget * ra / (ra + rs) + 0.5)
        ga = min(max(ga, self.g_min), self.max_request)
        return (ga, self.budget - ga)

    def selfish_split(self):
        """Outcome when every phase plays its dominant strategy (the maximum request)."""
        return self.allocate((self.max_request, self.max_request))

    def nash_equilibria(self):
        """All pure Nash equilibria of the request game, as request profiles."""
        reqs = list(self.requests)
        pay = {(ra, rs): self.payoffs(self.allocate((ra, rs))) for ra in reqs for rs in reqs}
        best_a = {rs: max(pay[(ra, rs)][0] for ra in reqs) for rs in reqs}
        best_s = {ra: max(pay[(ra, rs)][1] for rs in reqs) for ra in reqs}
        return [(ra, rs) for ra in reqs for rs in reqs
                if pay[(ra, rs)][0] >= best_a[rs] - TOL and pay[(ra, rs)][1] >= best_s[ra] - TOL]

    # --- cooperative solutions --------------------------------------------------
    def social_optimum_split(self):
        """Split maximising the summed utility (first maximum in tie-break order)."""
        best, best_w = None, -math.inf
        for split in self.ordered_splits():
            w = self.welfare(split)
            if w > best_w + TOL:
                best, best_w = split, w
        return best

    def nash_bargaining_split(self):
        """Nash bargaining solution with the selfish outcome as threat point d.

        Among the splits that leave no phase worse off than d (individual rationality),
        maximise the product of the gains  prod_k (U_k - d_k + EPS).  The EPS term only
        matters when a phase cannot gain at all (e.g. its queue is already cleared in d):
        the product is then maximised by giving the other phase the largest gain that
        costs the first one nothing. When no phase can gain without hurting another,
        the solution is d itself.
        """
        d = self.payoffs(self.selfish_split())
        best, best_value = self.selfish_split(), -math.inf
        for split in self.ordered_splits():
            gains = [u - d_k for u, d_k in zip(self.payoffs(split), d)]
            if min(gains) < -TOL:
                continue
            value = math.prod(max(g, 0.0) + EPS for g in gains)
            if value > best_value * (1 + 1e-9):
                best, best_value = split, value
        return best

    # --- efficiency measures ------------------------------------------------------
    def _equilibrium_welfares(self):
        return [self.welfare(self.allocate(p)) for p in self.nash_equilibria()]

    @staticmethod
    def _ratio(numerator, denominator):
        """Ratio of welfares; nan when undefined (a welfare <= 0, i.e. queues above 100)."""
        if numerator <= 0 or denominator <= 0:
            return math.nan
        return numerator / denominator

    def price_of_anarchy(self):
        """PoA = W(optimum) / W(worst Nash equilibrium)  >= 1."""
        optimum = self.welfare(self.social_optimum_split())
        return self._ratio(optimum, min(self._equilibrium_welfares()))

    def price_of_stability(self):
        """W(optimum) / W(best Nash equilibrium): the gap that no coordination of the
        equilibrium choice could remove."""
        optimum = self.welfare(self.social_optimum_split())
        return self._ratio(optimum, max(self._equilibrium_welfares()))
