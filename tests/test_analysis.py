"""Golden values are worked out by hand from the synthetic plate described in bob/fixtures.py."""

import pytest

from bob import analysis, fixtures
from bob.mappings import load_builtin, parse_file


@pytest.fixture(scope="module")
def run():
    return parse_file(fixtures.synthetic_gen5_workbook(), load_builtin("biotek-gen5-kinetic"))


def _signal(run, name):
    return next(s for s in run.signals if s.name == name)


def test_background_is_the_mean_control_signal_at_each_time(run):
    yfp = _signal(run, "YFP")
    c = analysis.background_correct(yfp.times, yfp.values, fixtures.UNTRANSFORMED)
    assert c.background == [100.0] * fixtures.N_READS
    assert c.background_sd == [0.0] * fixtures.N_READS
    assert c.corrected["A2"] == [50.0 * k for k in range(fixtures.N_READS)]
    assert c.corrected["A1"][4] == 190.0


def test_points_below_background_are_flagged_and_optionally_dropped(run):
    od = _signal(run, "OD600")
    c = analysis.background_correct(od.times, od.values, fixtures.MEDIUM, threshold_sd=2.0, drop_below=True)
    # At k = 0 the culture reads exactly the medium blank, so it is background; from k = 1 it is above.
    assert c.below_threshold["A1"][:2] == [True, False]
    assert c.corrected["A1"][0] is None
    assert c.corrected["A1"][5] == pytest.approx(0.05)
    assert all(v is None for v in c.corrected["C5"])
    kept = analysis.background_correct(od.times, od.values, fixtures.MEDIUM, threshold_sd=2.0)
    assert kept.corrected["A1"][0] == pytest.approx(0.0) and kept.below_threshold["A1"][0] is True


def test_replicate_mean_and_sd(run):
    yfp = _signal(run, "YFP")
    corrected = analysis.background_correct(yfp.times, yfp.values, fixtures.UNTRANSFORMED).corrected
    (group,) = analysis.grouped_series(yfp.times, corrected, {"Consortium X": fixtures.CONSORTIUM})
    assert group.mean == pytest.approx([50.0 * k for k in range(fixtures.N_READS)])
    assert group.sd == pytest.approx([10.0] * fixtures.N_READS)
    assert group.n == [3] * fixtures.N_READS


def test_mean_expression_over_the_run(run):
    yfp = _signal(run, "YFP")
    corrected = analysis.background_correct(yfp.times, yfp.values, fixtures.UNTRANSFORMED).corrected
    per_well = {p: analysis.mean_expression(yfp.times, corrected[p]) for p in fixtures.CONSORTIUM}
    assert per_well == pytest.approx({"A1": 290.0, "A2": 300.0, "A3": 310.0})
    stats = analysis.group_stats(per_well, {"Consortium X": fixtures.CONSORTIUM})["Consortium X"]
    assert stats["mean"] == pytest.approx(300.0) and stats["sd"] == pytest.approx(10.0) and stats["n"] == 3


def test_mean_expression_per_od_skips_low_density_points(run):
    yfp, od = _signal(run, "YFP"), _signal(run, "OD600")
    f = analysis.background_correct(yfp.times, yfp.values, fixtures.UNTRANSFORMED).corrected["A2"]
    o = analysis.background_correct(od.times, od.values, fixtures.MEDIUM).corrected["A2"]
    o = analysis.align(od.times, o, yfp.times)
    # Corrected OD is 0.01k, so k < 5 falls under min_od = 0.05 and F/OD = 50k / 0.01k = 5000 elsewhere.
    assert analysis.mean_expression(yfp.times, f, o, min_od=0.05) == pytest.approx(5000.0)


def test_align_resamples_by_nearest_time():
    assert analysis.align([0, 10, 20], [1, 2, 3], [0, 9, 19, 21]) == [1, 2, 3, 3]
    assert analysis.align([0, 10], [], [0, 5]) == [None, None]


def test_controls_corrected_against_themselves_average_to_exactly_zero():
    values = {"H10": [80.1, 91.7], "H11": [79.7, 88.2], "H12": [80.2, 90.3]}
    corrected = analysis.background_correct([0.0, 600.0], values, list(values)).corrected
    (group,) = analysis.grouped_series([0.0, 600.0], corrected, {"Medium": list(values)})
    assert group.mean == [0.0, 0.0]
    per_well = {p: analysis.mean_expression([0.0, 600.0], s) for p, s in corrected.items()}
    assert analysis.group_stats(per_well, {"Medium": list(values)})["Medium"]["mean"] == 0.0


def test_align_is_fast_when_lengths_differ():
    import time

    src = [i * 10.0 for i in range(2000)]
    dst = [i * 10.0 + 3 for i in range(1999)]
    t0 = time.perf_counter()
    out = analysis.align(src, list(range(2000)), dst)
    assert time.perf_counter() - t0 < 0.5
    assert out[:3] == [0, 1, 2] and out[-1] == 1998


def test_zero_or_negative_od_never_divides():
    assert analysis.mean_expression([0, 1, 2], [5.0, 5.0, 6.0], [0.0, -0.1, 0.2], min_od=0.0) == pytest.approx(30.0)
