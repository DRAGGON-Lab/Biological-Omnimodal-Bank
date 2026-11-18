"""A study export must carry its saved analysis configuration, and must not mislabel digests.

Two independent claims are asserted here, both against the exported bytes rather than through the
writer that produced them:

* a saved figure recipe reaches all three exports with the same payload;
* the raw file's SHA-256 is never presented as SBOL's optional attachment hash, which the SBOL 2.3
  specification defines as a SHA-1 digest (SBOL 2.3, section 7.13).
"""
import io
import json
import re
import zipfile

import pytest

from tests.conftest import signup
from tests.test_recipes_api import _assay_for, _body, _study_with_assay

SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b")


def _study_with_recipe(client, plate_bytes, email="exports@lab.test", name="Saved growth curve"):
    study, s, host, med = _study_with_assay(client, email)
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    body = _body(client, assay, signals, s, host, med, name=name)
    rec = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert rec.status_code == 201, rec.text
    return study, assay, rec.json()


def _crate_manifest(client, study_id, version=None):
    q = f"?version={version}" if version else ""
    r = client.get(f"/api/studies/{study_id}/ro-crate{q}")
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    meta = json.loads(zf.read("ro-crate-metadata.json"))
    names = [e["@id"] for e in meta["@graph"]]
    manifest_ids = [n for n in names if "recipe" in n.lower() and n.endswith(".json")]
    assert manifest_ids, f"no recipe manifest entity in the crate: {names}"
    payload = json.loads(zf.read(manifest_ids[0]))
    root = next(e for e in meta["@graph"] if e["@id"] == "./")
    linked = [p["@id"] for p in root.get("hasPart", [])]
    assert manifest_ids[0] in linked, f"manifest not linked through hasPart: {linked}"
    return payload


def _isa_manifest(client, study_id, version=None):
    q = f"?version={version}" if version else ""
    r = client.get(f"/api/studies/{study_id}/isa{q}")
    assert r.status_code == 200, r.text
    doc = r.json()
    (study,) = doc["studies"]
    comments = {c["name"]: c["value"] for c in study.get("comments", [])}
    key = next((k for k in comments if "recipe" in k.lower()), None)
    assert key, f"no recipe comment at study level: {sorted(comments)}"
    return json.loads(comments[key])


def _sbol_text(client, study_id, version=None):
    q = f"?version={version}" if version else ""
    r = client.get(f"/api/studies/{study_id}/sbol{q}")
    assert r.status_code == 200, r.text
    return r.text


