import os

import pytest
from fastapi.testclient import TestClient

from bob import fixtures, synbiohub
from bob.models import RemoteAccount
from tests.conftest import signup
from tests.test_api import _project, _samples, _upload

# A SynBioHub to test against, set up with tests/synbiohub/ (docker-compose.yml, then setup.py).
SBH = os.environ.get("BOB_TEST_SYNBIOHUB", "").rstrip("/")
SBH_EMAIL = os.environ.get("BOB_TEST_SYNBIOHUB_EMAIL", "bobtest@lab.test")
SBH_PASSWORD = os.environ.get("BOB_TEST_SYNBIOHUB_PASSWORD", "bob-sbh-test-2026")
needs_sbh = pytest.mark.skipif(not SBH, reason="Set BOB_TEST_SYNBIOHUB to a test SynBioHub (see tests/synbiohub/)")
AUTHORS = [{"given_name": "Ada", "family_name": "Lovelace"}]


@pytest.fixture
def sbh_client(data_dir, monkeypatch):
    from bob.main import create_app

    monkeypatch.setenv("BOB_SYNBIOHUB_INSTANCES", SBH)
    with TestClient(create_app()) as c:
        yield c


def test_bob_contacts_only_the_configured_synbiohubs(client):
    signup(client, "ada@lab.test")
    status = client.get("/api/synbiohub").json()
    assert status == {"instances": [{"instance": "https://synbiohub.org", "signed_in": False, "username": None}]}
    for path, body in (("/api/synbiohub/login", {"instance": "http://127.0.0.1:9", "email": "a", "password": "b"}),):
        assert client.post(path, json=body).status_code == 422
    assert client.get("/api/synbiohub/resolve", params={"iri": "http://169.254.169.254/latest/meta-data"}).status_code == 422
    assert client.get("/api/synbiohub/resolve", params={"iri": "https://synbiohub.org.evil.test/x"}).status_code == 422
    assert client.get("/api/synbiohub/search", params={"instance": "http://localhost:8000", "q": "x"}).status_code == 422
    assert client.get("/api/synbiohub/collections", params={"instance": "https://synbiohub.org"}).status_code == 409


def test_tokens_are_sealed_and_unreadable_under_another_key():
    sealed = synbiohub.seal("first key", "c559e941-5a0a-4611-be25-8759796eeecb")
    assert "c559e941" not in sealed
    assert synbiohub.unseal("first key", sealed) == "c559e941-5a0a-4611-be25-8759796eeecb"
    assert synbiohub.unseal("rotated key", sealed) is None


@needs_sbh
def test_sign_in_upload_and_versions_on_synbiohub(sbh_client, plate_bytes):
    c = sbh_client
    ws = signup(c, "ada@lab.test", "Ada")["workspaces"][0]
    wrong = c.post("/api/synbiohub/login", json={"instance": SBH, "email": SBH_EMAIL, "password": "not it"})
    assert wrong.status_code == 400 and c.get("/api/auth/me").status_code == 200
    assert c.post("/api/synbiohub/login", json={"instance": SBH, "email": SBH_EMAIL, "password": SBH_PASSWORD}).json()["signed_in"]
    with c.app.state.sessionmaker() as db:
        (acct,) = db.query(RemoteAccount).all()
        assert acct.username == SBH_EMAIL and synbiohub.unseal(c.app.state.settings.secret_key, acct.secret)

    _, study = _project(c, ws["id"])
    samples = _samples(c, study["id"])
    assay = _upload(c, study["id"], plate_bytes)
    c.put(f"/api/assays/{assay['id']}/layout", json={"assignments": {p: samples["consortium"]["id"] for p in fixtures.CONSORTIUM}})
    c.post(f"/api/studies/{study['id']}/publish", json={"license": "CC-BY-4.0", "authors": AUTHORS})

    first = c.post(f"/api/studies/{study['id']}/synbiohub", json={"instance": SBH})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1 and first.json()["collection"].startswith(SBH + "/user/")
    assert c.post(f"/api/studies/{study['id']}/synbiohub", json={"instance": SBH}).status_code == 409
    assert c.post(f"/api/studies/{study['id']}/synbiohub", json={"instance": SBH, "overwrite": True}).status_code == 200

    c.patch(f"/api/studies/{study['id']}", json={"title": "Study, second version"})
    second = c.post(f"/api/studies/{study['id']}/synbiohub", json={"instance": SBH}).json()
    collections = c.get("/api/synbiohub/collections", params={"instance": SBH}).json()
    mine = [(x["display_id"], x["version"]) for x in collections if x["display_id"] == f"bob_{study['id']}_collection"]
    assert sorted(mine) == [(f"bob_{study['id']}_collection", "1"), (f"bob_{study['id']}_collection", "2")]
    meta = c.get("/api/synbiohub/resolve", params={"iri": second["collection"]}).json()
    assert meta["name"] == "Study, second version" and meta["sbol_class"] == "Collection"

    _, other = _project(c, ws["id"])
    c.patch(f"/api/studies/{other['id']}", json={"title": "Lab collection"})
    lab = c.post(f"/api/studies/{other['id']}/synbiohub", json={"instance": SBH}).json()["collection"]
    into = c.post(f"/api/studies/{study['id']}/synbiohub", json={"instance": SBH, "collection": lab})
    assert into.status_code == 200, into.text
    assert c.post(f"/api/studies/{study['id']}/synbiohub", json={"instance": SBH, "collection": SBH + "x/evil"}).status_code == 422
    events = [e for e in c.get(f"/api/studies/{study['id']}/events").json() if e["kind"] == "synbiohub"]
    assert len(events) == 4 and all(e["detail"].startswith(SBH) for e in events)

    assert c.post("/api/synbiohub/logout", json={"instance": SBH}).status_code == 204
    assert c.get("/api/synbiohub/collections", params={"instance": SBH}).status_code == 409


