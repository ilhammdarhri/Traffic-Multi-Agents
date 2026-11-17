import csv
import math

from sim import config
from sim.run_experiments import aggregate, main, run_grid, summarize, t_quantile
from tests.test_mqtt_client import needs_broker


def test_aggregate_ignores_undefined_and_computes_ci():
    mean, std, ci, n = aggregate([1.0, 2.0, 3.0, None, math.nan])
    assert (mean, n) == (2.0, 3) and math.isclose(std, 1.0)
    assert math.isclose(ci, t_quantile(2) / math.sqrt(3))
    assert aggregate([None]) is None
    assert t_quantile(100) == 1.96


def test_grid_and_summary_shapes_and_determinism():
    rows = run_grid(2, 300, log=lambda *_: None)
    assert len(rows) == 2 * 4 * 2
    assert rows == run_grid(2, 300, log=lambda *_: None)
    summary = summarize(rows)
    assert len(summary) == 8 and all(s["n"] == 2 for s in summary)


def test_cli_writes_csv(tmp_path):
    assert main(["--seeds", "2", "--duration", "300", "--out", str(tmp_path)]) == 0
    with open(tmp_path / "runs.csv") as f:
        runs = list(csv.DictReader(f))
    assert len(runs) == 16 and {r["scenario"] for r in runs} == {"selfish", "nash", "consensus", "centralized"}
    assert (tmp_path / "summary.csv").exists()


@needs_broker
def test_real_broker_run_equals_loopback():
    from sim.real_broker import RealBroker
    kw = dict(demands=("normal",), scenarios=("consensus",), log=lambda *_: None)
    real = run_grid(1, 300, broker_factory=RealBroker, **kw)
    assert real == run_grid(1, 300, **kw)
