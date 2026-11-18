"""Benchmark harness on the scripted backend: cost mechanics and selection recall (model independent)."""
import sys

from _util import FIXTURES, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import bench  # noqa: E402

SPEC = FIXTURES / "bench" / "scenarios.yaml"


def _rows(res):
    return {r["id"]: r for r in res["scenarios"]}


def test_clean_scenarios_cost_nothing_and_errors_are_selected():
    res = bench.bench(SPEC, "scripted")
    rows = _rows(res)
    for sid in ("s0-rerun", "s1-typo", "s2-presentation"):
        assert rows[sid]["optimized"]["calls"] == 0, sid
    for sid in ("s3-evidence-contradicts", "s4-overview-contradicts", "s5-premise-changed", "s8-negation"):
        assert all(rows[sid]["optimized"]["selection"]), sid
    # global errors are only reachable through L2; without a trigger they are not selected
    assert rows["s7-unrecorded-dependency"]["optimized"]["selection"] == [False]
    t = res["totals"]
    assert t["optimized"]["calls"] < t["naive"]["calls"]
    assert t["naive"]["selection_recall"] == 1.0
    assert t["optimized"]["critical_error_recall"].startswith("not measured")


def test_forced_l2_selects_global_errors():
    rows = _rows(bench.bench(SPEC, "scripted", force_l2=True))
    assert rows["s7-unrecorded-dependency"]["optimized"]["selection"] == [True]
    assert all(rows["s6-overview-drops-disagreement"]["optimized"]["selection"])


def test_markdown_report_states_limits():
    md = bench.to_markdown(bench.bench(SPEC, "scripted"))
    assert "not a property of DDS" in md and "it is not detection" in md