@needs_sbh
def test_designs_are_found_and_resolved(sbh_client):
    c = sbh_client
    signup(c, "ada@lab.test")
    c.post("/api/synbiohub/login", json={"instance": SBH, "email": SBH_EMAIL, "password": SBH_PASSWORD})
    assert c.get("/api/synbiohub/search", params={"instance": SBH, "q": "no such design anywhere"}).json() == []
    assert c.get("/api/synbiohub/resolve", params={"iri": SBH + "/public/nothing/here/1"}).status_code in (404, 502)


@needs_sbh
def test_workbook_designs_are_resolved_from_synbiohub_with_a_token_sent_for_one_import(sbh_client, plate_bytes):
    import uuid

    import sbol2

    from tests.test_workbook import XLSX

    token = synbiohub.login(SBH, SBH_EMAIL, SBH_PASSWORD)
    combined = sbol2.Document()
    for doc in fixtures.synthetic_design_sbol().values():
        combined.appendString(doc, overwrite=True)
    cid = "designs_" + uuid.uuid4().hex[:8]
    synbiohub.submit(SBH, token, combined.writeString().encode("utf-8"), "designs.xml", collection_id=cid, name="Designs")
    (coll,) = [x for x in synbiohub.collections(SBH, token) if x["display_id"] == f"{cid}_collection"]
    prefix = coll["uri"].rsplit("/", 2)[0]

    c = sbh_client
    ws = signup(c, "ada@lab.test")["workspaces"][0]
    _, study = _project(c, ws["id"])
    book = fixtures.synthetic_assay_workbook(("plate_1",), design_iri=prefix + "/{}/1")
    files = [("workbook", ("experiment.xlsm", book, XLSX)), ("plates", ("run1.xlsx", plate_bytes, XLSX))]
    out = c.post(f"/api/studies/{study['id']}/workbook", data={"synbiohub_token": token, "synbiohub_instance": SBH}, files=files)
    assert out.status_code == 201, out.text
    assert out.json()["warnings"] == []
    samples = {s["name"]: s for s in c.get(f"/api/studies/{study['id']}/samples").json()}
    parts = [(p["role"], p["label"], p["iri"], p["amount"]) for p in samples["consortium_x"]["components"]]
    assert parts[:3] == [("design", "consortium_x", prefix + "/consortium_x/1", None), ("medium", "m9", prefix + "/m9/1", None),
                         ("strain", "host", prefix + "/host/1", None)]
    assert parts[4][0::3] == ("supplement", 0.001)
    with c.app.state.sessionmaker() as db:
        assert db.query(RemoteAccount).count() == 0
