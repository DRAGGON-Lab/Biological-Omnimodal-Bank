"""A selected background control must actually supply a series in the channel it corrects.

A layout assignment does not prove a measurement exists. `preset_inputs._series` and
`rate_inputs._mean_at` index `series[p]` directly, unlike `analysis.background_correct`, so an
unread selection has to be refused by name, naming the well and the channel, before either reaches
the readings.

The plate below reads every well in both channels except two: H2 is missing from the absorbance
block and G2 from the fluorescence block. So one biomass control and one reporter control are
unread, each in a different channel, which is what separates the two cases.
"""
import datetime as dt
import math

from tests.conftest import signup
from tests.test_api import _project

ROWS = "ABCDEFGH"
PLATE = [f"{r}{c}" for r in ROWS for c in range(1, 13)]
SAMPLE_WELLS = ["A1", "A2"]
MEDIUM_WELLS = ["H1", "H2"]          # H2 is unread in the absorbance channel
HOST_WELLS = ["G1", "G2"]            # G2 is unread in the fluorescence channel
UNREAD_OD, UNREAD_FL = "H2", "G2"

N_READS, STEP_S = 17, 900
OD_OFF, FL_OFF = 450, 543
OD_BLANK, FL_BLANK = 0.080, 150.0
MU, PHI, B0, Y0 = 0.4, 100.0, 0.02, 5.0


def _b(h):
    return B0 * math.exp(MU * h)


def _y(h):
    return Y0 + (PHI * B0 / MU) * (math.exp(MU * h) - 1.0)


def _od(pos, k):
    h = (OD_OFF + k * STEP_S) / 3600
    return OD_BLANK + (_b(h) if pos in SAMPLE_WELLS + HOST_WELLS else 0.0)


def _fl(pos, k):
    h = (FL_OFF + k * STEP_S) / 3600
    return FL_BLANK + (_y(h) if pos in SAMPLE_WELLS else 0.0)


def _plate(unread_od: str = UNREAD_OD) -> bytes:
    """A Gen5 text export whose two blocks cover different well sets."""
    lines = [[], ["Software Version", "2.07.17"], [], ["Plate Number", "Plate 1"],
             ["Date", "2026-10-20"], ["Time", "09:00:00"], ["Reader Type:", "Synergy HTX"],
             ["Reader Serial Number:", "SYNTHETIC-1"], ["Plate Type", "96 flat bottom"], []]
    blocks = (("OD600:600", OD_OFF, _od, [p for p in PLATE if p != unread_od]),
              ("YFP:500/27,540/25", FL_OFF, _fl, [p for p in PLATE if p != UNREAD_FL]))
    for label, offset, fn, wells in blocks:
        lines += [[label], [], ["Time", f"T° {label}", *wells]]
        for k in range(N_READS):
            lines.append([str(dt.timedelta(seconds=offset + k * STEP_S)), "37",
                          *[f"{fn(p, k):.6f}" for p in wells]])
        lines.append([])
    return "\r\n".join("\t".join(c) for c in lines).encode("cp1252")


def _setup(client, email, unread_od: str = UNREAD_OD):
    """`unread_od` moves the absorbance gap, so it can fall on a measured well instead."""
    ws = signup(client, email)["workspaces"][0]
    _, study = _project(client, ws["id"])
    ctx = [{"role": "medium", "iri": "urn:LB"}]
    strain = [{"role": "strain", "iri": "urn:host"}]

    def make(name, kind, extra=()):
        return client.post(f"/api/studies/{study['id']}/samples",
                           json={"name": name, "sample_type": kind,
                                 "components": list(ctx) + list(extra)}).json()

    s = make("Reporter in LB", "sample", strain)
    med = make("LB blank", "medium")
    host = make("Untransformed in LB", "untransformed", strain)
    assay = client.post(f"/api/studies/{study['id']}/assays",
                        data={"name": "Gapped plate", "mapping_key": "biotek-gen5-kinetic-text"},
                        files={"file": ("gapped.txt", _plate(unread_od), "text/plain")}).json()
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments":
        {p: s["id"] for p in SAMPLE_WELLS} | {p: med["id"] for p in MEDIUM_WELLS}
        | {p: host["id"] for p in HOST_WELLS}})
    return study, assay, {"sample": s, "medium": med, "host": host}


