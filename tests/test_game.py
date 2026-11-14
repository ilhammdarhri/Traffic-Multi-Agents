import itertools
import math

import pytest

from agents.utility import UtilityFunction
from coordination.game import TOL, GreenGame, jain_index
from sim import config

AVENUE, SIDE = "avenue", "side"
NORMAL, PEAK = config.ARRIVALS["normal"], config.ARRIVALS["peak"]


def make_game(qa=5, qs=5, rates=NORMAL, wa=1.0, ws=1.0):
    return GreenGame({
        AVENUE: UtilityFunction(weight=wa, arrival_rate=rates[AVENUE], q0=qa),
        SIDE: UtilityFunction(weight=ws, arrival_rate=rates[SIDE], q0=qs)})


# a grid of states: demand regime x initial queues x weights
STATES = [make_game(qa, qs, rates, wa, ws)
          for rates in (NORMAL, PEAK)
          for qa, qs in itertools.product((0, 5, 20, 60), repeat=2)
          for wa, ws in ((1.0, 1.0), (1.0, 1.5), (2.0, 1.0))]


# --- allocation rule ---------------------------------------------------------------
def test_allocation_is_proportional_and_respects_the_budget():
    game = make_game()
    assert game.allocate((70, 70)) == (40, 40)
    assert game.allocate((50, 25)) == (53, 27)               # 80 * 50/75 = 53.3
    assert game.allocate((70, 10)) == (70, 10)
    assert game.allocate((10, 70)) == (10, 70)
    for ra, rs in itertools.product(game.requests, repeat=2):
        ga, gs = game.allocate((ra, rs))
        assert ga + gs == config.GREEN_BUDGET
        assert ga >= config.G_MIN and gs >= config.G_MIN


def test_allocation_is_monotone_in_own_request():
    game = make_game()
    for rs in game.requests:
        alloc = [game.allocate((ra, rs))[0] for ra in game.requests]
        assert alloc == sorted(alloc)


@pytest.mark.parametrize("bad", [(9, 40), (40, 71), (0, 0)])
def test_allocation_rejects_requests_out_of_range(bad):
    with pytest.raises(ValueError):
        make_game().allocate(bad)


def test_game_needs_two_phases():
    f = UtilityFunction(arrival_rate=0.1)
    with pytest.raises(ValueError):
        GreenGame({"a": f})


# --- tie-break order ----------------------------------------------------------------
def test_ordered_splits_start_at_the_need_proportional_split():
    game = make_game()                                       # needs 55 and 28 -> target 53.0
    splits = game.ordered_splits()
    assert len(splits) == config.GREEN_BUDGET - 2 * config.G_MIN + 1
    assert splits[0] == (53, 27)
    assert all(a + b == config.GREEN_BUDGET for a, b in splits)


# --- Nash equilibrium of the request game ----------------------------------------------
def test_maximum_request_is_weakly_dominant():
    for game in STATES:
        for rs in game.requests:                              # whatever the opponent asks
            best = max(game.payoffs(game.allocate((ra, rs)))[0] for ra in game.requests)
            assert game.payoffs(game.allocate((game.max_request, rs)))[0] >= best - TOL
        for ra in game.requests:
            best = max(game.payoffs(game.allocate((ra, rs)))[1] for rs in game.requests)
            assert game.payoffs(game.allocate((ra, game.max_request)))[1] >= best - TOL


def test_selfish_outcome_is_a_nash_equilibrium_and_the_worst_one():
    for game in STATES:
        profile = (game.max_request, game.max_request)
        assert profile in game.nash_equilibria()
        assert game.selfish_split() == (40, 40)
        worst = min(game._equilibrium_welfares())
        assert worst == pytest.approx(game.welfare(game.selfish_split()))


def test_every_equilibrium_pays_at_least_the_selfish_payoff():
    for game in STATES[::7]:
        selfish = game.payoffs(game.selfish_split())
        for profile in game.nash_equilibria():
            paid = game.payoffs(game.allocate(profile))
            assert paid[0] >= selfish[0] - TOL and paid[1] >= selfish[1] - TOL


def test_equilibrium_is_not_unique_when_a_queue_is_cleared():
    assert len(make_game().nash_equilibria()) > 1            # payoff is flat above the need


def test_need_based_requests_are_not_an_equilibrium():
    """Asking only for what clears the queue is not stable: a phase gains by asking more."""
    game = make_game(rates=PEAK)
    need = tuple(min(game.max_request, math.ceil(f.required_green())) for f in game.functions)
    assert need not in game.nash_equilibria()
    ga, gs = game.allocate(need)
    greedy = game.allocate((game.max_request, need[1]))
    assert game.payoffs(greedy)[0] > game.payoffs((ga, gs))[0]


# --- social optimum --------------------------------------------------------------------
def test_optimum_values_normal_and_peak():
    assert make_game().social_optimum_split() == (53, 27)
    assert make_game(rates=PEAK).social_optimum_split() == (51, 29)


