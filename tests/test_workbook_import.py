import io
import json

import openpyxl

from bob import fixtures
from bob.models import RemoteAccount
from tests.conftest import signup
from tests.test_api import _project
from tests.test_workbook import AUTHORS, XLSX, _send


def _study(client, public=False):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    if public:
        client.post(f"/api/studies/{study['id']}/publish", json={"license": "CC-BY-4.0", "authors": AUTHORS})
    return study["id"]


def _parts(sample):
    return [(c["role"], c["label"], c["amount"]) for c in sample["components"]]


def _check(client, sid, book, plates, **form):
    files = [("workbook", ("experiment.xlsm", book, XLSX))] + [("plates", (name, data, XLSX)) for name, data in plates]
    return client.post(f"/api/studies/{sid}/workbook/check", data=form, files=files)


def test_a_workbook_brings_samples_with_their_designs_resolved_into_parts(fake_synbiohub, client, plate_bytes):
    sid = _study(client, public=True)
    book = fixtures.synthetic_assay_workbook(("plate_1", "plate_2"))
    pairing = json.dumps({"run1.xlsx": "plate_1", "run2.xlsx": "plate_2"})
    r = _send(client, sid, book, [("run1.xlsx", plate_bytes), ("run2.xlsx", plate_bytes)], plate_assays=pairing,
              synbiohub_collection="https://synbiohub.test/user/lab/exp/exp_collection/1")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["samples_created"] == 3 and [(a["workbook_assay_id"], a["action"]) for a in out["assays"]] == [("plate_1", "new"), ("plate_2", "new")]
    assert all(a["wells_assigned"] == 9 for a in out["assays"]) and out["warnings"] == []

    samples = {s["name"]: s for s in client.get(f"/api/studies/{sid}/samples").json()}
    assert _parts(samples["consortium_x"]) == [("design", "consortium_x", None), ("medium", "m9", None), ("strain", "host", None),
                                               ("plasmid", "pYFP", None), ("supplement", "IPTG", 0.001)]
    assert _parts(samples["host_only"]) == [("design", "host_only", None), ("medium", "m9", None), ("strain", "host", None)]
    assert _parts(samples["medium_only"]) == [("design", "medium_only", None), ("medium", "m9", None)]
    design = samples["consortium_x"]["components"][0]
    assert (design["iri"], design["sbol_class"]) == (fixtures.DESIGN_IRI.format("consortium_x"), "ModuleDefinition")
    assert samples["consortium_x"]["components"][4]["unit"] is None
    layout = {p["position"]: p["sample_id"] for p in client.get(f"/api/assays/{out['assays'][0]['id']}/layout").json()["positions"]}
    assert {pos: layout[pos] for pos in fixtures.CONSORTIUM} == {pos: samples["consortium_x"]["id"] for pos in fixtures.CONSORTIUM}
    assert layout["A4"] is None
    assay = client.get(f"/api/assays/{out['assays'][1]['id']}").json()
    assert assay["name"] == "Plate plate_2" and assay["run_metadata"]["temperature_c"] == "30"

    history = client.get(f"/api/studies/{sid}/versions").json()
    assert [v["note"] for v in history] == ["Imported workbook experiment.xlsm", "Published"]
    kinds = {e["kind"]: e["detail"] for e in client.get(f"/api/studies/{sid}/events").json()}
    assert kinds["synbiohub"].endswith("exp_collection/1") and kinds["workbook"].startswith("experiment.xlsm (sha256 ")
    sbol = client.get(f"/api/studies/{sid}/sbol").text
    assert f'sbol:built rdf:resource="{fixtures.DESIGN_IRI.format("host_only")}"' in sbol
    assert 'sbol:built rdf:resource="https://synbiohub.test/user/lab/designs/host/1"' not in sbol
    assert "<sdo:value>0.001</sdo:value>" in sbol
    assert 'sdo:valueReference rdf:resource="https://synbiohub.test/user/lab/designs/IPTG/1"' in sbol
    (isa,) = client.get(f"/api/studies/{sid}/isa").json()["studies"]
    (iptg,) = [c for s in isa["materials"]["samples"] for c in s["characteristics"]]
    assert iptg["value"] == 0.001 and "unit" not in iptg
    assert [c["characteristicType"]["annotationValue"] for c in isa["characteristicCategories"]] == ["IPTG"]

    again = _send(client, sid, fixtures.synthetic_assay_workbook(("plate_3",)), [("run3.xlsx", plate_bytes)])
    assert again.json()["samples_created"] == 0 and len(client.get(f"/api/studies/{sid}/samples").json()) == 3


