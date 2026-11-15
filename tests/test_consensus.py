import pytest

from agents.intersection import IntersectionAgent
from coordination.consensus import OffsetConsensus, wrap
from coordination.strategies import ConsensusStrategy
from sim import config, topics
from sim.corridor import Corridor
from sim.message import Message
from sim.scenarios import SCENARIOS, ideal_offsets, initial_offsets, make_corridor, random_offsets
from tests.test_traffic_devices import FakeMqtt

T, C = config.TRAVEL_TIME, config.CYCLE
NORMAL = config.ARRIVALS["normal"]


# --- circular arithmetic ---------------------------------------------------------------
@pytest.mark.parametrize("x,expected", [(0, 0), (20, 20), (-20, -20), (50, -40), (-50, 40),
                                        (45, -45), (90, 0), (130, 40)])
def test_wrap(x, expected):
    assert wrap(x) == expected


def test_alignment_removes_the_travel_time():
    node = OffsetConsensus(1, {"a": 0, "b": 2})
    assert node.align(30, 1) == 0 and node.align(0, 0) == 0 and node.align(60, 2) == 0
    assert node.align(10, 1) == (10 - T) % C == 70


# --- one node ------------------------------------------------------------------------------
def test_node_waits_until_every_neighbour_was_heard():
    node = OffsetConsensus(1, {"a": 0, "b": 2})
    node.receive("a", 0)
    assert not node.ready() and node.update(50) == 0 and not node.converged
    node.receive("b", 60)
    assert node.ready() and node.update(50) != 0


def test_node_moves_towards_its_neighbour():
    node = OffsetConsensus(1, {"a": 0})
    node.receive("a", 0)                       # neighbour wave start 0 -> I should be at 30
    assert node.update(10) > 0                 # own offset 10 is too early
    assert node.update(50) < 0                 # 50 is too late


def test_shift_follows_the_shortest_way_round_the_circle():
    node = OffsetConsensus(0, {"b": 1})
    node.receive("b", 20)                      # aligned a_b = 20 - 30 = -10 = 80; own offset 85 -> a = 85
    assert node.update(85) == int(round(0.4 * wrap(80 - 85)))      # -2: backwards, not +88
    far = OffsetConsensus(0, {"b": 1})
    far.receive("b", 30)                       # a_b = 0; own offset 80 -> error +10 across the wrap
    assert far.update(80) == 4


def test_shift_is_clipped():
    node = OffsetConsensus(0, {"b": 1})
    node.receive("b", 30 + 40)                 # error 40 -> raw 16
    assert node.update(0) == config.MAX_SHIFT


def test_converged_after_two_stable_rounds_and_detects_disturbance():
    node = OffsetConsensus(0, {"b": 1})
    node.receive("b", 30)
    assert node.update(0) == 0 and not node.converged         # one stable round
    assert node.update(0) == 0 and node.converged and node.converged_at == 2
    node.receive("b", 50)                                     # the neighbour moved
    assert node.update(0) != 0 and not node.converged


def test_timeout_freezes_the_node():
    node = OffsetConsensus(0, {"b": 1}, max_iter=3)
    node.receive("b", 30 + 40)
    assert [node.update(0) for _ in range(3)] == [config.MAX_SHIFT, config.MAX_SHIFT, 0]
    assert node.timed_out and not node.converged
    assert node.update(0) == 0                                # stays frozen


def test_forgotten_neighbour_leaves_the_average():
    node = OffsetConsensus(1, {"a": 0, "b": 2})
    node.receive("a", 0); node.receive("b", 60)
    node.forget("b")
    assert node.neighbors == {"a": 0} and node.ready()
    node.receive("b", 0)                                      # no longer a neighbour: ignored
    assert "b" not in node.aligned


def test_node_without_neighbours_does_nothing():
    node = OffsetConsensus(0, {})
    assert node.update(40) == 0 and not node.converged


# --- the whole chain, without any simulator ----------------------------------------------------
def run_chain(offsets, iterations=40, **options):
    nodes = [OffsetConsensus(i, {j: j for j in (i - 1, i + 1) if 0 <= j < len(offsets)}, **options)
             for i in range(len(offsets))]
    offsets = list(offsets)
    history = []
    for _ in range(iterations):
        for i, node in enumerate(nodes):                      # asynchronous: use the latest values
            shift = node.update(offsets[i])
            offsets[i] = (offsets[i] + shift) % C
            for j, other in enumerate(nodes):
                other.receive(i, offsets[i])
        aligned = [(o - i * T) % C for i, o in enumerate(offsets)]
        history.append(max(abs(wrap(a - b)) for a in aligned for b in aligned))
    return nodes, history


