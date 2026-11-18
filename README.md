# Cooperative traffic-signal control at connected intersections

Multi-agent IoT simulator: three intersections along an avenue share their green time with
utility-based agents, game theory and a distributed consensus on their offsets. Every message goes
through a real MQTT broker (Mosquitto). Master MSID S3, module *Systèmes Multi-Agents appliqués à l'IoT*,
subject no. 11 *Feux de circulation*.

Four scenarios are compared: **selfish** agents, **Nash** negotiation, **consensus** on offsets
(green wave) and a **centralized** optimum. Research questions studied: Q1 (price of anarchy),
Q2 (consensus convergence, loss of an intersection) and Q3 (emergency-vehicle priority).

## Quick start

Python 3.8 or newer and an MQTT broker on `localhost:1883`.

```bash
brew install mosquitto && brew services start mosquitto      # macOS; or: mosquitto -v
pip install -r requirements.txt
python -m pytest -q tests          # 223 tests; the 6 that need the broker are skipped without it
```

Only the real-broker run needs Mosquitto; everything else runs in-process (see *Two brokers* below).

## Reproduce the results

| Command | What it does | Output | Time |
|---|---|---|---|
| `python -m sim.run_experiments --seeds 20` | 2 demands × 4 scenarios × 20 seeds, 3600 s each | `results/runs.csv`, `results/summary.csv` | ~5 min |
| `python -m sim.run_experiments --broker mqtt --seeds 1 --duration 900` | same runs through the **real MQTT broker**, checked against the in-process run (must print `8/8 runs identical`) | `results/*_mqtt.csv` | ~2 min |
| `python -m sim.studies all --seeds 10` | Q1, Q2, Q3 studies | `results/q1_*.csv`, `q2_*.csv`, `q3_*.csv` | ~10 min |
| `python -m sim.figures` | the 8 figures of the report | `results/figures/*.png` and `.pdf` | ~20 s |
| `python -m sim.replay` | records 13 demo cases and builds **one page, `results/replay.html`**: open it in a browser (no server, no internet) | `results/replay.html` | ~5 s |
| `python -m sim.compare_strategies --seeds 5` | quick console comparison of the four scenarios | console | ~2 min |

Everything is seeded: the same command gives the same files. Parameters live in one file, `sim/config.py`.

## Main results (20 seeds, 3600 s, mean wait per vehicle, 95 % confidence)

| Scenario | Normal demand | Peak demand |
|---|---|---|
| selfish | 97.1 ± 5.9 s | 183.6 ± 6.0 s |
| nash | 22.2 ± 1.1 s | 92.9 ± 6.3 s |
| consensus | 17.5 ± 0.4 s | 90.3 ± 6.5 s |
| centralized | 17.1 ± 0.3 s | 69.6 ± 7.1 s |

- **Q1.** The price of anarchy of one cycle is small (at most 1.04), but selfishness is costly over time
  because queues carry over: selfish agents wait 5.8 times longer than the optimum at normal load.
- **Q2.** Consensus brings the offsets to a green wave in 6 to 11 cycles depending on the gain (8.0 at the
  default 0.4). If an agent dies after it has announced its offset, its neighbours keep it as an anchor and
  the wave survives (mean wait +0.4 to +1 s). If it dies before ever speaking, nobody can align with it.
- **Q3.** Preemption removes the emergency vehicle's delay (15 s → 0 s) for +0.9 to +2.3 % mean wait of the others.

## Visual replay

`results/replay.html` replays a whole execution: the avenue with its lights and queues, the time-space diagram
(green bars per intersection and the groups of vehicles travelling between them: a green wave is when the lines
meet the next green bar), and the distance to the green wave and mean wait over time. 13 cases: the four
scenarios at normal and peak demand, three agent failures and an ambulance with and without priority. Two cases
can be shown side by side. All cases use seed 17, so the same vehicles arrive in each.

## How it works