def test_plates_pair_with_assays_by_choice_never_by_order(fake_synbiohub, client, plate_bytes):
    sid = _study(client)
    book = fixtures.synthetic_assay_workbook(("plate_1", "plate_2"))
    plates = [("run_plate_2.xlsx", plate_bytes), ("first.xlsx", plate_bytes)]
    unsaid = _send(client, sid, book, plates)
    assert unsaid.status_code == 422 and "say which file belongs to which assay" in unsaid.json()["detail"]
    check = _check(client, sid, book, plates).json()
    assert not check["ok"] and check["pairing"] == [{"plate": "run_plate_2.xlsx", "assay_id": "plate_2", "source": "file name"},
                                                    {"plate": "first.xlsx", "assay_id": None, "source": None}]
    assert _send(client, sid, book, [("only.xlsx", plate_bytes)]).status_code == 422

    out = _send(client, sid, book, [("second.xlsx", plate_bytes)], plate_assays=json.dumps({"second.xlsx": "plate_2"})).json()
    assert [a["workbook_assay_id"] for a in out["assays"]] == ["plate_2"] and "plate_1" in out["warnings"][0]
    assert _send(client, sid, book, [("x.xlsx", plate_bytes)], plate_assays=json.dumps({"x.xlsx": "nope"})).status_code == 422
    assert _send(client, sid, book, [("x.xlsx", plate_bytes)], plate_assays="[1]").status_code == 422
    two = [("x.xlsx", plate_bytes), ("y.xlsx", plate_bytes)]
    unpaired = _send(client, sid, book, two, plate_assays=json.dumps({"x.xlsx": "plate_1"}))
    assert unpaired.status_code == 422 and "y.xlsx" in unpaired.json()["detail"]
    assert _send(client, sid, book, two, plate_assays=json.dumps({"x.xlsx": "plate_1", "y.xlsx": "plate_1"})).status_code == 422
    not_a_book = _send(client, sid, plate_bytes, [("x.xlsx", plate_bytes)])
    assert not_a_book.status_code == 422 and "Assay workbook" in not_a_book.json()["detail"]
    assert len(client.get(f"/api/studies/{sid}/assays").json()) == 1


def test_the_signal_sheet_names_the_channels_in_read_order(fake_synbiohub, client, plate_bytes):
    sid = _study(client)
    sheet = [("OD", "Optical density at 600nm", "black"), ("cyan", "CFP fluorescence", "cyan"), ("yellow", "YFP fluorescence", "#e6c200")]
    out = _send(client, sid, fixtures.synthetic_assay_workbook(("plate_1",), signals=sheet), [("run1.xlsx", plate_bytes)])
    assert out.status_code == 201, out.text
    signals = client.get(f"/api/assays/{out.json()['assays'][0]['id']}").json()["signals"]
    assert [(s["name"], s["description"], s["color"], s["kind"]) for s in signals] == [
        ("OD", "Optical density at 600nm", "black", "absorbance"), ("cyan", "CFP fluorescence", "cyan", "fluorescence"),
        ("yellow", "YFP fluorescence", "#e6c200", "fluorescence")]

    short = _send(client, sid, fixtures.synthetic_assay_workbook(("plate_2",), signals=sheet[:2]), [("run2.xlsx", plate_bytes)])
    assert short.status_code == 422
    assert "names 2 signals (OD, cyan) but the file holds 3 channels (OD600:600, CFP:420/50,485/20, YFP:500/27,540/25)" in short.json()["detail"]
    empty = _send(client, sid, fixtures.synthetic_assay_workbook(("plate_2",), signals=[]), [("run2.xlsx", plate_bytes)])
    assert {s["name"] for s in client.get(f"/api/assays/{empty.json()['assays'][0]['id']}").json()["signals"]} == {"OD600", "CFP", "YFP"}


def test_the_check_shows_what_an_import_would_do_and_saves_nothing(fake_synbiohub, client, plate_bytes):
    sid = _study(client)
    check = _check(client, sid, fixtures.synthetic_assay_workbook(("plate_1",), signals=fixtures.SIGNAL_SHEET), [("run1.xlsx", plate_bytes)])
    assert check.status_code == 200, check.text
    found = check.json()
    assert found["ok"] and found["problems"] == [] and found["pairing"] == [{"plate": "run1.xlsx", "assay_id": "plate_1", "source": "only one"}]
    (assay,) = found["assays"]
    assert (assay["action"], assay["wells"]) == ("new", 9)
    assert [(c["read"], c["label"], c["name"], c["color"]) for c in assay["channels"]] == [
        (1, "OD600:600", "OD600", "black"), (2, "CFP:420/50,485/20", "CFP", "cyan"), (3, "YFP:500/27,540/25", "YFP", "yellow")]
    samples = {s["name"]: s for s in found["samples"]}
    assert samples["consortium_x"]["action"] == "new" and samples["consortium_x"]["resolved"]
    assert [p["role"] for p in samples["consortium_x"]["parts"]] == ["design", "medium", "strain", "plasmid", "supplement"]
    assert client.get(f"/api/studies/{sid}/assays").json() == [] and client.get(f"/api/studies/{sid}/samples").json() == []
    assert client.get(f"/api/studies/{sid}/events").json() == []


