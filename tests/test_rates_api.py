import pytest

from bob import fixtures
from tests.conftest import signup
from tests.test_api import _project, _samples, _upload


def _assay(client, plate_bytes):
    ws = signup(client, "rates@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    samples = _samples(client, study["id"])
    assay = _upload(client, study["id"], plate_bytes)
    assign = {p: samples["consortium"]["id"] for p in fixtures.CONSORTIUM}
    assign |= {p: samples["host"]["id"] for p in fixtures.UNTRANSFORMED}
    assign |= {p: samples["medium"]["id"] for p in fixtures.MEDIUM}
    other = client.post(f"/api/studies/{study['id']}/samples",
                        json={"name": "Strain Y", "sample_type": "sample",
                              "components": [{"role": "strain", "iri": "https://sbh.test/y/1"}]}).json()
    assign |= {p: other["id"] for p in fixtures.STRAIN_Y}
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assign})
    return assay, client.get(f"/api/assays/{assay['id']}").json()["signals"]


def _of_kind(signals, kind):
    """Pick a channel by its recorded kind; the fixture's read order is OD600, CFP, YFP, so a
    positional choice silently swaps the reporter and the biomass proxy."""
    return next(s["name"] for s in signals if s["kind"] == kind)


def _query(signals, **over):
    q = {
        "signal": _of_kind(signals, "fluorescence"),
        "biomass_signal": _of_kind(signals, "absorbance"),
        "wells": ",".join(fixtures.CONSORTIUM),
        "biomass_controls": ",".join(fixtures.MEDIUM),
        "reporter_controls": ",".join(fixtures.UNTRANSFORMED),
    }
    q["context_acknowledged"] = "true"
    q.update(over)
    return q


def test_the_rates_endpoint_returns_both_profiles_with_provenance(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "gaussian-basis-inverse"
    assert body["growth"]["unit"] == "1/h"
    assert "/" in body["production"]["unit"] and "*h)" in body["production"]["unit"]
    assert body["provenance"]["biomass_control_wells"] == sorted(fixtures.MEDIUM)
    assert body["provenance"]["reporter_control_wells"] == sorted(fixtures.UNTRANSFORMED)
    assert len(body["growth"]["rate"]) == len(body["growth"]["times_h"])
    assert body["growth"]["diagnostics"]["time_unit"] == "h"


def test_a_medium_well_cannot_stand_in_for_reporter_negative_cells(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates",
                   params=_query(signals, reporter_controls=",".join(fixtures.MEDIUM)))
    assert r.status_code == 422
    assert "not a substitute" in r.json()["detail"]


def test_unassigned_control_wells_are_refused(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals, biomass_controls="Z9"))
    assert r.status_code == 422
    assert "not assigned" in r.json()["detail"]


def test_a_single_control_well_is_warned_about(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates",
                   params=_query(signals, biomass_controls=fixtures.MEDIUM[0]))
    assert r.status_code == 200, r.text
    assert any("control spread cannot be estimated" in w for w in r.json()["warnings"])


def test_an_unknown_signal_is_refused(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals, signal="NoSuchChannel"))
    assert r.status_code == 422
    assert "no signal named" in r.json()["detail"]


def test_a_well_cannot_be_both_sample_and_its_own_control(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates",
                   params=_query(signals, wells=",".join(fixtures.MEDIUM), biomass_controls=",".join(fixtures.MEDIUM)))
    assert r.status_code == 422
    assert "both a measured sample and its own control" in r.json()["detail"]


def test_wells_spanning_two_samples_are_refused(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    mixed = ",".join([fixtures.CONSORTIUM[0], fixtures.STRAIN_Y[0]])
    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals, wells=mixed))
    assert r.status_code == 422
    assert "more than one sample" in r.json()["detail"]


def test_unknown_context_is_refused_until_explicitly_acknowledged(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates",
                   params=_query(signals, context_acknowledged="false"))
    assert r.status_code == 422
    # host compatibility is unknown by construction, so it is refused before the chemical check
    assert "Host compatibility is unknown" in r.json()["detail"]
    ok = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals))
    assert ok.status_code == 200
    assert ok.json()["provenance"]["context_acknowledged_by_user"] is True
    assert ok.json()["provenance"]["context_checked"] is False
    assert ok.json()["provenance"]["host_compatibility"] == "unknown"


