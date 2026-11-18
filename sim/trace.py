"""Record a whole run second by second, to replay it in the viewer (results/replay.html).

    python -m sim.replay          # records every case and builds results/replay.html

A trace is a plain dict (JSON): for each intersection, per second, the light shown (A = avenue green,
S = side green, R = all red), the queues, the avenue departures, the offset and the avenue green of the
cycle; and for the corridor the distance to the green wave, the mean wait so far, the events (crash,
fallback, preemption...) and, when there is one, the position of the emergency vehicle.
"""
from agents.vehicles import EmergencyVehicleAgent
from sim import config
from sim.scenarios import make_corridor
from sim.traffic import AVENUE, SIDE

LETTER = {"avenue": "A", "side": "S", "red": "R"}
ROUTE = [("carrefour1", AVENUE), ("carrefour2", AVENUE), ("carrefour3", AVENUE)]


def ev_position(ev):
    """Position along the avenue in intersection units (0 = first intersection), or None."""
    if ev.status == "done":
        return None
    if ev.status == "at_line":
        return float(ev.idx)
    return ev.idx - max(0, ev.eta) / ev.TRAVEL_TIME


def record(name, scenario, rates, seed, duration, events=(), kb=None, ev=None, title="", note=""):
    """events: (t, label, function(corridor)) ; ev: {"start": t, "priority": bool}."""
    cor = make_corridor(scenario, rates, seed, kb=kb)
    agent = None
    if ev:
        agent = EmergencyVehicleAgent("ev1", ROUTE, cor.broker.client("ev1"), first_eta=40,
                                      priority=ev["priority"])
        cor.add_vehicle(agent, start_t=ev["start"])
    cs = cor.carrefours
    out = {c: {"sig": [], "qa": [], "qs": [], "dep": [], "thr": [], "off": [], "ga": [], "gs": [],
               "up": [], "fb": []} for c in cs}
    carry = {c: 0.0 for c in cs}                         # same fractional carry as Corridor.step
    gap, wait, evpos, log = [], [], [], []
    pending = sorted(events, key=lambda e: e[0])
    seen = {c: (0, 0) for c in cs}                      # (fallbacks, preemptions) already reported
    for _ in range(duration):
        while pending and pending[0][0] <= cor.t:
            t, label, fn = pending.pop(0)
            fn(cor)
            log.append({"t": cor.t, "text": label})
        cor.step()
        for c in cs:
            sim, o = cor.sims[c], out[c]
            o["sig"].append(LETTER[sim.current_signal()])
            q = sim.queue_lengths()
            o["qa"].append(q[AVENUE]); o["qs"].append(q[SIDE])
            left = sim.phases[AVENUE].last_departed
            o["dep"].append(left)
            carry[c] += cor.platoon * left
            through = int(carry[c] + 1e-9)               # vehicles that really reach the next intersection
            carry[c] -= through
            o["thr"].append(through)
            o["off"].append(int(sim.offset))
            o["ga"].append(int(sim.cycle_plan[AVENUE]))
            o["gs"].append(int(sim.cycle_plan[SIDE]))
            o["up"].append(1 if getattr(cor.agents[c].mqtt, "alive", True) else 0)
            o["fb"].append(1 if cor.actuators[c].fallback_active else 0)
            act = cor.actuators[c]
            if act.fallbacks > seen[c][0]:
                log.append({"t": cor.t, "text": f"{c}: no plan received, fixed-time plan 50/30"})
            if act.preemptions > seen[c][1]:
                log.append({"t": cor.t, "text": f"{c}: priority green for the ambulance"})
            seen[c] = (act.fallbacks, act.preemptions)
        gap.append(cor.offset_spread())
        wait.append(round(cor.mean_wait(), 2))
        evpos.append(None if agent is None or cor.t - 1 < ev["start"] else ev_position(agent))
    if agent is not None:
        log.append({"t": ev["start"], "text": "ambulance enters the avenue"})
        passed = [p for p in agent.passed_at if p is not None]
        if passed:
            log.append({"t": passed[-1], "text": f"ambulance crosses the last intersection (waited {agent.total_delay} s)"})
    meta = {"name": name, "scenario": scenario, "seed": seed, "duration": duration, "title": title,
            "note": note, "cycle": config.CYCLE, "travel": config.TRAVEL_TIME,
            "ev_priority": None if not ev else ev["priority"],
            "ev_start": None if not ev else ev["start"], "ev_delay": None if agent is None else agent.total_delay,
            "ev_done": None if agent is None or not [x for x in agent.passed_at if x is not None] else max(x for x in agent.passed_at if x is not None)}
    return {"meta": meta, "carrefours": cs, "c": out, "gap": gap, "wait": wait,
            "ev": evpos if agent else None, "events": sorted(log, key=lambda e: e["t"]),
            "final": {"wait": wait[-1], "gap": gap[-1]}}
