from sqlalchemy import update

from bob import fixtures
from bob.models import Study
from tests.conftest import signup
from tests.test_api import _project, _samples, _upload

PW = "correct horse"
AUTHORS = [{"given_name": "Ada", "family_name": "Lovelace", "orcid": "0000-0002-1825-0097", "affiliation": "Analytical Engine Lab"}]


def _login(client, email):
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text


def _published(client, plate_bytes):
    """Owner ada with a published study holding samples and one laid-out assay."""
    ws = signup(client, "ada@lab.test", "Ada")["workspaces"][0]
    inv, study = _project(client, ws["id"])
    samples = _samples(client, study["id"])
    assay = _upload(client, study["id"], plate_bytes)
    layout = {p: samples["consortium"]["id"] for p in fixtures.CONSORTIUM} | {p: samples["medium"]["id"] for p in fixtures.MEDIUM}
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": layout})
    r = client.post(f"/api/studies/{study['id']}/publish", json={"license": "CC-BY-4.0", "authors": AUTHORS})
    assert r.status_code == 200, r.text
    return ws, inv, r.json(), samples, assay


def test_only_owners_publish_and_a_license_is_required(client):
    ws = signup(client, "ada@lab.test", "Ada")["workspaces"][0]
    _, study = _project(client, ws["id"])
    client.post(f"/api/workspaces/{ws['id']}/invitations", json={"email": "ed@lab.test", "role": "editor"})
    assert client.patch(f"/api/studies/{study['id']}", json={"visibility": "public"}).status_code == 422
    assert client.post(f"/api/investigations/{study['investigation_id']}/studies", json={"title": "X", "visibility": "public"}).status_code == 422
    client.post("/api/auth/logout")

    signup(client, "ed@lab.test", "Ed")
    (inv,) = client.get("/api/invitations").json()
    client.post(f"/api/invitations/{inv['id']}/accept")
    assert client.post(f"/api/studies/{study['id']}/publish", json={"license": "CC0-1.0", "authors": AUTHORS}).status_code == 403
    _login(client, "ada@lab.test")

    assert client.post(f"/api/studies/{study['id']}/publish", json={}).status_code == 422
    assert client.post(f"/api/studies/{study['id']}/publish", json={"license": "MIT"}).status_code == 422
    out = client.post(f"/api/studies/{study['id']}/publish", json={"license": "CC0-1.0", "authors": AUTHORS}).json()
    assert (out["visibility"], out["license"], out["latest_version"]) == ("public", "CC0-1.0", 1)
    assert out["license_url"] == "https://creativecommons.org/publicdomain/zero/1.0/"
    (event,) = client.get(f"/api/studies/{study['id']}/events").json()
    assert (event["kind"], event["detail"], event["user"]) == ("published", "CC0-1.0", "Ada")


def test_a_public_study_shows_readers_nothing_else(client, plate_bytes):
    ws, inv, study, _samples_, assay = _published(client, plate_bytes)
    inv = client.patch(f"/api/investigations/{inv['id']}", json={"title": "Confidential grant aims"}).json()
    secret = client.post(f"/api/investigations/{inv['id']}/studies", json={"title": "Unpublished"}).json()
    _login(client, "ada@lab.test")
    client.post("/api/auth/logout")
    signup(client, "reader@lab.test")

    sid = study["id"]
    for path in (f"/api/studies/{sid}", f"/api/studies/{sid}/samples", f"/api/studies/{sid}/assays", f"/api/studies/{sid}/versions",
                 f"/api/studies/{sid}/sbol", f"/api/studies/{sid}/isa", f"/api/assays/{assay['id']}", f"/api/assays/{assay['id']}/raw",
                 f"/api/assays/{assay['id']}/series?signal=YFP&correct=false", f"/api/studies/{sid}?version=1"):
        assert client.get(path).status_code == 200, path
    for path in (f"/api/investigations/{inv['id']}", f"/api/investigations/{inv['id']}/studies", f"/api/investigations/{inv['id']}/isa",
                 f"/api/studies/{secret['id']}", f"/api/workspaces/{ws['id']}/members"):
        assert client.get(path).status_code == 404, path
    assert client.get(f"/api/studies/{sid}/events").status_code == 403
    assert client.patch(f"/api/studies/{sid}", json={"title": "x"}).status_code == 404

    isa = client.get(f"/api/studies/{sid}/isa").json()
    text = str(isa)
    assert [s["identifier"] for s in isa["studies"]] == [sid] and isa["identifier"] == sid
    assert inv["title"] not in text and "Unpublished" not in text and ws["name"] not in text
    assert {"name": "license", "value": "CC-BY-4.0"} in isa["studies"][0]["comments"]


