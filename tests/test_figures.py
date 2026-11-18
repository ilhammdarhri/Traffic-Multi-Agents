import os

import pytest

from sim import figures

RESULTS = "results"
needs_results = pytest.mark.skipif(not os.path.exists(f"{RESULTS}/q3_summary.csv"),
                                   reason="run the experiments first (results/*.csv)")


@needs_results
def test_all_figures_are_written(tmp_path):
    figures.main(["--results", RESULTS, "--no-wave"])
    names = os.listdir(f"{RESULTS}/figures")
    for n in ("fig1_scenarios", "fig3_q1_static_poa", "fig6_q2_failures", "fig7_q3_priority"):
        assert f"{n}.png" in names and f"{n}.pdf" in names


def test_read_converts_numbers_and_empty_cells(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("a,b,c\n1.5,,x\n")
    assert figures.read(str(p)) == [{"a": 1.5, "b": None, "c": "x"}]