def test_the_fixture_really_leaves_one_well_unread_in_each_channel(client):
    """Guard on the fixture itself: without this gap the regressions below prove nothing."""
    study, assay, ids = _setup(client, "i29-fixture@lab.test")
    raw = client.get(f"/api/assays/{assay['id']}/series",
                     params={"signal": "OD600", "correct": "false"}).json()
    od_wells = {p for g in raw["groups"] for p in g["positions"]}
    assert UNREAD_OD not in od_wells and "H1" in od_wells
    rawf = client.get(f"/api/assays/{assay['id']}/series",
                      params={"signal": "YFP", "correct": "false"}).json()
    fl_wells = {p for g in rawf["groups"] for p in g["positions"]}
    assert UNREAD_FL not in fl_wells and "G1" in fl_wells


def _preset(client, assay, ids, preset, **over):
    params = {"preset": preset, "wells": ",".join(SAMPLE_WELLS), "context_acknowledged": "true"}
    params.update(over)
    return client.get(f"/api/assays/{assay['id']}/preset-series", params=params)


def test_preset_biomass_control_unread_in_the_absorbance_channel_is_refused(client):
    study, assay, ids = _setup(client, "i29-preset-biomass@lab.test")
    r = _preset(client, assay, ids, "growth_curve", biomass_signal="OD600",
                biomass_controls=",".join(MEDIUM_WELLS))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert UNREAD_OD in detail and "no readings" in detail.lower(), detail


def test_preset_reporter_control_unread_in_the_fluorescence_channel_is_refused(client):
    study, assay, ids = _setup(client, "i29-preset-reporter@lab.test")
    r = _preset(client, assay, ids, "reporter_trajectory", signal="YFP",
                reporter_controls=",".join(HOST_WELLS))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert UNREAD_FL in detail and "no readings" in detail.lower(), detail


def test_preset_refuses_each_channel_independently(client):
    """A reporter control unread in fluorescence must not be excused by being read in absorbance."""
    study, assay, ids = _setup(client, "i29-preset-independent@lab.test")
    r = _preset(client, assay, ids, "reporter_per_biomass", signal="YFP", biomass_signal="OD600",
                biomass_controls="H1", reporter_controls=",".join(HOST_WELLS))
    assert r.status_code == 422, r.text
    assert UNREAD_FL in r.json()["detail"], r.text


def test_a_fully_unread_selected_group_is_refused_rather_than_correcting_against_nothing(client):
    study, assay, ids = _setup(client, "i29-allunread@lab.test")
    r = _preset(client, assay, ids, "growth_curve", biomass_signal="OD600",
                biomass_controls=UNREAD_OD)
    assert r.status_code == 422, r.text
    assert "no readings" in r.json()["detail"].lower(), r.text


def _rates(client, assay, **over):
    params = {"signal": "YFP", "biomass_signal": "OD600", "wells": ",".join(SAMPLE_WELLS),
              "biomass_controls": "H1", "reporter_controls": "G1",
              "context_acknowledged": "true"}
    params.update(over)
    return client.get(f"/api/assays/{assay['id']}/rates", params=params)


def test_rate_path_refuses_an_unread_biomass_control(client):
    study, assay, ids = _setup(client, "i29-rate-biomass@lab.test")
    r = _rates(client, assay, biomass_controls=",".join(MEDIUM_WELLS))
    assert r.status_code == 422, r.text
    assert UNREAD_OD in r.json()["detail"], r.text


def test_rate_path_refuses_an_unread_reporter_control(client):
    study, assay, ids = _setup(client, "i29-rate-reporter@lab.test")
    r = _rates(client, assay, reporter_controls=",".join(HOST_WELLS))
    assert r.status_code == 422, r.text
    assert UNREAD_FL in r.json()["detail"], r.text


