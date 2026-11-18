"""Figures of the report, drawn from the CSV files of results/ (no simulation except fig_wave).

    python -m sim.figures                 # reads results/*.csv, writes results/figures/*.png and .pdf
    python -m sim.figures --no-wave       # skip the figure that re-runs a few simulations

One colour per scenario, everywhere:  selfish blue, nash orange, consensus aqua, centralized yellow
(first four slots of a palette validated for colour-vision deficiency; every series is also labelled
directly and the underlying numbers are in the CSV files).
"""
import argparse
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLORS = {"selfish": "#2a78d6", "nash": "#eb6834", "consensus": "#1baf7a", "centralized": "#eda100"}
MARKERS = {"selfish": "o", "nash": "s", "consensus": "^", "centralized": "D"}
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
ORDER = ("selfish", "nash", "consensus", "centralized")
GOOD, BAD = "#1baf7a", "#eb6834"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.edgecolor": MUTED, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False,
})


def read(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in r.items():
            try:
                r[k] = float(v) if v not in ("", None) else None
            except ValueError:
                pass
    return rows


def save(fig, out, name):
    os.makedirs(out, exist_ok=True)
    fig.savefig(os.path.join(out, name + ".png"), dpi=200, bbox_inches="tight")
    fig.savefig(os.path.join(out, name + ".pdf"), bbox_inches="tight")
    plt.close(fig)
    return name


def ci_bars(ax, labels, means, cis, colors, horizontal=False, fmt="{:.1f}"):
    pos = range(len(labels))
    cis = [c or 0 for c in cis]
    if horizontal:
        ax.barh(pos, means, xerr=cis, color=colors, height=0.62, error_kw={"ecolor": INK, "lw": 0.9, "capsize": 2})
        ax.set_yticks(list(pos), labels)
        for p, m, c in zip(pos, means, cis):
            ax.text(m + c + max(means) * 0.015, p, fmt.format(m), va="center", fontsize=9, color=INK)
        ax.grid(axis="y", visible=False)
    else:
        ax.bar(pos, means, yerr=cis, color=colors, width=0.62, error_kw={"ecolor": INK, "lw": 0.9, "capsize": 2})
        ax.set_xticks(list(pos), labels)
        for p, m, c in zip(pos, means, cis):
            ax.text(p, m + c + max(means) * 0.02, fmt.format(m), ha="center", fontsize=9, color=INK)
        ax.grid(axis="x", visible=False)


# --------------------------------------------------------------------------------------------
def fig_scenarios(res, out):
    s = read(f"{res}/summary.csv")
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    for ax, demand in zip(axes, ("normal", "peak")):
        rows = {r["scenario"]: r for r in s if r["demand"] == demand}
        ci_bars(ax, ORDER, [rows[k]["mean_wait_mean"] for k in ORDER], [rows[k]["mean_wait_ci95"] for k in ORDER],
                [COLORS[k] for k in ORDER])
        ax.set_title(f"{demand.capitalize()} demand")
        ax.set_ylabel("mean wait per vehicle (s)")
    fig.suptitle("Four scenarios, 20 seeds, 3600 s (bars: mean, whiskers: 95 % confidence)",
                 x=0.01, ha="left", fontsize=10, color=MUTED)
    fig.tight_layout()
    return save(fig, out, "fig1_scenarios")


def fig_other_metrics(res, out):
    s = read(f"{res}/summary.csv")
    fig, axes = plt.subplots(2, 2, figsize=(9, 6))
    spec = [("max_queue_mean", None, "max queue (vehicles)", "{:.0f}"),
            ("stops_per_vehicle_mean", "stops_per_vehicle_ci95", "stops per vehicle", "{:.2f}"),
            ("jain_wait_mean", "jain_wait_ci95", "Jain fairness index", "{:.2f}"),
            ("offset_gap_mean", "offset_gap_ci95", "final distance to green wave (s)", "{:.1f}")]
    for ax, (key, ci, label, fmt) in zip(axes.flat, spec):
        for i, demand in enumerate(("normal", "peak")):
            rows = {r["scenario"]: r for r in s if r["demand"] == demand}
            xs = [j * 3 + i * 1.0 for j in range(4)]
            vals = [rows[k][key] for k in ORDER]
            ax.bar(xs, vals, width=0.9, color=[COLORS[k] for k in ORDER],
                   alpha=1.0 if demand == "normal" else 0.55,
                   yerr=[(rows[k][ci] or 0) for k in ORDER] if ci else None,
                   error_kw={"ecolor": INK, "lw": 0.8, "capsize": 1.5})
        ax.set_xticks([j * 3 + 0.5 for j in range(4)], ORDER, fontsize=8)
        ax.set_title(label)
        ax.grid(axis="x", visible=False)
    fig.suptitle("Solid bars: normal demand. Light bars: peak demand (whiskers: 95 % confidence).",
                 x=0.01, ha="left", fontsize=10, color=MUTED)
    fig.tight_layout()
    return save(fig, out, "fig2_other_metrics")


def fig_q1_static(res, out):
    rows = read(f"{res}/q1_static.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    shades = {0: "#9cc3f0", 5: "#2a78d6", 20: "#1f5aa3", 40: "#143a6b"}
    for q0, col in shades.items():
        g = [r for r in rows if r["q0"] == q0 and r["poa"] == r["poa"]]
        ax.plot([r["load"] for r in g], [r["poa"] for r in g], marker="o", ms=5, lw=1.8, color=col)
        if q0 == 40:
            continue
        label = "20 or 40 queued" if q0 == 20 else f"{int(q0)} queued"
        ax.text(g[-1]["load"] + 0.015, g[-1]["poa"] + (0.0025 if q0 == 20 else 0), label, color=MUTED, fontsize=8,
                va="bottom" if q0 == 20 else "center")
    ax.axhline(1, color=MUTED, lw=0.8)
    ax.set_xlabel("traffic load (multiple of normal demand)")
    ax.set_ylabel("price of anarchy, one cycle")
    ax.set_title("Q1  Static PoA of the green-sharing game")
    ax.set_xlim(0.45, 1.5)
    fig.tight_layout()
    return save(fig, out, "fig3_q1_static_poa")


def fig_q1_dynamic(res, out):
    rows = read(f"{res}/q1_summary.csv")
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.8))
    ax = axes[0]
    for key, name in (("wait_selfish", "selfish"), ("wait_nash", "nash"), ("wait_centralized", "centralized")):
        ax.plot([r["load"] for r in rows], [r[key] for r in rows], color=COLORS[name], marker=MARKERS[name],
                ms=5, lw=1.8)
        ax.text(rows[-1]["load"] + 0.015, rows[-1][key], name, color=INK, fontsize=9, va="center")
    ax.set_xlim(0.45, 1.5)
    ax.set_xlabel("traffic load (multiple of normal demand)")
    ax.set_ylabel("mean wait per vehicle (s)")
    ax.set_title("Mean wait against load")
    ax = axes[1]
    ax.plot([r["load"] for r in rows], [r["dynamic_poa"] for r in rows], color=COLORS["selfish"],
            marker="o", ms=5, lw=1.8, label="selfish / optimum")
    ax.plot([r["load"] for r in rows], [r["nash_over_optimum"] for r in rows], color=COLORS["nash"],
            marker="s", ms=5, lw=1.8, label="nash / optimum")
    ax.axhline(1, color=MUTED, lw=0.8)
    ax.set_xlabel("traffic load (multiple of normal demand)")
    ax.set_ylabel("ratio of mean waits")
    ax.set_title("Dynamic price of anarchy")
    ax.set_ylim(0.8, 7.6)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return save(fig, out, "fig4_q1_dynamic_poa")