```
 Sensor ──queue──► ApproachAgent ──► IntersectionAgent ──plan──► Actuator ──► traffic lights
                                        │      ▲   (strategy: selfish / nash / consensus / centralized)
                       offset ◄─────────┘      └── knowledge base (weights, events, priority rules)
                       (neighbouring intersections, consensus)
```

* **Model** (`sim/traffic.py`, `sim/corridor.py`): 3 intersections, 2 phases each, cycle 90 s, green budget
  80 s, Poisson arrivals, FIFO queues, platoons travelling 30 s between intersections.
* **Utility agents** (`agents/`): sense → update state → decide → act. Utility `U_k = 100 − w_k · Q_k(g_k)`.
* **Game theory** (`coordination/game.py`): proportional-allocation request game, Nash equilibria, Nash
  bargaining, social optimum, price of anarchy / stability, Jain index.
* **Consensus** (`coordination/consensus.py`): average consensus on circular aligned offsets, one iteration
  per cycle, smooth shifts of the next cycle's green, timeout after 50 iterations.
* **Knowledge base** (`kb/`): OWL ontology (Owlready2, no reasoner) with phase weights, events, priority rules
  and the fallback plan. See `kb/README.md`.
* **Failures**: Last Will (`offline`) of a neighbour, actuator watchdog (3 cycles without plan → fixed-time
  plan 50/30), stale-sensor fallback in the intersection agent.

### MQTT contract (`sim/topics.py`)

| Topic | Content | QoS | Retained |
|---|---|---|---|
| `traffic/{c}/approach/{dir}/queue` | queue length | 0 | no |
| `traffic/{c}/signal/plan` | green times for the next cycle | 1 | yes |
| `traffic/{c}/signal/etat` | phase displayed | 1 | yes |
| `traffic/{c}/signal/preempt` | immediate priority green (emergency) | 2 | no |
| `traffic/{c}/signal/shift` | offset correction (consensus) | 2 | no |
| `traffic/{c}/offset/{id}` | offset at a consensus iteration | 1 | no |
| `traffic/priority/request` | emergency / bus request | 2 | no |
| `sma/agent/{id}/statut` | `online` / `offline` (Last Will) | 1 | yes |

Every payload is JSON: `{"ts": ..., "source": ..., "valeur": ..., "unite": ...}` (`sim/message.py`).

### Two brokers

`sim/loopback.py` is an in-process broker with the same interface as the real client (wildcards, retained
messages, Last Will): fast, deterministic, used for the 20-seed experiments and most tests.
`sim/real_broker.py` runs the same corridor through Mosquitto in lockstep (a barrier waits until every
message has been delivered before the clock moves on). Both give identical results, which the
`--broker mqtt` command and the test suite check.

## Assumptions and limits

* One avenue of 3 intersections, two phases, fixed cycle of 90 s; offsets are adjusted by smooth shifts.
* Offsets in seconds are integers, so a consensus leaves a residual gap of up to 2 s.
* The price of anarchy is undefined when a welfare is negative (queues above 100 vehicles); averages
  cover the decisions where it is defined (`poa_defined` in the CSV).
* The loopback fires a Last Will instantly; Mosquitto fires it about 1.5 × keepalive after a crash.
* Consensus does not bridge a dead middle intersection; a node that never spoke is simply left out.
* An emergency vehicle is assumed not to be blocked by the queue ahead.

## Layout

| Folder | Content |
|---|---|
| `agents/` | Agent, UtilityAgent, IntersectionAgent, ApproachAgent, emergency and bus agents |
| `coordination/` | game theory, strategies (Selfish, Nash, Consensus, Centralized), consensus on offsets |
| `kb/` | OWL knowledge base and its query layer |
| `sim/` | simulator, MQTT client, sensors and actuators, brokers, metrics, experiments, studies, figures, trace recorder and replay page |
| `tests/` | unit and integration tests |
| `results/` | CSV results and `figures/` |

## Team

* Member 1: simulator, agents, knowledge base, experiments.
* Member 2: article, design dossier (UML, MQTT specification).