def test_every_saved_change_is_a_version_and_old_versions_stay_readable(client, plate_bytes):
    _ws, _inv, study, samples, assay = _published(client, plate_bytes)
    sid, aid = study["id"], assay["id"]
    client.patch(f"/api/studies/{sid}", json={"title": "Renamed study"})
    client.patch(f"/api/studies/{sid}", json={"title": "Renamed study"})
    client.post(f"/api/studies/{sid}/samples", json={"name": "Late sample"})
    client.put(f"/api/assays/{aid}/layout", json={"assignments": {"H12": samples["host"]["id"]}})
    assert client.delete(f"/api/assays/{aid}").status_code == 204

    history = client.get(f"/api/studies/{sid}/versions").json()
    assert [(v["number"], v["note"]) for v in history] == [
        (5, "Removed assay Plate"),
        (4, "Changed the plate layout of Plate"),
        (3, "Added sample Late sample"),
        (2, "Edited the study details"),
        (1, "Published"),
    ]
    assert all(v["author"] == "Ada" for v in history)
    assert client.get(f"/api/studies/{sid}").json()["latest_version"] == 5
    assert client.get(f"/api/assays/{aid}").status_code == 404

    v1 = client.get(f"/api/studies/{sid}?version=1").json()
    assert (v1["title"], v1["version"], v1["assay_count"], v1["sample_count"]) == ("Study", 1, 1, 3)
    assert [a["id"] for a in client.get(f"/api/studies/{sid}/assays?version=1").json()] == [aid]
    assert client.get(f"/api/studies/{sid}/assays?version=5").json() == []
    assert len(client.get(f"/api/studies/{sid}/samples?version=3").json()) == 4
    assert client.get(f"/api/assays/{aid}?version=1").json()["raw_file"]["url"] == f"/api/assays/{aid}/raw?version=1"
    assert client.get(f"/api/assays/{aid}/raw?version=1").content == plate_bytes
    layout1 = {p["position"]: p["sample_id"] for p in client.get(f"/api/assays/{aid}/layout?version=1").json()["positions"]}
    layout4 = {p["position"]: p["sample_id"] for p in client.get(f"/api/assays/{aid}/layout?version=4").json()["positions"]}
    assert layout1["H12"] is None and layout4["H12"] == samples["host"]["id"]
    curves = client.get(f"/api/assays/{aid}/series?signal=YFP&version=1&correct=false").json()
    assert {g["group"] for g in curves["groups"]} == {"Consortium X", "Medium"}
    assert curves["corrected"] is False
    # version 1 marks no untransformed wells, and medium blanks are not a substitute for them
    refused = client.get(f"/api/assays/{aid}/series?signal=YFP&version=1&correct=true")
    assert refused.status_code == 422, refused.text
    assert "untransformed" in refused.json()["detail"]
    assert client.get(f"/api/assays/{aid}/mean-expression?signal=YFP&version=4&correct=false").status_code == 200
    assert client.get(f"/api/studies/{sid}?version=6").status_code == 404

    sbol1 = client.get(f"/api/studies/{sid}/sbol?version=1").text
    sbol5 = client.get(f"/api/studies/{sid}/sbol").text
    assert f"https://bob.test/sbol/study_{sid}/1" in sbol1 and f"assay_{aid}/1" in sbol1
    assert f"https://bob.test/sbol/study_{sid}/5" in sbol5 and f"assay_{aid}" not in sbol5
    isa1 = client.get(f"/api/studies/{sid}/isa?version=1").json()["studies"][0]
    assert isa1["title"] == "Study" and [a["@id"] for a in isa1["assays"]] == [f"#assay/{aid}"]


def test_withdrawn_studies_leave_a_notice_and_cannot_be_deleted(client, plate_bytes):
    ws, inv, study, _s, _a = _published(client, plate_bytes)
    sid = study["id"]
    assert client.post(f"/api/studies/{sid}/withdraw", json={"reason": " "}).status_code == 422
    out = client.post(f"/api/studies/{sid}/withdraw", json={"reason": "Plate reader was miscalibrated"}).json()
    assert out["visibility"] == "withdrawn" and out["withdraw_reason"] == "Plate reader was miscalibrated"
    assert client.delete(f"/api/studies/{sid}").status_code == 409
    assert client.delete(f"/api/investigations/{inv['id']}").status_code == 409
    assert client.delete(f"/api/workspaces/{ws['id']}").status_code == 409
    client.patch(f"/api/studies/{sid}", json={"title": "Edited while withdrawn"})
    assert client.get(f"/api/studies/{sid}").json()["latest_version"] == 1
    client.post("/api/auth/logout")

    signup(client, "reader@lab.test")
    for path in (f"/api/studies/{sid}", f"/api/studies/{sid}?version=1", f"/api/studies/{sid}/samples", f"/api/studies/{sid}/sbol"):
        r = client.get(path)
        assert r.status_code == 410, path
    notice = client.get(f"/api/studies/{sid}").json()["detail"]
    assert notice["withdrawn"]["reason"] == "Plate reader was miscalibrated" and notice["withdrawn"]["versions"] == 1
    _login(client, "ada@lab.test")

    out = client.post(f"/api/studies/{sid}/publish", json={"license": "CC-BY-4.0", "authors": AUTHORS}).json()
    assert (out["visibility"], out["latest_version"], out["withdraw_reason"]) == ("public", 2, "")
    kinds = [e["kind"] for e in client.get(f"/api/studies/{sid}/events").json()]
    assert kinds == ["published", "withdrawn", "published"]