def fig_q2_convergence(res, out):
    rows = read(f"{res}/q2_convergence.csv")
    gains = sorted({r["gain"] for r in rows})
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    means, lows, highs = [], [], []
    for g in gains:
        xs = sorted(r["convergence_cycles"] for r in rows if r["gain"] == g and r["convergence_cycles"] is not None)
        means.append(sum(xs) / len(xs)); lows.append(xs[0]); highs.append(xs[-1])
    ax.fill_between(gains, lows, highs, color=COLORS["consensus"], alpha=0.18, lw=0)
    ax.plot(gains, means, color=COLORS["consensus"], marker="^", ms=6, lw=2)
    ax.text(gains[0], highs[0] + 0.4, "range over seeds", color=MUTED, fontsize=8)
    ax.text(gains[-1] + 0.02, means[-1], "mean", color=INK, fontsize=9, va="center")
    ax.set_xlim(gains[0] - 0.03, gains[-1] + 0.12)
    ax.set_ylim(0, max(highs) + 2)
    ax.set_xlabel("consensus gain")
    ax.set_ylabel("cycles until the agents detect convergence")
    ax.set_title("Q2  Consensus speed (random starting clocks)")
    fig.tight_layout()
    return save(fig, out, "fig5_q2_convergence")


def fig_q2_failures(res, out):
    rows = read(f"{res}/q2_failures.csv")
    cases = list(dict.fromkeys(r["case"] for r in rows))
    def agg(key):
        m, c = [], []
        for case in cases:
            xs = [r[key] for r in rows if r["case"] == case and r[key] is not None]
            mean = sum(xs) / len(xs)
            sd = (sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5 if len(xs) > 1 else 0
            m.append(mean); c.append(2.26 * sd / len(xs) ** 0.5 if len(xs) > 1 else 0)
        return m, c
    colors = [COLORS["consensus"] if c != "no consensus (nash)" else COLORS["nash"] for c in cases]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), sharey=True)
    for ax, key, title in zip(axes, ("mean_wait", "offset_gap"),
                              ("Mean wait per vehicle (s)", "Final distance to green wave (s)")):
        m, c = agg(key)
        ci_bars(ax, cases, m, c, colors, horizontal=True)
        ax.set_title(title)
    axes[1].tick_params(labelleft=False)
    axes[0].invert_yaxis()                      # shared axis: first case ("none") at the top
    fig.suptitle("Q2  Loss of an intersection agent (consensus scenario, 10 seeds; orange = no consensus)",
                 x=0.01, ha="left", fontsize=10, color=MUTED)
    fig.tight_layout()
    return save(fig, out, "fig6_q2_failures")