@pytest.mark.parametrize("start", [[0, 0, 0], [14, 46, 36], [83, 57, 2], [0, 45, 0], [10, 40, 70], [5, 5, 5]])
def test_chain_reaches_a_green_wave(start):
    nodes, history = run_chain(start)
    assert history[-1] <= 2                                   # integer shifts leave at most 2 s
    assert all(n.converged for n in nodes) and not any(n.timed_out for n in nodes)
    assert max(n.converged_at for n in nodes) <= 15


def test_chain_spread_never_grows_much():
    _, history = run_chain([14, 46, 36])
    assert max(history) <= history[0] + 2


# --- strategy and messages (agent with a fake broker) --------------------------------------------
def consensus_agent(position=1, offset=50, neighbors=None, **options):
    mq = FakeMqtt()
    neighbors = {"carrefour1": 0, "carrefour3": 2} if neighbors is None else neighbors
    ia = IntersectionAgent("carrefour2", mq, strategy=ConsensusStrategy(**options),
                           position=position, offset=offset, neighbors=neighbors)
    return ia, mq


def test_consensus_subscribes_to_its_neighbours_only():
    ia, mq = consensus_agent()
    patterns = [p for p, _ in mq.subs]
    assert "traffic/carrefour1/offset/+" in patterns and "traffic/carrefour3/offset/+" in patterns
    assert not any("carrefour2/offset" in p for p in patterns)


def test_consensus_publishes_offset_and_shift_each_cycle():
    ia, mq = consensus_agent()
    mq.deliver("traffic/carrefour1/offset/ia-carrefour1", Message("ia-carrefour1", {"offset": 0, "cycle": 1}, "s"))
    mq.deliver("traffic/carrefour3/offset/ia-carrefour3", Message("ia-carrefour3", {"offset": 60, "cycle": 1}, "s"))
    ia.queues = {"avenue": 5, "side": 5}
    ia.decide_cycle(0)
    sent = {kind: (topic, msg) for topic, msg, kind in mq.published}
    assert sent["plan"][0] == "traffic/carrefour2/signal/plan"
    topic, msg = sent["offset"]
    assert topic == "traffic/carrefour2/offset/ia-carrefour2" and msg.unite == "s"
    assert msg.valeur == {"offset": ia.offset, "cycle": 1}
    topic, msg = sent["shift"]
    assert topic == "traffic/carrefour2/signal/shift" and isinstance(msg.valeur["shift_s"], int)
    assert ia.offset == (50 + msg.valeur["shift_s"]) % C


def test_consensus_without_shift_publishes_no_shift_command():
    ia, mq = consensus_agent(offset=30, neighbors={"carrefour1": 0})
    mq.deliver("traffic/carrefour1/offset/ia-carrefour1", Message("ia-carrefour1", {"offset": 0, "cycle": 1}, "s"))
    ia.queues = {"avenue": 5, "side": 5}
    ia.decide_cycle(0)
    assert [k for _, _, k in mq.published].count("shift") == 0
    assert [k for _, _, k in mq.published].count("offset") == 1


@pytest.mark.parametrize("junk", ["garbage", {"offset": "x"}, {"offset": None}, {"offset": True},
                                  {"offset": float("inf")}, {"cycle": 3}, 42])
def test_malformed_offset_messages_are_ignored(junk):
    ia, mq = consensus_agent()
    try:
        mq.deliver("traffic/carrefour1/offset/ia-carrefour1", Message("ia-carrefour1", junk, "s"))
    except ValueError:
        pytest.skip("rejected earlier, by the Message schema")
    assert ia.strategy.node.aligned == {}


def test_a_strategy_instance_serves_one_agent():
    strategy = ConsensusStrategy()
    IntersectionAgent("carrefour2", FakeMqtt(), strategy=strategy, position=1, neighbors={"carrefour1": 0})
    with pytest.raises(RuntimeError):
        IntersectionAgent("carrefour3", FakeMqtt(), strategy=strategy, position=2, neighbors={"carrefour2": 1})