def test_optimum_is_the_maximum_over_all_splits():
    for game in STATES:
        best = game.welfare(game.social_optimum_split())
        assert all(game.welfare(s) <= best + TOL for s in game.ordered_splits())


# --- price of anarchy ---------------------------------------------------------------------
def test_poa_normal_demand():
    game = make_game()
    assert game.welfare(game.social_optimum_split()) == pytest.approx(198.5)
    assert game.welfare(game.selfish_split()) == pytest.approx(192.5)
    assert game.price_of_anarchy() == pytest.approx(198.5 / 192.5)        # 1.0312


def test_poa_peak_demand():
    assert make_game(rates=PEAK).price_of_anarchy() == pytest.approx(189.5 / 188.0)


def test_poa_is_one_when_both_queues_clear_anyway():
    game = make_game(0, 0, {AVENUE: 0.10, SIDE: 0.05})
    assert game.price_of_anarchy() == pytest.approx(1.0)


def test_poa_grows_with_asymmetry():
    sym = make_game()
    asym = make_game(40, 0, {AVENUE: 0.30, SIDE: 0.02})
    assert asym.price_of_anarchy() == pytest.approx(168 / 153)            # 1.098
    assert asym.price_of_anarchy() > sym.price_of_anarchy() > 1.0


def test_poa_is_at_least_one_and_pos_at_most_poa():
    for game in STATES:
        poa, pos = game.price_of_anarchy(), game.price_of_stability()
        if math.isnan(poa):
            continue
        assert poa >= 1.0 - 1e-9 and 1.0 - 1e-9 <= pos <= poa + 1e-9


def test_price_of_stability_is_one_with_equal_weights():
    """Equal weights: a satisfied phase can ask for less at no cost, so an efficient
    equilibrium exists and the anarchy comes only from the worst equilibrium
    (checked on the whole grid of states)."""
    for game in STATES:
        if game.functions[0].weight == game.functions[1].weight:
            pos = game.price_of_stability()
            assert math.isnan(pos) or pos == pytest.approx(1.0)


def test_unequal_weights_make_anarchy_unavoidable():
    """The equal-split equilibrium ignores the weights (bus lane, main axis). When both
    phases are overloaded it is the only equilibrium (up to rounding): PoS = PoA > 1."""
    game = make_game(5, 60, NORMAL, wa=1.0, ws=1.5)
    assert len(game.nash_equilibria()) <= 4
    assert game.price_of_stability() == pytest.approx(game.price_of_anarchy())
    assert game.price_of_stability() > 1.05
    assert game.social_optimum_split() == (10, 70)           # the heavier phase should win


def test_poa_is_undefined_with_negative_welfare():
    game = make_game(60, 60, {AVENUE: 0.40, SIDE: 0.40}, 1.0, 2.0)
    assert game.welfare(game.selfish_split()) < 0
    assert math.isnan(game.price_of_anarchy())


# --- Nash bargaining ---------------------------------------------------------------------
def test_bargaining_values():
    assert make_game().nash_bargaining_split() == (52, 28)                 # side keeps what it needs
    assert make_game(rates=PEAK).nash_bargaining_split() == (43, 37)
    assert make_game(40, 0, {AVENUE: 0.30, SIDE: 0.02}).nash_bargaining_split() == (70, 10)


def test_bargaining_is_rational_and_between_selfish_and_optimum():
    for game in STATES:
        d = game.payoffs(game.selfish_split())
        split = game.nash_bargaining_split()
        paid = game.payoffs(split)
        assert paid[0] >= d[0] - TOL and paid[1] >= d[1] - TOL            # nobody loses
        assert game.welfare(split) >= game.welfare(game.selfish_split()) - TOL
        assert game.welfare(split) <= game.welfare(game.social_optimum_split()) + TOL


def test_bargaining_cannot_always_reach_the_optimum():
    """Both queues stay positive and the weights differ: any shift hurts the lighter phase,
    so bargaining stays at the threat point while the optimum favours the heavier phase."""
    game = make_game(60, 60, {AVENUE: 0.40, SIDE: 0.40}, 1.0, 2.0)
    assert game.nash_bargaining_split() == game.selfish_split() == (40, 40)
    assert game.social_optimum_split() == (10, 70)
    assert game.welfare(game.nash_bargaining_split()) < game.welfare(game.social_optimum_split())


# --- Jain index ---------------------------------------------------------------------------
def test_jain_index():
    assert jain_index([5, 5, 5]) == pytest.approx(1.0)
    assert jain_index([1, 0, 0, 0]) == pytest.approx(0.25)                 # 1/n
    assert jain_index([1, 2, 3]) == pytest.approx(36 / 42)
    assert jain_index([0, 0]) == 1.0 and jain_index([]) == 1.0
