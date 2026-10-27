import pytest

from bob import analysis, fixtures
from tests.conftest import signup
from tests.test_api import _project, _upload


def _setup(client, email):
    ws = signup(client, email)["workspaces"][0]
    _, study = _project(client, ws["id"])
    ctx = [{"role": "medium", "iri": "urn:LB"}]

    def make(name, kind):
        return client.post(f"/api/studies/{study['id']}/samples",
                           json={"name": name, "sample_type": kind, "components": list(ctx)}).json()

    s, host, med = make("Reporter", "sample"), make("Host", "untransformed"), make("LB", "medium")
    assay = _upload(client, study["id"], fixtures.synthetic_gen5_workbook())
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments":
        {p: s["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
        | {p: med["id"] for p in fixtures.MEDIUM}})
    sig = client.get(f"/api/assays/{assay['id']}").json()["signals"]
    od = next(x["name"] for x in sig if x["kind"] == "absorbance")
    fl = next(x["name"] for x in sig if x["kind"] == "fluorescence")
    return study, assay, od, fl


def _q(**over):
    q = {"wells": ",".join(fixtures.CONSORTIUM),
         "biomass_controls": ",".join(fixtures.MEDIUM),
         "reporter_controls": ",".join(fixtures.UNTRANSFORMED),
         "context_acknowledged": "true"}
    q.update(over)
    return q


def test_a_growth_curve_needs_no_reporter_and_no_host(client):
    study, assay, od, fl = _setup(client, "growthonly@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="growth_curve", biomass_signal=od, reporter_controls=""))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"]["controls_required"] == ["biomass"]
    assert body["provenance"]["reporter_control_wells"] == []
    assert body["provenance"]["host_compatibility"] == "not applicable"
    assert any(v is not None for v in body["biomass"])


def test_a_growth_curve_still_needs_its_medium_controls(client):
    study, assay, od, fl = _setup(client, "nomedium@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="growth_curve", biomass_signal=od, biomass_controls=""))
    assert r.status_code == 422
    assert "medium" in r.json()["detail"]


def test_the_selected_controls_are_used_not_every_well_of_that_type(client):
    study, assay, od, fl = _setup(client, "explicit@lab.test")
    one = client.get(f"/api/assays/{assay['id']}/preset-series",
                     params=_q(preset="growth_curve", biomass_signal=od,
                               biomass_controls=fixtures.MEDIUM[0], reporter_controls="")).json()
    allthree = client.get(f"/api/assays/{assay['id']}/preset-series",
                          params=_q(preset="growth_curve", biomass_signal=od, reporter_controls="")).json()
    assert one["provenance"]["biomass_control_wells"] == [fixtures.MEDIUM[0]]
    assert allthree["provenance"]["biomass_control_wells"] == sorted(fixtures.MEDIUM)
    assert one["biomass"] != allthree["biomass"], "a different control set must change the correction"


def test_a_medium_well_cannot_be_the_reporter_background(client):
    study, assay, od, fl = _setup(client, "wrongctrl@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="reporter_trajectory", signal=fl,
                             reporter_controls=",".join(fixtures.MEDIUM)))
    assert r.status_code == 422
    assert "untransformed" in r.json()["detail"]


def test_a_reporter_trajectory_returns_raw_beside_corrected(client):
    study, assay, od, fl = _setup(client, "traj@lab.test")
    b = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="reporter_trajectory", signal=fl)).json()
    assert "reporter" in b and "reporter_raw" in b
    assert b["reporter"] != b["reporter_raw"]


def test_the_ratio_preset_says_what_it_is_not(client):
    study, assay, od, fl = _setup(client, "ratio@lab.test")
    b = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="reporter_per_biomass", signal=fl, biomass_signal=od)).json()
    assert "/" in b["ratio_unit"]
    assert any("not a production rate" in w.lower() for w in b["warnings"])


def test_mean_over_run_uses_the_selected_wells_and_names_its_units(client):
    study, assay, od, fl = _setup(client, "mean@lab.test")
    b = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="mean_over_run", signal=fl)).json()
    assert b["mean"] is not None and b["mean_unit"]
    assert b["aggregation"].startswith("arithmetic mean")
    assert b["provenance"]["wells"] == sorted(fixtures.CONSORTIUM)


def test_unacknowledged_unknown_host_is_refused_for_reporter_presets(client):
    study, assay, od, fl = _setup(client, "ack@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="reporter_trajectory", signal=fl, context_acknowledged="false"))
    assert r.status_code == 422
    assert "host compatibility is unknown" in r.json()["detail"].lower()


def test_a_well_cannot_be_both_measured_and_its_own_control(client):
    study, assay, od, fl = _setup(client, "overlap@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="growth_curve", biomass_signal=od,
                             biomass_controls=",".join(fixtures.CONSORTIUM), reporter_controls=""))
    assert r.status_code == 422
    assert "both measured and its own control" in r.json()["detail"]