def _sbol_manifest(client, study_id, version=None):
    text = _sbol_text(client, study_id, version)
    hits = re.findall(r"<[^>]*recipe[Mm]anifest[^>]*>(.*?)</[^>]*recipe[Mm]anifest[^>]*>", text, re.S)
    assert hits, "no recipe manifest annotation in the SBOL document"
    raw = hits[0]
    for a, b in (("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        raw = raw.replace(a, b)
    return json.loads(raw)


def test_a_saved_recipe_reaches_all_three_exports(client, plate_bytes):
    """A saved recipe appears in the RO-Crate, the ISA-JSON and the SBOL export alike."""
    study, assay, rec = _study_with_recipe(client, plate_bytes)
    crate = _crate_manifest(client, study["id"])
    isa = _isa_manifest(client, study["id"])
    sbol = _sbol_manifest(client, study["id"])
    assert crate == isa == sbol, "the same payload must appear in all three formats"
    (entry,) = crate["recipes"]
    assert entry["id"] == rec["id"] and entry["name"] == "Saved growth curve"
    assert entry["preset"] == rec["preset"]
    assert entry["analysis_method"] == rec["source"]["analysis_method"]
    assert entry["analysis_method_version"] == rec["source"]["analysis_method_version"]
    assert entry["source"]["assay_id"] == assay["id"]
    assert entry["source"]["raw_file_sha256"] == rec["source"]["raw_file_sha256"]
    assert entry["layout_fingerprint"] == rec["layout_fingerprint"]


def test_the_raw_sha256_is_never_presented_as_the_sbol_attachment_hash(client, plate_bytes):
    """SBOL 2.3 section 7.13 defines the optional attachment hash as SHA-1, so a 64-hex SHA-256
    must not occupy it. Asserted on the serialized document, not through the writer."""
    study, assay, rec = _study_with_recipe(client, plate_bytes, email="sbolhash@lab.test")
    text = _sbol_text(client, study["id"])
    digest = rec["source"]["raw_file_sha256"]
    assert len(digest) == 64

    hash_values = re.findall(r"<sbol:hash[^>]*>(.*?)</sbol:hash>", text, re.S)
    assert digest not in hash_values, (
        "the raw file's SHA-256 is serialized as sbol:hash, which SBOL defines as SHA-1")
    assert not any(SHA256_RE.fullmatch(v.strip()) for v in hash_values), (
        f"a 64-hex digest still occupies sbol:hash: {hash_values}")

    labelled = re.findall(r"<bob:rawFileSha256[^>]*>(.*?)</bob:rawFileSha256>", text, re.S)
    assert labelled and labelled[0].strip() == digest, (
        "the SHA-256 must survive under an explicitly named property")
    assert "sha256" in text.lower()


def _publish(client, study_id, note="first"):
    r = client.post(f"/api/studies/{study_id}/publish",
                    json={"license": "CC-BY-4.0",
                          "authors": [{"given_name": "Ada", "family_name": "Lovelace"}]})
    assert r.status_code == 200, r.text
    return r.json()


def test_every_recipe_check_is_reported_separately_and_none_is_implied(client, plate_bytes):
    study, assay, rec = _study_with_recipe(client, plate_bytes, email="checks@lab.test")
    (entry,) = _crate_manifest(client, study["id"])["recipes"]
    status = entry["source_status"]
    assert "scope" in status and "recorded source" in status["scope"]
    names = set(status["checks"])
    assert names == {"source_resolved", "raw_file_sha256", "layout_fingerprint", "units",
                     "recipe_schema_version", "analysis_method", "analysis_method_version"}, names
    for name, check in status["checks"].items():
        assert check["ok"] in (True, False, None), (name, check)
        if check["ok"] is None:
            assert check["reason"], f"{name} is not checked and must say so"
    assert status["resolved"] is True


def test_a_recipe_tied_to_v1_is_assessed_against_v1_even_when_exported_from_v3(client, plate_bytes):
    """The counterexample: export version and recorded source version are different things."""
    study, s, host, med = _study_with_assay(client, "v1v3@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    _publish(client, study["id"])

    body = _body(client, assay, signals, s, host, med, name="Tied to v1")
    body["snapshot_version"] = 1
    saved = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["source"]["snapshot_version"] == 1

    # move the live layout on, which must not change how the v1-tied recipe is judged
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": {}})
    client.patch(f"/api/studies/{study['id']}", json={"description": "moved on"})
    versions_now = client.get(f"/api/studies/{study['id']}/versions").json()
    assert len(versions_now) >= 3, versions_now

    latest = max(v["number"] for v in versions_now)
    (entry,) = _crate_manifest(client, study["id"], version=latest)["recipes"]
    status = entry["source_status"]
    assert "published version 1" in status["scope"], status["scope"]
    assert status["checks"]["layout_fingerprint"]["ok"] is True, status
    assert status["resolved"] is True, status


def test_a_published_manifest_does_not_change_when_the_method_version_moves_on(client, plate_bytes, monkeypatch):
    """A frozen assessment stays frozen: the stored outcome is not re-derived on later downloads."""
    from bob import recipes as recipe_core

    study, assay, rec = _study_with_recipe(client, plate_bytes, email="frozen@lab.test")
    _publish(client, study["id"])
    before = _crate_manifest(client, study["id"], version=1)

    spec = dict(recipe_core.PRESETS[rec["preset"]])
    spec["method_version"] = "999"
    monkeypatch.setitem(recipe_core.PRESETS, rec["preset"], spec)

    after = _crate_manifest(client, study["id"], version=1)
    assert after == before, "a published manifest was re-derived against the newer implementation"
    (entry,) = after["recipes"]
    assert entry["analysis_method_version"] != "999"
    assert entry["source_status"]["checks"]["analysis_method_version"]["ok"] is True


def test_an_older_snapshot_without_recipes_says_not_captured(client, plate_bytes):
    """Not captured is distinct from a verified empty inventory."""
    from bob.models import StudyVersion

    study, assay, rec = _study_with_recipe(client, plate_bytes, email="notcaptured@lab.test")
    _publish(client, study["id"])
    # rewrite version 1 as it would have been written before this field existed
    Session = client.app.state.sessionmaker
    with Session() as db:
        v = db.query(StudyVersion).filter_by(study_id=study["id"], number=1).one()
        snap = dict(v.snapshot)
        snap.pop("recipes", None)
        v.snapshot = snap
        db.add(v)
        db.commit()

    m = _crate_manifest(client, study["id"], version=1)
    assert m["captured"] is False
    assert m["recipes"] == []
    assert "not" in m["capture_note"].lower() and "verified" in m["capture_note"].lower()


def test_a_known_empty_inventory_is_not_the_same_as_not_captured(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "empty@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    _publish(client, study["id"])
    m = _crate_manifest(client, study["id"], version=1)
    assert m["captured"] is True and m["recipes"] == [] and m["capture_note"] == ""


def test_exporting_never_creates_a_version(client, plate_bytes):
    study, assay, rec = _study_with_recipe(client, plate_bytes, email="noversion@lab.test")
    _publish(client, study["id"])
    before = client.get(f"/api/studies/{study['id']}/versions").json()
    for path in ("isa", "sbol", "ro-crate"):
        assert client.get(f"/api/studies/{study['id']}/{path}").status_code == 200
        assert client.get(f"/api/studies/{study['id']}/{path}").status_code == 200
    after = client.get(f"/api/studies/{study['id']}/versions").json()
    assert [v["number"] for v in after] == [v["number"] for v in before]


def test_two_recipes_on_two_assays_do_not_leak_into_each_other(client, plate_bytes):
    study, s, host, med = _study_with_assay(client, "twoassays@lab.test")
    a1, sig1 = _assay_for(client, study, s, host, med, plate_bytes)
    a2, sig2 = _assay_for(client, study, s, host, med, plate_bytes)
    for assay, signals, name in ((a1, sig1, "First"), (a2, sig2, "Second")):
        b = _body(client, assay, signals, s, host, med, name=name)
        assert client.post(f"/api/studies/{study['id']}/recipes", json=b).status_code == 201, name
    m = _crate_manifest(client, study["id"])
    assert len(m["recipes"]) == 2
    by_name = {e["name"]: e for e in m["recipes"]}
    assert by_name["First"]["source"]["assay_id"] == a1["id"]
    assert by_name["Second"]["source"]["assay_id"] == a2["id"]
    assert by_name["First"]["id"] != by_name["Second"]["id"]


def test_a_reader_of_another_study_cannot_reach_the_manifest(client, plate_bytes):
    study, assay, rec = _study_with_recipe(client, plate_bytes, email="owner@lab.test")
    client.post("/api/auth/logout")
    signup(client, "stranger@lab.test")
    for path in ("isa", "sbol", "ro-crate"):
        r = client.get(f"/api/studies/{study['id']}/{path}")
        assert r.status_code == 404, (path, r.status_code)


def test_the_preview_is_labelled_as_a_preview_and_not_a_result(client, plate_bytes):
    study, assay, rec = _study_with_recipe(client, plate_bytes, email="preview@lab.test")
    (entry,) = _isa_manifest(client, study["id"])["recipes"]
    note = entry["preview"]["note"].lower()
    assert "not an analysis result" in note and "preview" in note
    assert "recipes" in _isa_manifest(client, study["id"])


def test_units_are_compared_against_the_selected_channel_not_the_first_of_its_kind(client, plate_bytes):
    """The two fluorescence channels are given genuinely different units here, because the stock
    Gen5 mapping gives both RFU and selecting the second could not then expose a first-of-kind
    lookup. The final assertion shows that the former lookup would have been wrong."""
    from bob.models import Signal

    study, s, host, med = _study_with_assay(client, "twochannels@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    fluor = [x for x in signals if x["kind"] == "fluorescence"]
    assert len(fluor) >= 2, [x["name"] for x in signals]
    first_name, second_name = fluor[0]["name"], fluor[1]["name"]

    Session = client.app.state.sessionmaker
    with Session() as db:
        row = db.query(Signal).filter_by(assay_id=assay["id"], name=second_name).one()
        row.unit = "MEFL"
        db.add(row)
        db.commit()
    refreshed = client.get(f"/api/assays/{assay['id']}").json()["signals"]
    units = {x["name"]: x["unit"] for x in refreshed}
    assert units[first_name] != units[second_name], units

    body = _body(client, assay, signals, s, host, med, name="On the second channel")
    body["config"]["reporter_signal"] = second_name
    r = client.post(f"/api/studies/{study['id']}/recipes", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["source"]["reporter_unit"] == "MEFL", r.json()["source"]

    (entry,) = _crate_manifest(client, study["id"])["recipes"]
    assert entry["config"]["reporter_signal"] == second_name
    assert entry["source"]["reporter_unit"] == "MEFL"
    check = entry["source_status"]["checks"]["units"]
    assert check["ok"] is True, check

    # the former first-of-kind lookup would have offered the first channel's unit for comparison,
    # which this fixture makes a different value, so the check would not have passed
    from bob import recipes as recipe_core
    first_of_kind = recipe_core.assess(entry, scope="first-of-kind simulation", source={
        "layout_fingerprint": entry["layout_fingerprint"],
        "raw_file_sha256": entry["source"].get("raw_file_sha256"),
        "channel_units": {first_name: units[first_name]}})
    assert first_of_kind["checks"]["units"]["ok"] is False, first_of_kind["checks"]["units"]
    assert first_of_kind["resolved"] is False


def test_the_investigation_export_carries_each_study_manifest_without_leakage(client, plate_bytes):
    """The aggregate export must not be a narrower record than the per-study one."""
    study_a, assay_a, rec_a = _study_with_recipe(client, plate_bytes, email="agg@lab.test",
                                                 name="Recipe in study A")
    inv_id = client.get(f"/api/studies/{study_a['id']}").json()["investigation_id"]
    study_b = client.post(f"/api/investigations/{inv_id}/studies", json={"title": "Study B"}).json()

    doc = client.get(f"/api/investigations/{inv_id}/isa")
    assert doc.status_code == 200, doc.text
    blocks = doc.json()["studies"]
    assert len(blocks) == 2, [b["title"] for b in blocks]
    found = {}
    for b in blocks:
        comments = {c["name"]: c["value"] for c in b.get("comments", [])}
        key = next((k for k in comments if "recipe" in k.lower()), None)
        assert key, f"study {b['title']!r} carries no recipe comment"
        found[b["identifier"]] = json.loads(comments[key])
    a = found[study_a["id"]]
    b = found[study_b["id"]]
    assert [e["name"] for e in a["recipes"]] == ["Recipe in study A"]
    assert b["recipes"] == [], "study B must not inherit study A's recipes"
    assert b["captured"] is True


def test_a_recorded_unit_with_no_source_channel_is_never_reported_as_passing(client):
    """Absent evidence must read as a failure or as not checked, never as a pass."""
    from bob import recipes as recipe_core

    entry = {
        "config": {"reporter_signal": "YFP"},
        "source": {"assay_id": "a1", "reporter_unit": "RFU"},
        "layout_fingerprint": "f" * 64,
        "schema_version": recipe_core.SCHEMA_VERSION,
        "preset": "reporter_trajectory",
        "analysis_method": recipe_core.PRESETS["reporter_trajectory"]["method"],
        "analysis_method_version": recipe_core.PRESETS["reporter_trajectory"]["method_version"],
    }
    gone = recipe_core.assess(entry, scope="test", source={
        "layout_fingerprint": "f" * 64, "raw_file_sha256": None, "channel_units": {"OD600": "OD"}})
    assert gone["checks"]["units"]["ok"] is False, gone["checks"]["units"]
    assert "not present in the recorded source" in gone["checks"]["units"]["reason"]
    assert gone["resolved"] is False and "units" in gone["failed_checks"]

    nolist = recipe_core.assess(entry, scope="test", source={
        "layout_fingerprint": "f" * 64, "raw_file_sha256": None, "channel_units": None})
    assert nolist["checks"]["units"]["ok"] is None
    assert nolist["resolved"] is False, "an unchecked box must not produce an all-clear"
    assert nolist["assessment_complete"] is False and "units" in nolist["not_checked"]


def test_not_checked_boxes_never_make_an_all_clear(client):
    from bob import recipes as recipe_core

    out = recipe_core.assess({"config": {}, "source": {"assay_id": "a1"}, "preset": "growth_curve",
                              "layout_fingerprint": "", "schema_version": recipe_core.SCHEMA_VERSION,
                              "analysis_method": recipe_core.PRESETS["growth_curve"]["method"],
                              "analysis_method_version": recipe_core.PRESETS["growth_curve"]["method_version"]},
                             scope="test",
                             source={"layout_fingerprint": None, "raw_file_sha256": None,
                                     "channel_units": {}})
    assert out["source_resolved"] is True
    assert out["checks_passed"] is True
    assert out["assessment_complete"] is False
    assert out["resolved"] is False, "source resolution is not the same as a complete assessment"


# --- the manifest-bearing exports, through the same validators test_standards.py uses ---

@pytest.fixture
def manifest_bearing(client, plate_bytes):
    """A published study whose exports carry a recipe manifest, live and at a frozen version."""
    study, s, host, med = _study_with_assay(client, "validated@lab.test")
    assay, signals = _assay_for(client, study, s, host, med, plate_bytes)
    # the supplement is chemical context, so every well compared against another must share it,
    # otherwise the export fixture trips the compatibility refusal rather than the validators
    context = [{"role": "medium", "iri": "urn:LB"},
               {"role": "supplement", "iri": "https://sbh.test/iptg/1", "label": "IPTG",
                "amount": 1.0, "unit": "mM"}]
    client.patch(f"/api/samples/{s['id']}", json={"components": context + [
        {"role": "design", "iri": "https://sbh.test/design/1"},
        {"role": "strain", "iri": "https://sbh.test/a/1", "label": "host"}]})
    client.patch(f"/api/samples/{med['id']}", json={"components": list(context)})
    client.patch(f"/api/samples/{host['id']}", json={"components": context + [
        {"role": "strain", "iri": "https://sbh.test/a/1", "label": "host"}]})
    client.post(f"/api/studies/{study['id']}/publish", json={
        "license": "CC-BY-4.0",
        "authors": [{"given_name": "Ada", "family_name": "Lovelace",
                     "orcid": "0000-0002-1825-0097", "affiliation": "Analytical Engine Lab"}]})
    body = _body(client, assay, signals, s, host, med, name="Validated recipe")
    assert client.post(f"/api/studies/{study['id']}/recipes", json=body).status_code == 201
    sid = study["id"]
    inv = client.get(f"/api/studies/{sid}").json()["investigation_id"]
    latest = max(v["number"] for v in client.get(f"/api/studies/{sid}/versions").json())
    return {
        "study_id": sid,
        "isa": {"study": client.get(f"/api/studies/{sid}/isa").json(),
                "investigation": client.get(f"/api/investigations/{inv}/isa").json(),
                f"study version {latest}": client.get(f"/api/studies/{sid}/isa?version={latest}").json()},
        "sbol": {"latest": client.get(f"/api/studies/{sid}/sbol").text,
                 "frozen": client.get(f"/api/studies/{sid}/sbol?version={latest}").text},
        "crates": {"latest": client.get(f"/api/studies/{sid}/ro-crate").content,
                   "frozen": client.get(f"/api/studies/{sid}/ro-crate?version={latest}").content},
    }


def _assert_carries_manifest_isa(doc):
    blocks = doc["studies"]
    assert any(any("recipe" in c["name"].lower() for c in b.get("comments", [])) for b in blocks), \
        "this document carries no recipe manifest, so validating it proves nothing about one"


@pytest.mark.parametrize("which", ["study", "investigation"])
def test_a_manifest_bearing_isa_export_matches_the_pinned_schemas(manifest_bearing, which):
    from tests.test_standards import validate_isa

    doc = manifest_bearing["isa"][which]
    _assert_carries_manifest_isa(doc)
    errors = validate_isa(doc)
    assert not errors, "\n".join(errors)


def test_a_manifest_bearing_frozen_isa_export_matches_the_pinned_schemas(manifest_bearing):
    from tests.test_standards import validate_isa

    key = next(k for k in manifest_bearing["isa"] if k.startswith("study version "))
    doc = manifest_bearing["isa"][key]
    _assert_carries_manifest_isa(doc)
    assert not validate_isa(doc)


@pytest.mark.parametrize("which", ["latest", "frozen"])
def test_a_manifest_bearing_sbol_export_passes_the_official_validator(manifest_bearing, which):
    from tests.test_standards import validate_sbol

    text = manifest_bearing["sbol"][which]
    assert "recipeManifest" in text, "this document carries no manifest annotation"
    result = validate_sbol(text)
    assert result["valid"], "\n".join(e.strip() for e in result.get("errors", []) if e.strip())


@pytest.mark.parametrize("which", ["latest", "frozen"])
def test_a_manifest_bearing_crate_passes_the_ro_crate_and_isa_profiles(manifest_bearing, which, tmp_path):
    from tests.test_standards import validate_crate_dir

    crate = tmp_path / "crate"
    zipfile.ZipFile(io.BytesIO(manifest_bearing["crates"][which])).extractall(crate)
    meta = json.loads((crate / "ro-crate-metadata.json").read_text(encoding="utf-8"))
    root = next(e for e in meta["@graph"] if e["@id"] == "./")
    parts = [p["@id"] for p in root["hasPart"]]
    recipes_file = next(n for n in parts if n.endswith(".recipes.json"))
    assert (crate / recipes_file).exists(), f"the manifest file is not in the crate: {parts}"
    payload = json.loads((crate / recipes_file).read_text(encoding="utf-8"))
    assert payload["recipes"], "the crate's manifest is empty, so this proves nothing about one"
    validate_crate_dir(crate)
