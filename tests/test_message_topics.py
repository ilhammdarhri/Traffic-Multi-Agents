import pytest

from sim import topics
from sim.message import Message


def test_roundtrip():
    m = Message(source="loop-c3-n", valeur=14, unite="vehicules")
    m2 = Message.from_json(m.to_json().encode())
    assert m2 == m


def test_spec_example_payload():
    payload = '{"ts": "2026-10-09T08:05:00Z", "source": "loop-c3-n", "valeur": 14, "unite": "vehicules"}'
    m = Message.from_json(payload)
    assert m.valeur == 14 and m.source == "loop-c3-n"


def test_structured_value():
    m = Message(source="ia-c1", valeur={"avenue": 50, "side": 30}, unite="s")
    assert Message.from_json(m.to_json()).valeur == {"avenue": 50, "side": 30}


@pytest.mark.parametrize("bad", [
    '{"source": "x", "valeur": 1, "unite": "v"}',                      # missing ts
    '{"ts": "yesterday", "source": "x", "valeur": 1, "unite": "v"}',   # bad ts
    '{"ts": "2026-10-09T08:05:00Z", "source": "", "valeur": 1, "unite": "v"}',
    '{"ts": "2026-10-09T08:05:00Z", "source": "x", "valeur": 1, "unite": "v", "z": 1}',
    '[1, 2]',
])
def test_invalid_payloads_rejected(bad):
    with pytest.raises(ValueError):
        Message.from_json(bad)


def test_topic_builders():
    assert topics.queue("carrefour3", "nord") == "traffic/carrefour3/approach/nord/queue"
    assert topics.signal_plan("carrefour1") == "traffic/carrefour1/signal/plan"
    assert topics.agent_status("ia-c2") == "sma/agent/ia-c2/statut"
    assert topics.everything_of("carrefour3") == "traffic/carrefour3/#"


def test_qos_and_retained_cover_same_kinds():
    assert set(topics.QOS) == set(topics.RETAINED)
    assert topics.QOS["priority"] == 2
    assert topics.RETAINED["plan"] and topics.RETAINED["status"]
    assert not topics.RETAINED["queue"]