def test_an_inducer_dose_mismatch_is_rejected(client, plate_bytes):
    ws = signup(client, "dose@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])

    def make(name, kind, iptg_mM):
        comps = [{"role": "medium", "iri": "urn:LB"},
                 {"role": "inducer", "iri": "urn:IPTG", "amount": iptg_mM, "unit": "mM"}]
        return client.post(f"/api/studies/{study['id']}/samples",
                           json={"name": name, "sample_type": kind, "components": comps}).json()

    induced = make("Induced", "sample", 1.0)
    blank = make("Medium LB no IPTG", "medium", 0.0)
    host = make("Host", "untransformed", 1.0)
    assay = _upload(client, study["id"], plate_bytes)
    assign = {p: induced["id"] for p in fixtures.CONSORTIUM}
    assign |= {p: blank["id"] for p in fixtures.MEDIUM}
    assign |= {p: host["id"] for p in fixtures.UNTRANSFORMED}
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assign})
    signals = client.get(f"/api/assays/{assay['id']}").json()["signals"]

    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals))
    assert r.status_code == 422, r.text
    assert "does not match the sample's medium and supplement context" in r.json()["detail"]


def test_host_compatibility_stays_unknown_even_when_the_medium_matches(client, plate_bytes):
    ws = signup(client, "host@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    ctx = [{"role": "medium", "iri": "urn:LB"}]

    def make(name, kind, strain):
        return client.post(f"/api/studies/{study['id']}/samples",
                           json={"name": name, "sample_type": kind,
                                 "components": ctx + [{"role": "strain", "iri": strain}]}).json()

    s = make("Reporter", "sample", "https://sbh.test/eng/1")
    h = make("Host", "untransformed", "https://sbh.test/host/1")
    m = client.post(f"/api/studies/{study['id']}/samples",
                    json={"name": "LB", "sample_type": "medium", "components": ctx}).json()
    assay = _upload(client, study["id"], plate_bytes)
    assign = {p: s["id"] for p in fixtures.CONSORTIUM}
    assign |= {p: h["id"] for p in fixtures.UNTRANSFORMED}
    assign |= {p: m["id"] for p in fixtures.MEDIUM}
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assign})
    signals = client.get(f"/api/assays/{assay['id']}").json()["signals"]

    refused = client.get(f"/api/assays/{assay['id']}/rates",
                         params=_query(signals, context_acknowledged="false"))
    assert refused.status_code == 422
    assert "Host compatibility is unknown" in refused.json()["detail"]

    ok = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals))
    assert ok.status_code == 200, ok.text
    prov = ok.json()["provenance"]
    assert prov["context_checked"] is True
    assert prov["host_compatibility"] == "unknown"


def test_a_frozen_version_keeps_its_own_layout_when_the_live_one_diverges(client, plate_bytes):
    ws = signup(client, "frozen@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    ctx = [{"role": "medium", "iri": "urn:LB"}]

    def make(name, kind):
        return client.post(f"/api/studies/{study['id']}/samples",
                           json={"name": name, "sample_type": kind, "components": list(ctx)}).json()

    s, host, med = make("Reporter", "sample"), make("Host", "untransformed"), make("LB", "medium")
    assay = _upload(client, study["id"], plate_bytes)
    assign = {p: s["id"] for p in fixtures.CONSORTIUM}
    assign |= {p: host["id"] for p in fixtures.UNTRANSFORMED}
    assign |= {p: med["id"] for p in fixtures.MEDIUM}
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assign})
    signals = client.get(f"/api/assays/{assay['id']}").json()["signals"]

    pub = client.post(f"/api/studies/{study['id']}/publish",
                      json={"license": "CC-BY-4.0",
                            "authors": [{"given_name": "Ada", "family_name": "Lovelace"}]})
    assert pub.status_code == 200, pub.text

    frozen = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals, version=1))
    assert frozen.status_code == 200, frozen.text
    before = frozen.json()
    assert before["provenance"]["snapshot_version"] == 1
    assert "frozen snapshot version 1" in before["provenance"]["layout_source"]

    # now diverge the live layout: the sample's wells become medium
    client.put(f"/api/assays/{assay['id']}/layout",
               json={"assignments": {p: med["id"] for p in fixtures.CONSORTIUM} | {
                   p: host["id"] for p in fixtures.UNTRANSFORMED} | {
                   p: med["id"] for p in fixtures.MEDIUM}})

    again = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals, version=1))
    assert again.status_code == 200, again.text
    after = again.json()
    assert after["provenance"]["snapshot_version"] == 1
    assert after["growth"]["rate"] == before["growth"]["rate"]
    assert after["production"]["rate"] == before["production"]["rate"]
    assert after["provenance"]["wells"] == before["provenance"]["wells"]


