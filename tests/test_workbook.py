from bob import fixtures
from tests.conftest import signup
from tests.test_api import _project

AUTHORS = [{"given_name": "Ada", "family_name": "Lovelace"}]
XLSX = "application/octet-stream"


def _send(client, study_id, workbook, plates, **form):
    files = [("workbook", ("experiment.xlsm", workbook, XLSX))] + [("plates", (name, data, XLSX)) for name, data in plates]
    return client.post(f"/api/studies/{study_id}/workbook", data=form, files=files)


def test_a_workbook_takes_gen5_text_exports_as_synbiosuite_sends_them(client, plate_bytes):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    book = fixtures.synthetic_assay_workbook(("plate_1",))
    out = _send(client, study["id"], book, [("run1.txt", fixtures.synthetic_gen5_text())], mapping_key="biotek-gen5-kinetic-text")
    assert out.status_code == 201, out.text
    (assay,) = out.json()["assays"]
    assert assay["wells_assigned"] == 9
    signals = {s["name"] for s in client.get(f"/api/assays/{assay['id']}").json()["signals"]}
    assert signals == {"OD600", "CFP", "YFP"}
    wrong = _send(client, study["id"], book, [("run1.xlsx", plate_bytes)], mapping_key="biotek-gen5-kinetic-text")
    assert wrong.status_code == 422 and "Excel" in wrong.json()["detail"]


def test_other_apps_sign_in_for_a_token_and_list_editable_studies(client):
    ws = signup(client, "ada@lab.test", "Ada")["workspaces"][0]
    _, study = _project(client, ws["id"])
    client.post("/api/auth/logout")
    wrong = client.post("/api/auth/token", json={"email": "ada@lab.test", "password": "nope", "app": "SynBioSuite"})
    assert wrong.status_code == 401
    r = client.post("/api/auth/token", json={"email": "ada@lab.test", "password": "correct horse", "app": "SynBioSuite"},
                    headers={"Origin": "https://synbiosuite.org"})
    assert r.status_code == 201, r.text
    bearer = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get("/api/auth/me").status_code == 401
    studies = client.get("/api/studies", headers=bearer).json()
    assert [(s["id"], s["investigation_title"]) for s in studies] == [(study["id"], "Inv")]
    assert [t["name"] for t in client.get("/api/auth/tokens", headers=bearer).json()] == ["SynBioSuite"]
    (inv,) = client.get("/api/investigations", headers=bearer).json()
    assert (inv["id"], inv["workspace_name"]) == (study["investigation_id"], ws["name"])

    preflight = client.options("/api/auth/token", headers={"Origin": "https://synbiosuite.org", "Access-Control-Request-Method": "POST",
                                                            "Access-Control-Request-Headers": "content-type"})
    assert preflight.headers.get("access-control-allow-origin") == "https://synbiosuite.org"
    assert "access-control-allow-credentials" not in preflight.headers
    other = client.options("/api/auth/token", headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in other.headers
    assert client.post("/api/workspaces", json={"name": "x"}, headers={"Origin": "https://evil.test"}).status_code == 403


def test_studies_listed_for_apps_exclude_read_only_workspaces(client):
    owner_ws = signup(client, "owner@lab.test", "Owner")["workspaces"][0]
    _project(client, owner_ws["id"])
    client.post(f"/api/workspaces/{owner_ws['id']}/invitations", json={"email": "viewer@lab.test", "role": "viewer"})
    client.post("/api/auth/logout")
    signup(client, "viewer@lab.test", "Viewer")
    (inv,) = client.get("/api/invitations").json()
    client.post(f"/api/invitations/{inv['id']}/accept")
    assert client.get("/api/studies").json() == [] and client.get("/api/investigations").json() == []
