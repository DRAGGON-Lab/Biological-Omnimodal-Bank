"""The Time series and Mean signal over run panels must correct against the controls the user
selected, not every well of a control type on the plate.

The plate here carries two medium groups with deliberately different, exactly representable
backgrounds, so pooling and explicit selection give different numbers and the difference is
arithmetic rather than a matter of float tolerance.
"""
import datetime as dt

import pytest

from tests.conftest import signup
from tests.test_api import _project

ROWS = "ABCDEFGH"
PLATE = [f"{r}{c}" for r in ROWS for c in range(1, 13)]
SAMPLE_WELLS = ["A1", "A2"]
MED_LB_WELLS = ["H1", "H2"]
MED_M9_WELLS = ["B1", "B2"]
HOST_LB_WELLS = ["G1", "G2"]

# exactly representable in binary, so every expected value below is exact
OD_SAMPLE, OD_MED_LB, OD_MED_M9, OD_HOST = 0.5, 0.25, 0.125, 0.375
FL_SAMPLE, FL_HOST_LB, FL_MED = 8.0, 2.0, 1.0

# What the numbers mean, worked out by hand and not from the implementation:
#   explicit LB medium only : background 0.25         -> 0.5 - 0.25    = 0.25
#   pooled over both media  : background (0.25+0.125)/2 = 0.1875
#                                                      -> 0.5 - 0.1875 = 0.3125
EXPECTED_EXPLICIT = 0.25
EXPECTED_POOLED = 0.3125


def _plate(od_m9: float = OD_MED_M9) -> bytes:
    """A two-read Gen5 text export whose every well holds a constant value."""
    od = dict.fromkeys(PLATE, 0.05)
    fl = dict.fromkeys(PLATE, 0.5)
    for p in SAMPLE_WELLS:
        od[p], fl[p] = OD_SAMPLE, FL_SAMPLE
    for p in MED_LB_WELLS:
        od[p], fl[p] = OD_MED_LB, FL_MED
    for p in MED_M9_WELLS:
        od[p], fl[p] = od_m9, FL_MED
    for p in HOST_LB_WELLS:
        od[p], fl[p] = OD_HOST, FL_HOST_LB

    lines = [[], ["Software Version", "2.07.17"], [], ["Plate Number", "Plate 1"],
             ["Date", "2026-10-20"], ["Time", "03:00:00"], ["Reader Type:", "Synergy HTX"],
             ["Reader Serial Number:", "SYNTHETIC-2"], ["Plate Type", "96 flat bottom"], []]
    for label, offset, table in (("OD600:600", 450, od), ("YFP:500/27,540/25", 543, fl)):
        lines += [[label], [], ["Time", f"T° {label}", *PLATE]]
        for k in range(2):
            lines.append([str(dt.timedelta(seconds=offset + k * 900)), "37",
                          *[f"{table[p]:.6f}" for p in PLATE]])
        lines.append([])
    return "\r\n".join("\t".join(c) for c in lines).encode("cp1252")


def _setup(client, email, od_m9: float = OD_MED_M9):
    ws = signup(client, email)["workspaces"][0]
    _, study = _project(client, ws["id"])
    lb = [{"role": "medium", "iri": "urn:LB"}]
    m9 = [{"role": "medium", "iri": "urn:M9"}]

    def make(name, kind, ctx, extra=()):
        return client.post(f"/api/studies/{study['id']}/samples",
                           json={"name": name, "sample_type": kind,
                                 "components": list(ctx) + list(extra)}).json()

    s = make("Reporter in LB", "sample", lb, [{"role": "strain", "iri": "urn:host"}])
    med_lb = make("LB blank", "medium", lb)
    med_m9 = make("M9 blank", "medium", m9)
    host_lb = make("Untransformed in LB", "untransformed", lb, [{"role": "strain", "iri": "urn:host"}])

    files = {"file": ("plate.txt", _plate(od_m9), "text/plain")}
    assay = client.post(f"/api/studies/{study['id']}/assays",
                        data={"name": "Mixed media", "mapping_key": "biotek-gen5-kinetic-text"},
                        files=files).json()
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments":
        {p: s["id"] for p in SAMPLE_WELLS} | {p: med_lb["id"] for p in MED_LB_WELLS}
        | {p: med_m9["id"] for p in MED_M9_WELLS} | {p: host_lb["id"] for p in HOST_LB_WELLS}})
    return study, assay, {"sample": s, "med_lb": med_lb, "med_m9": med_m9, "host_lb": host_lb}


