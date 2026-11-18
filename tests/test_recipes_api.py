from bob import fixtures
from tests.conftest import signup
from tests.test_api import _project, _upload


def _study_with_assay(client, email="recipes@lab.test"):
    ws = signup(client, email)["workspaces"][0]
    _, study = _project(client, ws["id"])
    ctx = [{"role": "medium", "iri": "urn:LB"}]

    def make(name, kind):
        return client.post(f"/api/studies/{study['id']}/samples",
                           json={"name": name, "sample_type": kind, "components": list(ctx)}).json()

    s, host, med = make("Reporter", "sample"), make("Host", "untransformed"), make("LB", "medium")
    return study, s, host, med


def _assay_for(client, study, s, host, med, plate_bytes):
    assay = _upload(client, study["id"], plate_bytes)
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments":
        {p: s["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
        | {p: med["id"] for p in fixtures.MEDIUM}})
    signals = client.get(f"/api/assays/{assay['id']}").json()["signals"]
    return assay, signals


def _pick(signals, kind):
    return next(s["name"] for s in signals if s["kind"] == kind)


def _fingerprint(client, assay, signals):
    """The source identity the server hands back with a completed figure."""
    r = client.get(f"/api/assays/{assay['id']}/preset-series", params={
        "preset": "growth_curve", "wells": ",".join(fixtures.CONSORTIUM),
        "biomass_signal": _pick(signals, "absorbance"),
        "biomass_controls": ",".join(fixtures.MEDIUM), "context_acknowledged": "true"})
    return r.json()["source_fingerprint"]


def _body(client, assay, signals, s, host, med, name="My figure"):
    return {"name": name, "preset": "rate_profiles", "assay_id": assay["id"],
            "reporter_unit": "RFU", "biomass_unit": "OD",
            "analysis_method": "gaussian-basis-inverse", "analysis_method_version": "1",
            "source_fingerprint": _fingerprint(client, assay, signals),
            "config": {"reporter_signal": _pick(signals, "fluorescence"),
                       "biomass_signal": _pick(signals, "absorbance"),
                       "sample_id": s["id"], "biomass_control_id": med["id"], "reporter_control_id": host["id"]}}


def test_presets_are_listed_with_their_measurement_wording(client):
    signup(client, "presets@lab.test")
    r = client.get("/api/presets")
    assert r.status_code == 200
    keys = {p["key"] for p in r.json()["presets"]}
    assert keys == {"growth_curve", "reporter_trajectory", "reporter_per_biomass", "rate_profiles", "mean_over_run"}
    per_biomass = next(p for p in r.json()["presets"] if p["key"] == "reporter_per_biomass")
    assert "not a production rate" in per_biomass["measurement"] + " " + per_biomass["caveat"]
    assert "not a production rate" not in per_biomass["measurement"], "a caveat belongs in the tooltip"


def test_a_recipe_saves_and_reopens(client, plate_bytes):
    study, s, host, med = _study_with_assay(client)
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    r = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med))
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["layout_fingerprint"] and rec["source"]["raw_file_sha256"]

    again = client.get(f"/api/recipes/{rec['id']}")
    assert again.status_code == 200
    body = again.json()
    assert body["reproducible"] is True and body["stale_reason"] == ""
    assert body["config"]["sample_id"] == s["id"]
    assert "wells" not in body["config"]
    assert client.get(f"/api/studies/{study['id']}/recipes").json()["recipes"][0]["id"] == rec["id"]


def test_a_changed_layout_makes_a_recipe_not_reproducible(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "stale@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    rec = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med)).json()
    assert client.get(f"/api/recipes/{rec['id']}").json()["reproducible"] is True

    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments":
        {p: med["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
        | {p: med["id"] for p in fixtures.MEDIUM}})
    after = client.get(f"/api/recipes/{rec['id']}").json()
    assert after["reproducible"] is False
    assert "layout or sample metadata changed" in after["stale_reason"]
    assert after["config"] == rec["config"], "the saved recipe itself must be preserved"


def test_a_duplicate_name_in_one_study_is_refused(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "dup@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    assert client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med)).status_code == 201
    second = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med))
    assert second.status_code == 409