def test_consensus_splits_are_the_nash_bargaining_splits():
    ia, _ = consensus_agent()
    ia.update_state({"avenue": 5, "side": 5})
    assert ia.decide() == (52, 28)


# --- scenarios ---------------------------------------------------------------------------------
def test_initial_offsets_per_scenario():
    assert initial_offsets("centralized", 3) == ideal_offsets() == [0, 30, 60]
    assert initial_offsets("selfish", 3) == initial_offsets("nash", 3) == initial_offsets("consensus", 3)
    assert initial_offsets("nash", 3) == random_offsets(3) != random_offsets(4)
    assert all(0 <= o < C for o in random_offsets(7))
    with pytest.raises(ValueError):
        initial_offsets("anarchy", 0)


def test_make_corridor_builds_each_scenario():
    for name in SCENARIOS:
        cor = make_corridor(name, NORMAL, seed=1)
        assert all(a.strategy.name == name for a in cor.agents.values())
        assert [a.offset for a in cor.agents.values()] == initial_offsets(name, 1)


# --- consensus in the closed loop ------------------------------------------------------------------
def run_scenario(name, seed, seconds=config.DURATION, rates=NORMAL):
    cor = make_corridor(name, rates, seed)
    cor.run(seconds)
    return cor


@pytest.mark.parametrize("seed", range(4))
def test_consensus_builds_a_green_wave_in_a_few_cycles(seed):
    cor = make_corridor("consensus", NORMAL, seed)
    start = cor.offset_spread()
    spreads = []
    for _ in range(25):
        cor.run(config.CYCLE)
        spreads.append(cor.offset_spread())
    assert spreads[12] <= 2 and max(spreads[12:]) <= 2         # converged, and it stays converged
    assert start <= 2 or spreads[0] <= start                   # moving the right way from the start
    assert all(a.strategy.node.converged for a in cor.agents.values())
    assert max(a.strategy.node.converged_at for a in cor.agents.values()) <= 12


def test_uncoordinated_scenarios_keep_their_random_clocks():
    for name in ("selfish", "nash"):
        cor = make_corridor(name, NORMAL, 0)
        start = cor.offset_spread()
        cor.run(10 * config.CYCLE)
        assert cor.offset_spread() == start
        assert not any(k in ("offset", "shift") for _, k in cor.broker.log)


def test_centralized_starts_on_the_green_wave():
    cor = make_corridor("centralized", NORMAL, 0)
    cor.run(5 * config.CYCLE)
    assert cor.offset_spread() == 0


def test_consensus_traffic_goes_through_the_broker():
    cor = run_scenario("consensus", 0, seconds=12 * config.CYCLE)
    log = cor.broker.log
    n_offset = sum(1 for _, k in log if k == "offset")
    assert n_offset >= 3 * 10                                  # every intersection, every cycle
    assert any(k == "shift" for _, k in log)
    assert {t for t, k in log if k == "offset"} == {f"traffic/carrefour{i}/offset/ia-carrefour{i}" for i in (1, 2, 3)}
    assert sum(a.shifts for a in cor.actuators.values()) == sum(1 for _, k in log if k == "shift")
    assert sum(a.rejected for a in cor.actuators.values()) == 0


def test_timeout_when_consensus_cannot_finish():
    cor = Corridor(rates=NORMAL, offsets=[0, 0, 0], seed=0, strategy=ConsensusStrategy(max_iter=2))
    cor.run(8 * config.CYCLE)
    nodes = [a.strategy.node for a in cor.agents.values()]
    assert all(n.timed_out and not n.converged for n in nodes)
    frozen = cor.offset_spread()
    shifts_before = sum(1 for _, k in cor.broker.log if k == "shift")
    cor.run(5 * config.CYCLE)
    assert sum(1 for _, k in cor.broker.log if k == "shift") == shifts_before    # no drift on stale data
    assert cor.offset_spread() == frozen


def test_consensus_beats_uncoordinated_clocks_and_the_wave_reference_is_best():
    seeds = range(3)
    wait = {name: sum(run_scenario(name, s).mean_wait() for s in seeds) / 3
            for name in ("nash", "consensus", "centralized")}
    assert wait["consensus"] < wait["nash"]
    assert wait["centralized"] <= wait["consensus"] + 1.0