def _group(body, sample_id):
    return next(g for g in body["groups"] if g["sample_id"] == sample_id)


def test_series_corrects_against_the_selected_medium_not_every_medium(client):
    """The regression. Pre-change this returns the pooled value and fails on the number."""
    study, assay, ids = _setup(client, "i27-series@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"],
        "controls": ",".join(MED_LB_WELLS), "context_acknowledged": "false"})
    assert r.status_code == 200, r.text
    body = r.json()
    got = _group(body, ids["sample"]["id"])["mean"][0]
    assert got == pytest.approx(EXPECTED_EXPLICIT), (
        f"corrected against the selected LB blanks the sample reads {EXPECTED_EXPLICIT}; "
        f"pooling both media would read {EXPECTED_POOLED}; got {got}")
    assert body["control_positions"] == sorted(MED_LB_WELLS)


def test_an_unselected_incompatible_control_cannot_move_the_result(client):
    """Same selection, a different value in the unselected M9 blank: the answer must not move."""
    out = []
    for email, od_m9 in (("i27-move-a@lab.test", OD_MED_M9), ("i27-move-b@lab.test", 0.0625)):
        _study, assay, ids = _setup(client, email, od_m9=od_m9)
        r = client.get(f"/api/assays/{assay['id']}/series", params={
            "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"],
            "controls": ",".join(MED_LB_WELLS)})
        assert r.status_code == 200, r.text
        out.append(_group(r.json(), ids["sample"]["id"])["mean"][0])
    assert out[0] == pytest.approx(EXPECTED_EXPLICIT)
    assert out[0] == pytest.approx(out[1]), (
        "the unselected M9 blank changed the selected sample's correction, so the "
        "correction is still pooling by sample type")


def test_mean_expression_corrects_against_the_selected_medium(client):
    study, assay, ids = _setup(client, "i27-mean@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/mean-expression", params={
        "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"],
        "controls": ",".join(MED_LB_WELLS)})
    assert r.status_code == 200, r.text
    got = _group(r.json(), ids["sample"]["id"])["mean"]
    assert got == pytest.approx(EXPECTED_EXPLICIT), (
        f"expected {EXPECTED_EXPLICIT} against the selected LB blanks, "
        f"{EXPECTED_POOLED} if pooled; got {got}")


def test_correcting_a_mixed_media_plate_as_a_whole_is_refused(client):
    """Every reported group must be compatible, so a mixed plate must be narrowed, not pooled."""
    study, assay, ids = _setup(client, "i27-mixed@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "true", "controls": ",".join(MED_LB_WELLS)})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "both measured and its own control" in detail or "does not share" in detail, detail


def test_correction_without_selected_controls_is_refused_not_silently_raw(client):
    study, assay, ids = _setup(client, "i27-noctl@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"]})
    assert r.status_code == 422, r.text
    assert "select explicit medium control wells" in r.json()["detail"]


def test_raw_mode_needs_no_controls_and_says_it_is_raw(client):
    study, assay, ids = _setup(client, "i27-raw@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "false", "samples": ids["sample"]["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["corrected"] is False and body["control_positions"] == []
    assert _group(body, ids["sample"]["id"])["mean"][0] == pytest.approx(OD_SAMPLE)


def test_a_foreign_or_unassigned_control_well_is_refused(client):
    study, assay, ids = _setup(client, "i27-foreign@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"], "controls": "L24"})
    assert r.status_code == 422, r.text
    assert "not assigned in the plate map" in r.json()["detail"]


def test_a_sample_well_cannot_serve_as_the_background(client):
    study, assay, ids = _setup(client, "i27-wrongtype@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"],
        "controls": ",".join(HOST_LB_WELLS)})
    assert r.status_code == 422, r.text
    assert "the measured background needs 'medium' wells" in r.json()["detail"]


