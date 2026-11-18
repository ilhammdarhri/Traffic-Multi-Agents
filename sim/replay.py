"""Record the demo cases and build ONE self-contained page: results/replay.html.

    python -m sim.replay                 # all cases (about 1 minute)
    python -m sim.replay --quick         # fewer / shorter cases, for a test

The page (sim/replay_template.html + the traces as JSON) needs no server and no internet:
open it in a browser. It shows the avenue, the time-space diagram (the green wave) and the metrics.
"""
import argparse
import json
import os

from kb.knowledge_base import KnowledgeBase
from sim import config
from sim.trace import record

PREFIX = '<!doctype html>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
TEMPLATE = os.path.join(os.path.dirname(__file__), "replay_template.html")
NORMAL, PEAK = config.ARRIVALS["normal"], config.ARRIVALS["peak"]
SEED = 17          # close to the 20-seed averages, and 30 s away from a green wave at the start
SCEN = (("selfish", "Selfish", "Each phase asks for the maximum, clocks stay random."),
        ("nash", "Nash", "Phases bargain; clocks stay random."),
        ("consensus", "Consensus", "Nash plus consensus on offsets: the clocks align."),
        ("centralized", "Centralized", "Optimum with ideal offsets: the reference."))


def crash(c):
    return lambda cor: cor.crash_agent(c)


def restart(c):
    return lambda cor: cor.recover_agent(c)


def cases(quick=False):
    """Yield (group, kwargs for record())."""
    d = 900 if quick else 3600
    for demand, rates in (("normal", NORMAL), ("peak", PEAK)):
        for key, label, note in SCEN:
            yield ("Scenarios, %s demand" % demand,
                   dict(name=f"{demand}-{key}", scenario=key, rates=rates, seed=SEED, duration=d,
                        title=f"{label}, {demand} demand", note=note))
    f = 900 if quick else 2400
    yield ("Failures", dict(name="fail-middle", scenario="consensus", rates=NORMAL, seed=SEED, duration=f,
                            events=[(300, "carrefour2: agent crashed", crash("carrefour2"))],
                            title="Middle agent crashes at 300 s",
                            note="Its neighbours keep its last offset as an anchor: the wave survives."))
    yield ("Failures", dict(name="fail-first", scenario="consensus", rates=NORMAL, seed=SEED, duration=f,
                            events=[(0, "carrefour1: agent never started", crash("carrefour1"))],
                            title="First agent dead from the start",
                            note="It never announced an offset, so nobody can align with it."))
    yield ("Failures", dict(name="fail-restart", scenario="consensus", rates=NORMAL, seed=SEED, duration=f,
                            events=[(300, "carrefour2: agent crashed", crash("carrefour2")),
                                    (min(1500, f - 100), "carrefour2: agent restarted", restart("carrefour2"))],
                            title="Middle agent crashes, then restarts",
                            note="After the restart the corridor converges again."))
    kb = KnowledgeBase()
    for prio, label, note in ((False, "without priority", "The ambulance waits at red lights."),
                              (True, "with priority", "Preemption: green just before it arrives.")):
        yield ("Ambulance", dict(name=f"ev-{'on' if prio else 'off'}", scenario="consensus", rates=NORMAL,
                                 seed=SEED, duration=1300, kb=kb, ev={"start": 900, "priority": prio},
                                 title=f"Ambulance {label}", note=note))


def build(out="results/replay.html", quick=False, log=print, standalone=True):
    traces = []
    for group, kw in cases(quick):
        tr = record(**kw)
        tr["meta"]["group"] = group
        traces.append(tr)
        log(f"  {kw['name']:14s} wait {tr['final']['wait']:6.1f} s  gap {tr['final']['gap']:4.1f} s")
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    data = json.dumps(traces, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("/*__TRACES__*/[]", data)
    if standalone:                       # a published artifact gets its skeleton from the host instead
        html = PREFIX + html
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"written {out} ({len(html) / 1e6:.2f} MB, {len(traces)} cases)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/replay.html")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    build(a.out, a.quick)


if __name__ == "__main__":
    main()