def test_interpolation_keeps_missing_points_missing_and_counts_each_reason():
    """A gap is not bridged: an interval with a missing endpoint stays missing, and an exact
    timestamp is usable even when it is the only reading."""
    values, why = analysis.resample_onto([0.0, 1.0, 2.0, 3.0], [1.0, None, 3.0, 4.0],
                                         [-1.0, 0.0, 0.5, 1.0, 1.5, 2.5, 9.0])
    assert values == [None, 1.0, None, None, None, 3.5, None]
    assert why == ["missing_outside_support", "matched", "missing_bracket_reading",
                   "missing_source_reading", "missing_bracket_reading", "interpolated",
                   "missing_outside_support"]
    counts = analysis.alignment_counts(why)
    assert counts == {"target_points": 7, "points_matched_exactly": 1, "points_interpolated": 1,
                      "points_missing_outside_support": 2, "points_missing_source_reading": 1,
                      "points_missing_bracket_reading": 2}
    assert analysis.resample_onto([10.0], [5.0], [10.0, 11.0])[0] == [5.0, None]


def test_an_invalid_source_grid_is_refused_by_name():
    for bad, needle in (
        (([0.0, 1.0], [1.0], [0.5]), "the series has 1"),
        (([1.0, 1.0], [1.0, 2.0], [1.0]), "not strictly increasing"),
        (([0.0, float("nan")], [1.0, 2.0], [0.5]), "not a finite number"),
    ):
        with pytest.raises(ValueError) as e:
            analysis.resample_onto(*bad)
        assert needle in str(e.value), (needle, str(e.value))


def test_biomass_is_resampled_onto_the_reporter_clock_analytically():
    """Biomass rises linearly on its own clock, 93 s before each reporter reading. Pairing by index
    would hand the fit the biomass of 93 s earlier; the value at the reporter's timestamp is the
    line evaluated there."""
    bio_t = [450.0 + 600 * k for k in range(5)]
    bio = [0.1 + 0.01 * k for k in range(5)]
    rep_t = [543.0 + 600 * k for k in range(5)]
    got, why = analysis.resample_onto(bio_t, bio, rep_t)
    for k in range(4):
        assert got[k] == pytest.approx(0.1 + 0.01 * (k + (543.0 - 450.0) / 600))
        assert why[k] == "interpolated"
        assert got[k] > bio[k], "pairing by index would have returned the earlier, smaller reading"
    # the last reporter reading sits past the final biomass reading, so it has no support
    assert got[4] is None and why[4] == "missing_outside_support"




@pytest.mark.parametrize("preset,param", [
    ("reporter_trajectory", "signal"),
    ("mean_over_run", "signal"),
    ("growth_curve", "biomass_signal"),
])
def test_a_single_channel_preset_refuses_a_channel_in_the_wrong_role(client, plate_bytes, preset, param):
    """A single-channel preset refuses a channel in the wrong role, so an absorbance channel is
    never corrected against untransformed cells as if it were a reporter."""
    _, assay, od, fl = _setup(client, f"roles-{preset}@lab.test")
    wrong = od if param == "signal" else fl
    r = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset=preset, **{param: wrong}))
    assert r.status_code == 422, r.text
    assert "only this calculation is restricted" in r.json()["detail"], r.json()["detail"]


def test_a_preset_result_carries_its_raw_source_and_mapping_identity(client, plate_bytes):
    """A downloaded result has to say which file and which mapping produced it."""
    _, assay, od, fl = _setup(client, "source-identity@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/preset-series",
                   params=_q(preset="reporter_per_biomass", signal=fl, biomass_signal=od))
    assert r.status_code == 200, r.text
    src = r.json()["source"]
    assert src["assay_id"] == assay["id"]
    assert isinstance(src["raw_file_sha256"], str) and len(src["raw_file_sha256"]) == 64
    assert src["raw_file_name"] and src["mapping_key"] and src["mapping_version"] >= 1
    assert src["mapping_id"]
    # the alignment reasons the service derives must reach the caller, one per reported time
    body = r.json()
    assert len(body["biomass_alignment_per_point"]) == len(body["times_h"])
    assert set(body["biomass_alignment_per_point"]) <= {
        "matched", "interpolated", "missing_outside_support",
        "missing_source_reading", "missing_bracket_reading"}
    counts = body["provenance"]["biomass_alignment"]
    assert counts["target_points"] == len(body["times_h"])
