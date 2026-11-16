"""Model parameters and assumptions (single source of truth).

Both the simulator and the article must use these values.
Units: seconds, vehicles, vehicles/second.
"""

# --- Network -------------------------------------------------------------
N_INTERSECTIONS = 3            # carrefours along the avenue
PHASES = ("avenue", "side")    # phase 0 = avenue (main axis), phase 1 = side street
TRAVEL_TIME = 30               # s between two neighbouring intersections
                               # (400 m at ~13 m/s) -> ideal offset = 30 s

# --- Signal cycle ---------------------------------------------------------
CYCLE = 90                     # C, fixed cycle length (s)
LOST_PER_PHASE = 5             # 3 s amber + 2 s all-red
LOST_TIME = LOST_PER_PHASE * len(PHASES)   # L = 10 s
GREEN_BUDGET = CYCLE - LOST_TIME           # sum(g_k) = 80 s (coupling constraint)
G_MIN = 10                     # minimum green per phase (s)

# --- Traffic --------------------------------------------------------------
SATURATION_FLOW = 0.5          # s, vehicles/s discharged during green (1800 veh/h)

# Arrival rates lambda_k (veh/s) per phase, two regimes
ARRIVALS = {
    "normal": {"avenue": 0.25, "side": 0.10},   # needs 45 s + 18 s = 63 s <= 80 s
    "peak":   {"avenue": 0.30, "side": 0.15},   # needs 54 s + 27 s = 81 s  > 80 s (oversaturated)
}
INITIAL_QUEUE = 5              # Q0 (vehicles) per phase at start

# --- Utility --------------------------------------------------------------
# U_k(g_k) = 100 - w_k * Q_k(g_k),  Q_k(g_k) = max(0, Q0_k + lambda_k*C - s*g_k)
BASE_UTILITY = 100
WEIGHTS = {
    "default": 1.0,
    "bus": 1.5,                # phase with a bus lane
    "main_axis": 1.0,
}

# --- Selfish baseline rule -----------------------------------------------
# Game between the phases (coordination/game.py): each phase requests r_k in
# [G_MIN, GREEN_BUDGET - G_MIN]; the allocation is proportional,
#   g_k = GREEN_BUDGET * r_k / sum_j(r_j)   (rounded, so sum g_k = GREEN_BUDGET).
# Asking for more never lowers a phase's own green, so the maximum request is a weakly
# dominant strategy: the selfish outcome (Nash equilibrium) is an equal split, whatever the
# queues and weights. (Requesting only "what clears my queue" is NOT an equilibrium.)

# --- Simulation -----------------------------------------------------------
TIME_STEP = 1                  # s
DURATION = 3600                # s = 40 cycles
SEEDS = list(range(10))        # 10 random seeds per scenario

# --- Failures --------------------------------------------------------------------
# Fixed-time plan used when the adaptive loop is broken (same values as the knowledge base).
FALLBACK_PLAN = {"avenue": 50, "side": 30}
PLAN_TIMEOUT_CYCLES = 3        # actuator: no plan received for this many cycles -> fixed-time plan
STALE_CYCLES = 2               # intersection agent: a sensor silent for this many cycles -> fixed-time plan

# --- Platoons (avenue flow from one intersection to the next) ---------------
# A vehicle leaving intersection i on the avenue reaches intersection i+1 after
# TRAVEL_TIME seconds with probability PLATOON_FRACTION (the others turn off). The rest of
# the downstream avenue demand is external: (1 - PLATOON_FRACTION) * lambda_avenue.
PLATOON_FRACTION = 0.8

# --- Consensus on offsets -----------------------------------------------------
# One consensus iteration per cycle. Aligned offset of intersection i (i = 0, 1, ...):
#   a_i = (offset_i - i * TRAVEL_TIME) mod C   -> all equal means a green wave.
#   shift_i = CONSENSUS_GAIN * sum_{j neighbour} wrap(a_j - a_i)     (circular difference)
CONSENSUS_GAIN = 0.4           # step size alpha (stable if alpha < 2 / lambda_max(Laplacian))
CONSENSUS_EPS = 0.5            # s, convergence threshold on |shift|
CONSENSUS_MAX_ITER = 50        # timeout (alt fragment: converged / timeout)
MAX_SHIFT = 10                 # s, largest change of the cycle length in one cycle (safety)