def fig_q3(res, out):
    rows = read(f"{res}/q3_summary.csv")
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    demands = [r["demand"] for r in rows]
    for ax, (off, on, title, unit) in zip(axes, (("ev_delay_off", "ev_delay_on", "Emergency vehicle: total delay", "s"),
                                                  ("others_wait_off", "others_wait_on", "Other vehicles: mean wait", "s"))):
        for i, r in enumerate(rows):
            ax.bar(i * 3, r[off], width=1.0, color="#9a9a94")
            ax.bar(i * 3 + 1.1, r[on], width=1.0, color=COLORS["consensus"])
            for x, v in ((i * 3, r[off]), (i * 3 + 1.1, r[on])):
                ax.text(x, v + max(r[off], r[on]) * 0.03, f"{v:.1f}", ha="center", fontsize=9)
        ax.set_xticks([i * 3 + 0.55 for i in range(len(rows))], [d.capitalize() for d in demands])
        ax.set_title(title)
        ax.set_ylabel("seconds")
        ax.grid(axis="x", visible=False)
    for i, r in enumerate(rows):
        axes[1].text(i * 3 + 0.55, -0.16 * axes[1].get_ylim()[1], f"{r['cost_for_others_pct']:+.1f} %",
                     ha="center", fontsize=9, color=MUTED)
    fig.suptitle("Q3  Emergency vehicle priority (grey: no priority, green: priority; mean over runs)", x=0.01, ha="left", fontsize=10, color=MUTED)
    fig.tight_layout()
    return save(fig, out, "fig7_q3_priority")


def fig_wave(out, seeds=5, duration=1800):
    from sim import config
    from sim.metrics import Recorder
    from sim.scenarios import make_corridor
    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    for scenario in ("nash", "consensus", "centralized"):
        series = []
        for seed in range(seeds):
            rec = Recorder(make_corridor(scenario, config.ARRIVALS["normal"], seed))
            gaps = []
            for _ in range(duration):
                rec.step()
                if rec.cor.t % config.CYCLE == 0:
                    gaps.append(rec.cor.offset_spread())
            series.append(gaps)
        n = min(len(s) for s in series)
        mean = [sum(s[i] for s in series) / seeds for i in range(n)]
        ax.plot(range(1, n + 1), mean, color=COLORS[scenario], marker=MARKERS[scenario], ms=4, lw=1.8)
        ax.text(n + 0.3, mean[-1], scenario, color=INK, fontsize=9, va="center")
    ax.set_xlim(0, 24.5)
    ax.set_xlabel("cycle")
    ax.set_ylabel("distance to green wave (s)")
    ax.set_title("Green wave formation (mean of 5 seeds)")
    fig.tight_layout()
    return save(fig, out, "fig8_green_wave")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="results")
    ap.add_argument("--no-wave", action="store_true")
    a = ap.parse_args(argv)
    out = os.path.join(a.results, "figures")
    made = [f(a.results, out) for f in (fig_scenarios, fig_other_metrics, fig_q1_static, fig_q1_dynamic,
                                         fig_q2_convergence, fig_q2_failures, fig_q3)]
    if not a.no_wave:
        made.append(fig_wave(out))
    print("written:", ", ".join(f"{out}/{n}.png" for n in made))


if __name__ == "__main__":
    main()