def test_the_valid_case_still_works_and_an_unselected_unread_well_does_not_block_it(client):
    """H2 and G2 stay assigned and unread; selecting only the measured wells must succeed."""
    study, assay, ids = _setup(client, "i29-positive@lab.test")
    fit = _rates(client, assay)
    assert fit.status_code == 200, fit.text
    body = fit.json()
    pv = body["provenance"]
    assert pv["biomass_control_wells"] == ["H1"] and pv["reporter_control_wells"] == ["G1"]
    interior = body["growth"]["rate"][2:-2]
    assert max(abs(x - MU) for x in interior) < 0.02, interior

    series = _preset(client, assay, ids, "growth_curve", biomass_signal="OD600",
                     biomass_controls="H1")
    assert series.status_code == 200, series.text
    assert series.json()["provenance"]["biomass_control_wells"] == ["H1"]


def test_provenance_never_lists_a_control_that_supplied_no_series(client):
    """Provenance may only name controls that supplied a series. Pre-change the request crashed
    rather than reporting a false control list, so this guards the invariant, not a past claim."""
    study, assay, ids = _setup(client, "i29-provenance@lab.test")
    ok = _preset(client, assay, ids, "growth_curve", biomass_signal="OD600", biomass_controls="H1")
    assert ok.status_code == 200, ok.text
    assert UNREAD_OD not in ok.json()["provenance"]["biomass_control_wells"]
    refused = _preset(client, assay, ids, "growth_curve", biomass_signal="OD600",
                      biomass_controls=",".join(MEDIUM_WELLS))
    assert refused.status_code == 422, "an unread control must refuse, not be listed"


def test_the_refusal_holds_on_a_published_snapshot(client):
    """The check resolves against whichever source the version routing returned."""
    study, assay, ids = _setup(client, "i29-snapshot@lab.test")
    pub = client.post(f"/api/studies/{study['id']}/publish", json={
        "license": "CC-BY-4.0",
        "authors": [{"given_name": "Ada", "family_name": "Lovelace"}]})
    assert pub.status_code in (200, 201), pub.text

    frozen = client.get(f"/api/assays/{assay['id']}/rates", params={
        "signal": "YFP", "biomass_signal": "OD600", "wells": ",".join(SAMPLE_WELLS),
        "biomass_controls": ",".join(MEDIUM_WELLS), "reporter_controls": "G1",
        "context_acknowledged": "true", "version": 1})
    assert frozen.status_code == 422, frozen.text
    assert UNREAD_OD in frozen.json()["detail"], frozen.text

    ok = client.get(f"/api/assays/{assay['id']}/rates", params={
        "signal": "YFP", "biomass_signal": "OD600", "wells": ",".join(SAMPLE_WELLS),
        "biomass_controls": "H1", "reporter_controls": "G1",
        "context_acknowledged": "true", "version": 1})
    assert ok.status_code == 200, ok.text
    assert ok.json()["provenance"]["biomass_control_wells"] == ["H1"]
    assert ok.json()["provenance"]["layout_source"] == "frozen snapshot version 1"


def test_an_unread_measured_well_is_refused_rather_than_crashing(client):
    """A selected experimental well absent from a required channel must refuse, naming the well and
    the channel. Pre-change both paths returned HTTP 500; the selection is never silently shrunk."""
    study, assay, ids = _setup(client, "i29-measured@lab.test", unread_od="A2")
    r = _preset(client, assay, ids, "growth_curve", biomass_signal="OD600",
                biomass_controls=",".join(MEDIUM_WELLS))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "A2" in detail and "OD600" in detail and "measured" in detail, detail

    rates = _rates(client, assay)
    assert rates.status_code == 422, rates.text
    assert "A2" in rates.json()["detail"], rates.text


def test_an_unread_well_outside_the_selection_does_not_block_a_valid_request(client):
    """The gap stays on H2 and G2, both assigned and unread, and neither is selected here."""
    study, assay, ids = _setup(client, "i29-unselected@lab.test")
    r = _preset(client, assay, ids, "growth_curve", biomass_signal="OD600", biomass_controls="H1")
    assert r.status_code == 200, r.text
    assert r.json()["provenance"]["biomass_control_wells"] == ["H1"]
    fit = _rates(client, assay)
    assert fit.status_code == 200, fit.text
    interior = fit.json()["growth"]["rate"][2:-2]
    assert max(abs(x - MU) for x in interior) < 0.02, interior