def test_raw_files_stay_while_a_version_uses_them(client, data_dir, plate_bytes):
    _ws, _inv, _study, _s, assay = _published(client, plate_bytes)
    files = [p for p in (data_dir / "artifacts").rglob("*") if p.is_file()]
    assert len(files) == 1
    client.delete(f"/api/assays/{assay['id']}")
    assert files[0].exists()
    assert client.get(f"/api/assays/{assay['id']}/raw?version=1").content == plate_bytes


def test_studies_public_before_versions_get_a_first_version(client):
    ws = signup(client, "ada@lab.test", "Ada")["workspaces"][0]
    _, study = _project(client, ws["id"])
    with client.app.state.sessionmaker() as db:
        db.execute(update(Study).where(Study.id == study["id"]).values(visibility="public"))
        db.commit()
    assert client.get(f"/api/studies/{study['id']}").json()["license"] is None
    (v1,) = client.get(f"/api/studies/{study['id']}/versions").json()
    assert (v1["number"], v1["note"], v1["author"]) == (1, "Public before BOB kept versions", None)
    out = client.post(f"/api/studies/{study['id']}/publish", json={"license": "CC-BY-4.0", "authors": AUTHORS}).json()
    assert out["latest_version"] == 2
    assert client.get(f"/api/studies/{study['id']}/versions").json()[0]["note"] == "License set"
    assert client.delete(f"/api/studies/{study['id']}").status_code == 409


def test_a_published_study_names_its_authors(client):
    ws = signup(client, "ada@lab.test", "Ada")["workspaces"][0]
    _, study = _project(client, ws["id"])
    sid = study["id"]
    no_authors = client.post(f"/api/studies/{sid}/publish", json={"license": "CC-BY-4.0"})
    assert no_authors.status_code == 422 and "author" in no_authors.json()["detail"]
    bad = [{"given_name": "Ada", "orcid": "0000-0002-1825-0098"}]
    assert client.post(f"/api/studies/{sid}/publish", json={"license": "CC-BY-4.0", "authors": bad}).status_code == 422
    assert client.post(f"/api/studies/{sid}/publish", json={"license": "CC-BY-4.0", "authors": [{"given_name": " "}]}).status_code == 422

    authors = AUTHORS + [{"given_name": "Charles", "family_name": "Babbage", "orcid": "https://orcid.org/0000-0001-5109-3700"}]
    out = client.post(f"/api/studies/{sid}/publish", json={"license": "CC-BY-4.0", "authors": authors}).json()
    assert [a["family_name"] for a in out["authors"]] == ["Lovelace", "Babbage"]
    assert out["authors"][1]["orcid"] == "0000-0001-5109-3700" and out["authors"][1]["affiliation"] == ""
    assert client.patch(f"/api/studies/{sid}", json={"authors": []}).status_code == 422
    client.patch(f"/api/studies/{sid}", json={"authors": authors[::-1]})
    history = client.get(f"/api/studies/{sid}/versions").json()
    assert history[0]["note"] == "Edited the study details" and history[0]["number"] == 2
    assert [a["given_name"] for a in client.get(f"/api/studies/{sid}?version=1").json()["authors"]] == ["Ada", "Charles"]


def test_any_signed_in_user_finds_published_studies(client, plate_bytes):
    _, inv, study, _, _ = _published(client, plate_bytes)
    private = client.post(f"/api/investigations/{inv['id']}/studies", json={"title": "Still private"}).json()
    other = client.post(f"/api/investigations/{inv['id']}/studies", json={"title": "Withdrawn later"}).json()
    client.post(f"/api/studies/{other['id']}/publish", json={"license": "CC0-1.0", "authors": AUTHORS})
    client.post(f"/api/studies/{other['id']}/withdraw", json={"reason": "Wrong plate"})
    client.post("/api/auth/logout")
    assert client.get("/api/published").status_code == 401
    signup(client, "reader@lab.test", "Reader")
    listed = client.get("/api/published").json()
    assert [s["id"] for s in listed] == [study["id"]] and private["id"] not in {s["id"] for s in listed}
    assert listed[0]["authors"][0]["family_name"] == "Lovelace" and listed[0]["version_created_at"]