def test_reuploads_are_recognized_and_replace_or_version(fake_synbiohub, client, plate_bytes):
    sid = _study(client)
    book = fixtures.synthetic_assay_workbook(("plate_1",))
    first = _send(client, sid, book, [("run1.xlsx", plate_bytes)]).json()
    same = _send(client, sid, book, [("run1.xlsx", plate_bytes)]).json()
    assert same["assays"] == [{**first["assays"][0], "action": "unchanged"}] and not same["changed"]
    assert len(client.get(f"/api/studies/{sid}/events").json()) == 1

    redone = _send(client, sid, book, [("run1.txt", fixtures.synthetic_gen5_text())], mapping_key="biotek-gen5-kinetic-text").json()
    assert redone["assays"][0]["action"] == "replace" and redone["assays"][0]["id"] != first["assays"][0]["id"]
    (assay,) = client.get(f"/api/studies/{sid}/assays").json()
    assert assay["raw_file"]["filename"] == "run1.txt"

    client.post(f"/api/studies/{sid}/publish", json={"license": "CC-BY-4.0", "authors": AUTHORS})
    again = _send(client, sid, book, [("run1.xlsx", plate_bytes)]).json()
    assert again["assays"][0]["action"] == "replace"
    history = client.get(f"/api/studies/{sid}/versions").json()
    assert [v["note"] for v in history] == ["Imported workbook experiment.xlsm", "Published"]
    (old,) = client.get(f"/api/studies/{sid}/assays", params={"version": 1}).json()
    assert old["id"] == assay["id"] and old["raw_file"]["filename"] == "run1.txt"
    assert client.get(f"/api/assays/{assay['id']}/raw", params={"version": 1}).status_code == 200


def test_a_token_sent_with_an_import_reads_private_designs_and_is_not_kept(fake_synbiohub, client, plate_bytes):
    fake_synbiohub.token = "lab-token"
    sid = _study(client)
    book = fixtures.synthetic_assay_workbook(("plate_1",))
    without = _send(client, sid, book, [("run1.xlsx", plate_bytes)]).json()
    assert len(without["warnings"]) == 3 and "could not be read from SynBioHub (SynBioHub asked for a sign-in" in without["warnings"][0]
    assert all(_parts(s) == [("design", s["name"], None)] for s in client.get(f"/api/studies/{sid}/samples").json())

    unplaced = _send(client, sid, book, [("run1.xlsx", plate_bytes)], synbiohub_token="lab-token").json()
    assert unplaced["warnings"][0].startswith("The SynBioHub token sent with the import was not used")
    other = fixtures.synthetic_assay_workbook(("plate_2",))
    signed = _send(client, sid, other, [("run2.xlsx", plate_bytes)], synbiohub_token="lab-token", synbiohub_instance=fixtures.SYNBIOHUB).json()
    assert signed["warnings"] == [] and signed["samples_updated"] == 3
    samples = {s["name"]: s for s in client.get(f"/api/studies/{sid}/samples").json()}
    assert _parts(samples["medium_only"]) == [("design", "medium_only", None), ("medium", "m9", None)]
    assert {token for _url, token in fake_synbiohub.asked} == {None, "lab-token"}
    with client.app.state.sessionmaker() as db:
        assert db.query(RemoteAccount).count() == 0
    assert "lab-token" not in json.dumps(client.get(f"/api/studies/{sid}/events").json())


def test_designs_are_read_only_from_configured_synbiohubs(fake_synbiohub, client, plate_bytes):
    sid = _study(client)
    wb = openpyxl.load_workbook(io.BytesIO(fixtures.synthetic_assay_workbook(("plate_1",))))
    for row in wb["SBH_sampledesigns_collection"].iter_rows(min_row=2):
        row[1].value = row[1].value.replace(fixtures.SYNBIOHUB, "https://elsewhere.test")
    buf = io.BytesIO()
    wb.save(buf)
    out = _send(client, sid, buf.getvalue(), [("run1.xlsx", plate_bytes)]).json()
    assert len(out["warnings"]) == 3 and "is not on a SynBioHub this BOB server is set up to read" in out["warnings"][0]
    assert fake_synbiohub.asked == []