def test_a_reporter_needs_untransformed_cells_and_an_acknowledgement(client):
    """Host compatibility is unknown from metadata, so it needs the explicit acknowledgement."""
    study, assay, ids = _setup(client, "i27-reporter@lab.test")
    params = {"signal": "YFP", "correct": "true", "samples": ids["sample"]["id"],
              "controls": ",".join(HOST_LB_WELLS)}
    refused = client.get(f"/api/assays/{assay['id']}/series", params=params)
    assert refused.status_code == 422, refused.text
    assert "host compatibility is unknown" in refused.json()["detail"]

    ok = client.get(f"/api/assays/{assay['id']}/series",
                    params={**params, "context_acknowledged": "true"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["provenance"]["host_compatibility"] == "unknown"
    assert body["provenance"]["context_acknowledged_by_user"] is True
    assert _group(body, ids["sample"]["id"])["mean"][0] == pytest.approx(FL_SAMPLE - FL_HOST_LB)


def test_a_known_context_mismatch_is_not_overridden_by_acknowledgement(client):
    study, assay, ids = _setup(client, "i27-mismatch@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"],
        "controls": ",".join(MED_M9_WELLS), "context_acknowledged": "true"})
    assert r.status_code == 422, r.text
    assert "does not share the sample's medium and supplement context" in r.json()["detail"]


def test_normalisation_controls_are_validated_separately(client):
    study, assay, ids = _setup(client, "i27-norm@lab.test")
    base = {"signal": "YFP", "correct": "true", "samples": ids["sample"]["id"],
            "controls": ",".join(HOST_LB_WELLS), "context_acknowledged": "true",
            "normalize_by": "OD600", "min_od": "0"}
    missing = client.get(f"/api/assays/{assay['id']}/series", params=base)
    assert missing.status_code == 422, missing.text
    assert "normalisation background" in missing.json()["detail"]

    mismatched = client.get(f"/api/assays/{assay['id']}/series",
                            params={**base, "normalize_controls": ",".join(MED_M9_WELLS)})
    assert mismatched.status_code == 422, mismatched.text

    ok = client.get(f"/api/assays/{assay['id']}/series",
                    params={**base, "normalize_controls": ",".join(MED_LB_WELLS)})
    assert ok.status_code == 200, ok.text
    assert ok.json()["provenance"]["normalisation_control_wells"] == sorted(MED_LB_WELLS)


def test_an_unassigned_sample_selection_is_refused(client):
    study, assay, ids = _setup(client, "i27-badsample@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "false", "samples": "not-a-sample"})
    assert r.status_code == 422, r.text
    assert "not assigned to any well" in r.json()["detail"]


def test_an_absorbance_background_makes_no_host_claim(client):
    """Medium blanks hold no cells, so host compatibility does not apply to them."""
    study, assay, ids = _setup(client, "i27-nohost@lab.test")
    r = client.get(f"/api/assays/{assay['id']}/series", params={
        "signal": "OD600", "correct": "true", "samples": ids["sample"]["id"],
        "controls": ",".join(MED_LB_WELLS)})
    assert r.status_code == 200, r.text
    pv = r.json()["provenance"]
    assert pv["host_compatibility"] == "not applicable", pv
    assert pv["context_unknown_wells"] == []


def test_a_control_unread_in_the_corrected_channel_is_refused():
    """`background_correct` drops positions it has no series for, so a well that is assigned in the
    layout but unread in this channel must refuse rather than be reported as the background while
    contributing nothing to it. Every well of the plate fixture is read in both channels, so the
    guard is exercised directly."""
    from bob import services

    comp = type("C", (), {"role": "medium", "iri": "urn:LB", "amount": None, "unit": None})()

    def well(sid, name, kind):
        return type("S", (), {"id": sid, "name": name, "sample_type": kind,
                              "components": [comp]})()

    layout = {"A1": well("a", "Sample", "sample"),
              "H1": well("m", "LB blank", "medium"),
              "H2": well("m", "LB blank", "medium")}
    measured = {"a": ["A1"]}
    with pytest.raises(ValueError, match="no readings in this channel"):
        services.check_controls(layout, measured, ["H1", "H2"], "medium", "measured",
                                context_acknowledged=True, available={"A1", "H2"})
    assert services.check_controls(layout, measured, ["H1", "H2"], "medium", "measured",
                                   context_acknowledged=True,
                                   available={"A1", "H1", "H2"}) == ([], [])
