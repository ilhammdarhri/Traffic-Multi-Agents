import json
import re

from sim import config
from sim.replay import build, cases
from sim.trace import record

NORMAL = config.ARRIVALS["normal"]


def test_trace_shapes_and_values():
    tr = record("t", "consensus", NORMAL, 3, 400)
    n = 400
    assert len(tr["gap"]) == len(tr["wait"]) == n and tr["carrefours"] == ["carrefour1", "carrefour2", "carrefour3"]
    for c in tr["carrefours"]:
        d = tr["c"][c]
        assert all(len(v) == n for v in d.values())
        assert set(d["sig"]) <= {"A", "S", "R"} and min(d["ga"]) >= config.G_MIN
        assert all(0 <= t <= x for t, x in zip(d["thr"], d["dep"]))      # through <= left
    assert tr["final"]["wait"] == tr["wait"][-1]


def test_trace_is_deterministic_and_matches_the_run():
    a = record("t", "nash", NORMAL, 2, 300)
    b = record("t", "nash", NORMAL, 2, 300)
    assert a == b
    from sim.metrics import run_experiment
    assert abs(a["wait"][-1] - run_experiment("nash", NORMAL, 2, 300)["mean_wait"]) < 0.01


def test_crash_and_ambulance_are_recorded():
    from sim.replay import crash
    tr = record("t", "consensus", NORMAL, 1, 900, events=[(100, "carrefour2: agent crashed", crash("carrefour2"))])
    up = tr["c"]["carrefour2"]["up"]
    assert up[99] == 1 and up[101] == 0 and any(e["t"] == 100 for e in tr["events"])
    assert any("fixed-time plan" in e["text"] for e in tr["events"])         # actuator fallback logged
    ev = [kw for g, kw in cases(quick=True) if kw["name"] == "ev-on"][0]
    tr = record(**ev)
    assert tr["ev"][ev["ev"]["start"] - 1] is None and tr["ev"][ev["ev"]["start"] + 5] is not None
    assert tr["meta"]["ev_delay"] is not None and tr["meta"]["ev_done"] is not None


def test_build_makes_a_self_contained_page(tmp_path):
    out = build(str(tmp_path / "r.html"), quick=True, log=lambda *_: None)
    html = open(out, encoding="utf-8").read()
    assert html.startswith("<!doctype html>") and "__TRACES__" not in html
    assert "<script src=" not in html                       # nothing to download: works offline
    data = json.loads(re.search(r"const TRACES = (\[.*?\]);\nconst byName", html, re.S).group(1))
    assert len(data) == 13 and {t["meta"]["group"] for t in data} >= {"Failures", "Ambulance"}
    art = build(str(tmp_path / "a.html"), quick=True, log=lambda *_: None, standalone=False)
    assert not open(art, encoding="utf-8").read().startswith("<!doctype")