def test_the_frozen_snapshot_still_carries_component_metadata(client, plate_bytes):
    ws = signup(client, "frozenctx@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])

    def make(name, kind, iptg):
        return client.post(f"/api/studies/{study['id']}/samples", json={
            "name": name, "sample_type": kind,
            "components": [{"role": "medium", "iri": "urn:LB"},
                           {"role": "inducer", "iri": "urn:IPTG", "amount": iptg, "unit": "mM"}]}).json()

    s, host, med = make("Induced", "sample", 1.0), make("Host", "untransformed", 1.0), make("LB", "medium", 0.0)
    assay = _upload(client, study["id"], plate_bytes)
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments":
        {p: s["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
        | {p: med["id"] for p in fixtures.MEDIUM}})
    signals = client.get(f"/api/assays/{assay['id']}").json()["signals"]
    client.post(f"/api/studies/{study['id']}/publish",
                json={"license": "CC0-1.0", "authors": [{"given_name": "Ada", "family_name": "Lovelace"}]})

    # the dose mismatch must still be caught through the frozen snapshot
    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals, version=1))
    assert r.status_code == 422, r.text
    assert "does not match the sample's medium and supplement context" in r.json()["detail"]


def test_the_export_carries_standalone_reproducible_provenance(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals))
    assert r.status_code == 200, r.text
    src = r.json()["source"]
    assert src["assay_id"] == assay["id"]
    assert src["reporter_signal"] == _of_kind(signals, "fluorescence")
    assert src["biomass_signal"] == _of_kind(signals, "absorbance")
    assert src["reporter_unit"] and src["biomass_unit"]
    assert isinstance(src["raw_file_sha256"], str) and len(src["raw_file_sha256"]) == 64


def test_the_supported_reporter_and_biomass_pair_is_accepted(client, plate_bytes):
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates", params=_query(signals))
    assert r.status_code == 200, r.text
    assert r.json()["source"]["reporter_signal"] == _of_kind(signals, "fluorescence")


@pytest.mark.parametrize("roles,needle", [
    (("fluorescence", "fluorescence"), "reads one reporter against a separate biomass proxy"),
    (("absorbance", "absorbance"), "reads one reporter against a separate biomass proxy"),
    (("absorbance", "fluorescence"), "reads the reporter from a fluorescence channel"),
])
def test_an_unsupported_channel_role_pairing_is_refused_by_the_api(client, plate_bytes, roles, needle):
    """The GUI restricts the selectors, so only the API can be asked for these pairings."""
    assay, signals = _assay(client, plate_bytes)
    r = client.get(f"/api/assays/{assay['id']}/rates",
                   params=_query(signals, signal=_of_kind(signals, roles[0]),
                                 biomass_signal=_of_kind(signals, roles[1])))
    assert r.status_code == 422, r.text
    assert needle in r.json()["detail"], r.json()["detail"]


def test_two_distinct_fluorescence_channels_are_still_refused_as_a_pair(client, plate_bytes):
    """Distinctness is not sufficient: a second reporter is not a biomass proxy."""
    assay, signals = _assay(client, plate_bytes)
    fluors = [s["name"] for s in signals if s["kind"] == "fluorescence"]
    assert len(fluors) >= 2, signals
    r = client.get(f"/api/assays/{assay['id']}/rates",
                   params=_query(signals, signal=fluors[0], biomass_signal=fluors[1]))
    assert r.status_code == 422, r.text
    assert "reads the biomass proxy from an absorbance channel" in r.json()["detail"]