def test_an_incomplete_preset_selection_is_refused(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "incomplete@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med)
    body["config"].pop("biomass_signal")
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422 and "biomass_signal" in r.json()["detail"]


def test_another_users_private_study_is_not_readable(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "owner@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    rec = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med)).json()
    client.post("/api/auth/signout")
    signup(client, "stranger@lab.test")
    assert client.get(f"/api/recipes/{rec['id']}").status_code in (403, 404)
    assert client.get(f"/api/studies/{study['id']}/recipes").status_code in (403, 404)


def test_reuse_offers_a_mapping_and_leaves_the_original_untouched(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "reuse@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    rec = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med)).json()

    s2 = client.post(f"/api/studies/{study['id']}/samples",
                     json={"name": "Second reporter", "sample_type": "sample",
                           "components": [{"role": "medium", "iri": "urn:LB"}]}).json()
    assay2 = _upload(client, study["id"], plate_bytes)
    client.put(f"/api/assays/{assay2['id']}/layout", json={"assignments":
        {p: s2["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
        | {p: med["id"] for p in fixtures.MEDIUM}})

    t = client.get(f"/api/recipes/{rec['id']}/reuse", params={"assay_id": assay2["id"]})
    assert t.status_code == 200, t.text
    body = t.json()
    assert body["requires_fresh_acknowledgement"] is True
    for gone in ("sample_id", "biomass_control_id", "reporter_control_id"):
        assert body["template"].get(gone) is None
    assert body["template"]["reporter_signal"] == _pick(signals, "fluorescence")
    assert {c["id"] for c in body["choices"]["sample"]} >= {s2["id"]}
    assert client.get(f"/api/recipes/{rec['id']}").json()["config"] == rec["config"]


def _two_channel_plate() -> bytes:
    """A Gen5 text export with OD600 and YFP only, so a CFP recipe cannot map onto it."""
    import datetime as dt
    plate = [f"{r}{c}" for r in "ABCDEFGH" for c in range(1, 13)]
    lines = [[], ["Software Version", "2.07.17"], [], ["Plate Number", "Plate 1"],
             ["Date", "2026-10-20"], ["Time", "09:00:00"], ["Reader Type:", "Synergy HTX"],
             ["Reader Serial Number:", "TWOCHAN"], ["Plate Type", "96 flat bottom"], []]
    for label, offset in (("OD600:600", 450), ("YFP:500/27,540/25", 543)):
        lines += [[label], [], ["Time", f"T\u00b0 {label}", *plate]]
        for k in range(12):
            lines.append([str(dt.timedelta(seconds=offset + k * 900)), "37", *["0.250" for _ in plate]])
        lines.append([])
    return "\r\n".join("\t".join(c) for c in lines).encode("cp1252")


def test_reuse_reports_a_missing_channel(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "chan@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    assert any(s["name"] == "CFP" for s in signals), "the three-channel fixture should offer CFP"
    body = _body(client, assay, signals, s, host, med)
    body["config"]["reporter_signal"] = "CFP"
    rec = client.post(f"/api/studies/{study['id']}/recipes", json=body).json()

    files = {"file": ("two.txt", _two_channel_plate(), "text/plain")}
    assay2 = client.post(f"/api/studies/{study['id']}/assays",
                         data={"name": "Two channel", "mapping_key": "biotek-gen5-kinetic-text"},
                         files=files).json()
    client.put(f"/api/assays/{assay2['id']}/layout", json={"assignments":
        {p: s["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
        | {p: med["id"] for p in fixtures.MEDIUM}})

    t = client.get(f"/api/recipes/{rec['id']}/reuse", params={"assay_id": assay2["id"]}).json()
    assert any("no channel named 'CFP'" in p for p in t["problems"]), t["problems"]
    assert t["template"]["reporter_signal"] is None
    assert client.get(f"/api/recipes/{rec['id']}").json()["config"]["reporter_signal"] == "CFP"


def test_the_api_refuses_a_markup_preview(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "preview@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Markup")
    body["preview"] = "<svg onload=\"fetch('/api/studies')\"></svg>"
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422
    assert "markup" in r.json()["detail"]


def test_a_numeric_preview_is_stored_and_returned(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "numpreview@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Numeric")
    body["preview"] = [{"label": "Growth rate", "x": [0, 1, 2], "y": [0.1, 0.4, 0.4]}]
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 201, r.text
    import json
    stored = json.loads(r.json()["preview"])
    assert stored[0]["label"] == "Growth rate" and stored[0]["y"] == [0.1, 0.4, 0.4]


def test_a_nonexistent_channel_is_refused_at_save(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "badchan@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Bad channel")
    body["config"]["reporter_signal"] = "NONEXISTENT"
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "NONEXISTENT" in r.json()["detail"]


def test_a_sample_not_in_this_assay_is_refused_at_save(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "foreign@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    orphan = client.post(f"/api/studies/{study['id']}/samples",
                         json={"name": "Never assigned", "sample_type": "sample", "components": []}).json()
    body = _body(client, assay, signals, s, host, med, name="Foreign sample")
    body["config"]["sample_id"] = orphan["id"]
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422
    assert "not assigned" in r.json()["detail"] or "no wells" in r.json()["detail"]


def test_a_control_of_the_wrong_type_is_refused_at_save(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "wrongtype@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Wrong control type")
    body["config"]["reporter_control_id"] = med["id"]
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422
    assert "untransformed" in r.json()["detail"]


def test_units_and_method_come_from_the_server_not_the_caller(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "units@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Asserted units")
    body["reporter_unit"] = "MOLECULES_PER_CELL"
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 201, r.text
    src = r.json()["source"]
    assert src["reporter_unit"] != "MOLECULES_PER_CELL"
    assert src["analysis_method_version"] == "1"


def test_a_figure_computed_under_another_analysis_version_is_refused(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "relabel@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Relabelled version")
    body["analysis_method_version"] = "999"
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "run it again" in r.json()["detail"]


def test_a_recipe_without_a_source_assay_is_refused(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "noassay@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="No source")
    body.pop("assay_id")
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422
    assert "assay" in r.json()["detail"].lower()


def test_the_list_and_the_single_view_agree_about_staleness(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "agree@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    rec = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med)).json()
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments":
        {p: med["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
        | {p: med["id"] for p in fixtures.MEDIUM}})
    single = client.get(f"/api/recipes/{rec['id']}").json()
    listed = next(r for r in client.get(f"/api/studies/{study['id']}/recipes").json()["recipes"] if r["id"] == rec["id"])
    assert single["reproducible"] == listed["reproducible"] is False
    assert single["stale_reason"] == listed["stale_reason"]


def test_renaming_a_sample_makes_a_recipe_not_reproducible(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "label@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    rec = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med)).json()
    assert client.get(f"/api/recipes/{rec['id']}").json()["reproducible"] is True
    client.patch(f"/api/samples/{s['id']}", json={"name": "Renamed reporter"})
    assert client.get(f"/api/recipes/{rec['id']}").json()["reproducible"] is False


def test_analysis_version_is_separate_from_schema_version(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "versions@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    r = client.post(f"/api/studies/{study['id']}/recipes", json=_body(client, assay, signals, s, host, med)).json()
    from bob import recipes as core
    assert r["source"]["analysis_method"] == core.PRESETS["rate_profiles"]["method"]
    assert r["source"]["analysis_method_version"] == core.PRESETS["rate_profiles"]["method_version"]
    assert r["schema_version"] == core.SCHEMA_VERSION


def test_a_layout_change_between_the_figure_and_its_save_is_refused(client, plate_bytes):
    """One tab computes a figure; another moves a well; the first tab must not save the old preview."""
    study, s, host, med = _study_with_assay(client, "concurrent@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Concurrent edit")

    moved = sorted(fixtures.CONSORTIUM)[-1]
    assignments = ({p: s["id"] for p in fixtures.CONSORTIUM} | {p: host["id"] for p in fixtures.UNTRANSFORMED}
                   | {p: med["id"] for p in fixtures.MEDIUM})
    assignments[moved] = med["id"]
    assert client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assignments}).status_code == 200

    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "changed after this figure was computed" in r.json()["detail"]

    assignments[moved] = s["id"]
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assignments})
    rerun = _body(client, assay, signals, s, host, med, name="Concurrent edit")
    assert client.post(f"/api/studies/{study['id']}/recipes", json=rerun).status_code == 201


def test_a_sample_metadata_change_between_the_figure_and_its_save_is_refused(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "metadata@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="Metadata edit")
    assert client.patch(f"/api/samples/{s['id']}", json={"components": [
        {"role": "medium", "iri": "urn:LB"},
        {"role": "inducer", "iri": "urn:IPTG", "amount": 1.0, "unit": "mM"}]}).status_code == 200
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422, r.text


def test_a_recipe_saved_without_the_analysis_fingerprint_is_refused(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "nofp@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name="No fingerprint")
    body.pop("source_fingerprint")
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 422, r.text
    assert "run the figure again" in r.json()["detail"]


def test_a_saved_recipe_is_not_stale_against_the_source_it_was_computed_from(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "fresh@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    rec = client.post(f"/api/studies/{study['id']}/recipes",
                      json=_body(client, assay, signals, s, host, med)).json()
    assert rec["reproducible"] is True
    opened = client.get(f"/api/recipes/{rec['id']}").json()
    assert opened["reproducible"] is True and opened["layout_fingerprint"] == rec["layout_fingerprint"]
