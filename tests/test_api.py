import statistics
import re

import pytest
from fastapi.testclient import TestClient

from bob import fixtures
from tests.conftest import signup


def _project(client, ws_id):
    inv = client.post(f"/api/workspaces/{ws_id}/investigations", json={"title": "Inv"}).json()
    study = client.post(f"/api/investigations/{inv['id']}/studies", json={"title": "Study"}).json()
    return inv, study


def _samples(client, study_id):
    def make(name, sample_type, iris):
        body = {"name": name, "sample_type": sample_type, "components": [{"role": "strain", "iri": i} for i in iris]}
        r = client.post(f"/api/studies/{study_id}/samples", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return {
        "consortium": make("Consortium X", "sample", ["https://sbh.test/a/1", "https://sbh.test/b/1"]),
        "host": make("Host", "untransformed", ["https://sbh.test/host/1"]),
        "medium": make("Medium", "medium", []),
    }


def _upload(client, study_id, plate_bytes):
    files = {"file": ("plate.xlsx", plate_bytes, "application/octet-stream")}
    r = client.post(f"/api/studies/{study_id}/assays", data={"name": "Plate", "mapping_key": "biotek-gen5-kinetic"}, files=files)
    assert r.status_code == 201, r.text
    return r.json()


def test_signup_creates_personal_workspace_and_session(client):
    me = signup(client, "ada@lab.test", "Ada")
    assert me["user"]["email"] == "ada@lab.test"
    assert [w["role"] for w in me["workspaces"]] == ["owner"]
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "ada@lab.test", "password": "wrong password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ADA@lab.test", "password": "correct horse"}).status_code == 200


def test_duplicate_email_and_short_password_are_refused(client):
    signup(client, "ada@lab.test")
    assert client.post("/api/auth/signup", json={"email": "ada@lab.test", "name": "X", "password": "long enough"}).status_code == 409
    assert client.post("/api/auth/signup", json={"email": "b@lab.test", "name": "X", "password": "short"}).status_code == 422


def test_full_plate_reader_path(client, plate_bytes):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    samples = _samples(client, study["id"])
    assay = _upload(client, study["id"], plate_bytes)
    assert [s["name"] for s in assay["signals"]] == ["OD600", "CFP", "YFP"]
    assert len(assay["raw_file"]["sha256"]) == 64

    assign = {p: samples["consortium"]["id"] for p in fixtures.CONSORTIUM}
    assign |= {p: samples["host"]["id"] for p in fixtures.UNTRANSFORMED}
    assign |= {p: samples["medium"]["id"] for p in fixtures.MEDIUM}
    layout = client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assign}).json()
    assert sum(1 for p in layout["positions"] if p["sample_id"]) == 9

    corrected_against = {"controls": ",".join(fixtures.UNTRANSFORMED),
                         "samples": samples["consortium"]["id"], "context_acknowledged": "true"}
    series = client.get(f"/api/assays/{assay['id']}/series",
                        params={"signal": "YFP", **corrected_against}).json()
    assert series["corrected"] is True and series["control_type"] == "untransformed"
    consortium = next(g for g in series["groups"] if g["group"] == "Consortium X")
    assert consortium["mean"] == pytest.approx([50.0 * k for k in range(fixtures.N_READS)])
    assert consortium["sd"] == pytest.approx([10.0] * fixtures.N_READS)

    me = client.get(f"/api/assays/{assay['id']}/mean-expression",
                    params={"signal": "YFP", **corrected_against}).json()
    row = next(g for g in me["groups"] if g["group"] == "Consortium X")
    assert row["mean"] == pytest.approx(300.0) and row["sd"] == pytest.approx(10.0) and row["n"] == 3

    per_od = client.get(f"/api/assays/{assay['id']}/mean-expression", params={
        "signal": "YFP", "normalize_by": "OD600",
        "normalize_controls": ",".join(fixtures.MEDIUM), **corrected_against}).json()
    # OD is resampled onto YFP's own timestamps. The YFP block is read 93 s after the OD block, so
    # the biomass at each reporter reading is 0.01 * 93/600 larger than the OD of the same cycle,
    # and every ratio sits below 5000. The OD floor keeps cycles 5 to 11.
    lag = (543 - 450) / 600
    expected = statistics.fmean(50 * k / (0.01 * (k + lag)) for k in range(5, 12))
    per_od_mean = next(g for g in per_od["groups"] if g["group"] == "Consortium X")["mean"]
    assert per_od_mean < 5000.0
    assert per_od_mean == pytest.approx(expected, rel=1e-12)

    raw = client.get(f"/api/assays/{assay['id']}/raw")
    assert raw.status_code == 200 and raw.content == plate_bytes

    sbol = client.get(f"/api/studies/{study['id']}/sbol")
    assert sbol.status_code == 200 and "https://sbh.test/a/1" in sbol.text and "Experiment" in sbol.text
    assert "http://edamontology.org/format_3620" in sbol.text

    isa = client.get(f"/api/investigations/{study['investigation_id']}/isa").json()
    (isa_study,) = isa["studies"]
    (isa_assay,) = isa_study["assays"]
    assert {s["name"] for s in isa_study["materials"]["samples"]} == {"Consortium X", "Host", "Medium"}
    assert len(isa_assay["materials"]["samples"]) == 3
    assert {"name": "sha256", "value": assay["raw_file"]["sha256"]} in isa_assay["dataFiles"][0]["comments"]


def test_analysis_parameters_accept_booleans_and_zero_min_od(client, plate_bytes):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    samples = _samples(client, study["id"])
    assay = _upload(client, study["id"], plate_bytes)
    assign = ({p: samples["medium"]["id"] for p in fixtures.MEDIUM}
              | {p: samples["host"]["id"] for p in fixtures.UNTRANSFORMED}
              | {p: samples["consortium"]["id"] for p in fixtures.CONSORTIUM})
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assign})
    sel = {"controls": ",".join(fixtures.UNTRANSFORMED), "samples": samples["consortium"]["id"],
           "normalize_controls": ",".join(fixtures.MEDIUM), "context_acknowledged": "true"}
    for params in ({"correct": "true", "drop_below": "false", **sel}, {"correct": 0},
                   {"normalize_by": "OD600", "min_od": 0, **sel}):
        r = client.get(f"/api/assays/{assay['id']}/series", params={"signal": "YFP", **params})
        assert r.status_code == 200, (params, r.text)
    r = client.get(f"/api/assays/{assay['id']}/mean-expression",
                   params={"signal": "YFP", "normalize_by": "OD600", "min_od": 0, **sel})
    assert r.status_code == 200, r.text


def test_component_iri_must_be_absolute(client):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    bad = {"name": "X", "components": [{"role": "strain", "iri": "E. coli DH5a"}]}
    assert client.post(f"/api/studies/{study['id']}/samples", json=bad).status_code == 422
    blank = {"name": "Y", "components": [{"role": "strain", "iri": ""}]}
    assert client.post(f"/api/studies/{study['id']}/samples", json=blank).json()["components"] == []


def test_correction_is_refused_when_no_controls_are_assigned_and_raw_is_offered(client, plate_bytes):
    """A corrected request without selectable controls refuses rather than returning raw
    values under a corrected claim. Raw stays available and says it is raw."""
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    assay = _upload(client, study["id"], plate_bytes)
    refused = client.get(f"/api/assays/{assay['id']}/series", params={"signal": "YFP"})
    assert refused.status_code == 422, refused.text
    assert "turn correction off to plot raw values" in refused.json()["detail"]
    raw = client.get(f"/api/assays/{assay['id']}/series",
                     params={"signal": "YFP", "correct": "false"}).json()
    assert raw["corrected"] is False and raw["control_positions"] == []


def test_unreadable_upload_is_rejected(client):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    files = {"file": ("x.xlsx", b"not a workbook", "application/octet-stream")}
    r = client.post(f"/api/studies/{study['id']}/assays", data={"mapping_key": "biotek-gen5-kinetic"}, files=files)
    assert r.status_code == 422


def test_roles_limit_what_members_can_do(client, plate_bytes):
    owner_ws = signup(client, "owner@lab.test", "Owner")["workspaces"][0]
    inv, study = _project(client, owner_ws["id"])
    client.post("/api/auth/logout")
    signup(client, "viewer@lab.test", "Viewer")
    client.post("/api/auth/logout")
    signup(client, "stranger@lab.test", "Stranger")
    assert client.get(f"/api/studies/{study['id']}").status_code == 404
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"email": "owner@lab.test", "password": "correct horse"})
    r = client.post(f"/api/workspaces/{owner_ws['id']}/invitations", json={"email": "viewer@lab.test", "role": "viewer"})
    assert r.status_code == 202
    owner_id = client.get("/api/auth/me").json()["user"]["id"]
    assert client.patch(f"/api/workspaces/{owner_ws['id']}/members/{owner_id}", json={"role": "editor"}).status_code == 409
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"email": "viewer@lab.test", "password": "correct horse"})
    (invitation,) = client.get("/api/invitations").json()
    assert client.post(f"/api/invitations/{invitation['id']}/accept").json()["role"] == "viewer"
    assert client.get(f"/api/studies/{study['id']}").status_code == 200
    assert client.post(f"/api/investigations/{inv['id']}/studies", json={"title": "Nope"}).status_code == 403
    assert client.delete(f"/api/studies/{study['id']}").status_code == 403
    assert client.post(f"/api/workspaces/{owner_ws['id']}/invitations", json={"email": "stranger@lab.test"}).status_code == 403


def test_invitations_need_consent_and_reveal_no_accounts(client):
    ws = signup(client, "owner@lab.test", "Owner")["workspaces"][0]
    client.post("/api/auth/logout")
    signup(client, "known@lab.test", "Known")
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "owner@lab.test", "password": "correct horse"})

    known = client.post(f"/api/workspaces/{ws['id']}/invitations", json={"email": "known@lab.test", "role": "editor"})
    unknown = client.post(f"/api/workspaces/{ws['id']}/invitations", json={"email": "later@lab.test", "role": "editor"})
    assert known.status_code == unknown.status_code == 202
    assert known.json().keys() == unknown.json().keys()
    assert [m["email"] for m in client.get(f"/api/workspaces/{ws['id']}/members").json()] == ["owner@lab.test"]
    assert client.post(f"/api/workspaces/{ws['id']}/invitations", json={"email": "OWNER@lab.test"}).status_code == 409
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={"email": "known@lab.test", "password": "correct horse"})
    assert client.get("/api/auth/me").json()["invitations"] == 1
    (invitation,) = client.get("/api/invitations").json()
    assert invitation["workspace_name"] == ws["name"] and invitation["invited_by"] == "Owner"
    assert client.post(f"/api/invitations/{invitation['id']}/decline").status_code == 204
    assert client.get(f"/api/workspaces/{ws['id']}/members").status_code == 404
    client.post("/api/auth/logout")

    later = signup(client, "later@lab.test", "Later")
    assert later["invitations"] == 1
    (invitation,) = client.get("/api/invitations").json()
    client.post("/api/auth/logout")
    signup(client, "other@lab.test")
    assert client.post(f"/api/invitations/{invitation['id']}/accept").status_code == 404
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "later@lab.test", "password": "correct horse"})
    assert client.post(f"/api/invitations/{invitation['id']}/accept").status_code == 200
    roles = {m["email"]: m["role"] for m in client.get(f"/api/workspaces/{ws['id']}/members").json()}
    assert roles == {"owner@lab.test": "owner", "later@lab.test": "editor"}


def test_sign_in_and_sign_up_attempts_are_limited(client):
    signup(client, "ada@lab.test")
    client.post("/api/auth/logout")
    wrong = {"email": "ada@lab.test", "password": "wrong password"}
    assert all(client.post("/api/auth/login", json=wrong).status_code == 401 for _ in range(10))
    r = client.post("/api/auth/login", json=wrong)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert client.post("/api/auth/login", json={"email": "ada@lab.test", "password": "correct horse"}).status_code == 429
    statuses = [client.post("/api/auth/signup", json={"email": f"u{i}@lab.test", "name": "U", "password": "long enough"}).status_code for i in range(10)]
    assert statuses[-1] == 429 and statuses[:9].count(201) == 9


def test_password_change_revokes_api_tokens_unless_asked_to_keep_them(client):
    signup(client, "ada@lab.test")
    keep = client.post("/api/auth/tokens", json={"name": "kept"}).json()["token"]
    change = {"current_password": "correct horse", "new_password": "second horse battery", "revoke_tokens": False}
    assert client.patch("/api/auth/me", json=change).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {keep}"}).status_code == 200
    change = {"current_password": "second horse battery", "new_password": "third horse battery"}
    assert client.patch("/api/auth/me", json=change).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {keep}"}).status_code == 401
    assert client.get("/api/auth/tokens").json() == []


def test_cross_site_writes_are_refused(client):
    signup(client, "ada@lab.test")
    r = client.post("/api/workspaces", json={"name": "Evil"}, headers={"Origin": "https://evil.test"})
    assert r.status_code == 403


def test_api_token_authenticates_without_a_session(client):
    signup(client, "ada@lab.test")
    token = client.post("/api/auth/tokens", json={"name": "notebook"}).json()["token"]
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "ada@lab.test"
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer bob_wrong"}).status_code == 401


def test_mappings_are_listed_starred_and_versioned(client):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    listed = {m["key"]: m for m in client.get("/api/mappings").json()}
    assert {k: (m["builtin"], m["source_format"]) for k, m in listed.items()} == {
        "biotek-gen5-kinetic": (True, "xlsx"), "biotek-gen5-kinetic-text": (True, "delimited")}
    builtin = listed["biotek-gen5-kinetic"]
    assert client.post(f"/api/mappings/{builtin['id']}/star").json() == {"stars": 1, "starred": True}
    spec = client.get(f"/api/mappings/{builtin['id']}").json()["spec"]
    spec = {**spec, "key": "my-reader", "name": "My reader", "emoji": "🔬"}
    first = client.post(f"/api/workspaces/{ws['id']}/mappings", json={"spec": spec}).json()
    second = client.post(f"/api/workspaces/{ws['id']}/mappings", json={"spec": spec}).json()
    assert (first["version"], second["version"]) == (1, 2)
    bad = client.post(f"/api/workspaces/{ws['id']}/mappings", json={"spec": {**spec, "key": "Bad Key"}})
    assert bad.status_code == 422 and "key" in bad.json()["detail"]


def test_password_change_and_sign_out_everywhere_end_other_sessions(data_dir):
    from fastapi.testclient import TestClient

    from bob.main import create_app

    app = create_app()
    with TestClient(app) as laptop, TestClient(app) as phone:
        signup(laptop, "ada@lab.test")
        phone.post("/api/auth/login", json={"email": "ada@lab.test", "password": "correct horse"})
        assert phone.get("/api/auth/me").status_code == 200
        r = laptop.patch("/api/auth/me", json={"current_password": "correct horse", "new_password": "new horse battery"})
        assert r.status_code == 200
        assert laptop.get("/api/auth/me").status_code == 200
        assert phone.get("/api/auth/me").status_code == 401
        phone.post("/api/auth/login", json={"email": "ada@lab.test", "password": "new horse battery"})
        assert laptop.post("/api/auth/logout-all").status_code == 204
        assert laptop.get("/api/auth/me").status_code == 401
        assert phone.get("/api/auth/me").status_code == 401


def test_signup_can_be_closed(data_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from bob.main import create_app

    monkeypatch.setenv("BOB_ALLOW_SIGNUP", "0")
    with TestClient(create_app()) as c:
        r = c.post("/api/auth/signup", json={"email": "a@lab.test", "name": "A", "password": "long enough"})
        assert r.status_code == 403


def test_unknown_host_header_is_refused(client):
    assert client.get("/health", headers={"Host": "attacker.test"}).status_code == 400
    assert client.get("/health").status_code == 200


def test_only_web_and_urn_iris_are_accepted(client):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    for iri, ok in (("javascript:alert(1)", False), ("data:text/html,x", False), ("urn:uuid:1234", True), ("HTTPS://sbh.test/x/1", True)):
        r = client.post(f"/api/studies/{study['id']}/samples", json={"name": "S", "components": [{"role": "strain", "iri": iri}]})
        assert (r.status_code == 201) is ok, (iri, r.status_code)


def _workbook_with_label(label: str) -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append([label])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_user_mappings_run_isolated_with_a_time_limit(client, plate_bytes, monkeypatch):
    monkeypatch.setenv("BOB_MAPPING_TIMEOUT_S", "3")
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    base = client.get(f"/api/mappings/{client.get('/api/mappings').json()[0]['id']}").json()["spec"]

    copy = {**base, "key": "gen5-copy", "name": "Gen5 copy"}
    assert client.post(f"/api/workspaces/{ws['id']}/mappings", json={"spec": copy}).status_code == 201
    files = {"file": ("plate.xlsx", plate_bytes, "application/octet-stream")}
    r = client.post(f"/api/studies/{study['id']}/assays", data={"mapping_key": "gen5-copy"}, files=files)
    assert r.status_code == 201 and [s["name"] for s in r.json()["signals"]] == ["OD600", "CFP", "YFP"]

    evil = {**base, "key": "evil", "name": "Evil", "blocks": {**base["blocks"], "label_pattern": "^(a+)+$"}}
    assert client.post(f"/api/workspaces/{ws['id']}/mappings", json={"spec": evil}).status_code == 201
    files = {"file": ("x.xlsx", _workbook_with_label("a" * 40 + "!"), "application/octet-stream")}
    r = client.post(f"/api/studies/{study['id']}/assays", data={"mapping_key": "evil"}, files=files)
    assert r.status_code == 422 and "longer than" in r.json()["detail"]
    assert client.get("/health").status_code == 200


def test_builtin_mapping_keys_cannot_be_shadowed(client):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    builtin = client.get(f"/api/mappings/{client.get('/api/mappings').json()[0]['id']}").json()["spec"]
    r = client.post(f"/api/workspaces/{ws['id']}/mappings", json={"spec": builtin})
    assert r.status_code == 409


def test_mean_expression_reports_whether_correction_ran(client, plate_bytes):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    assay = _upload(client, study["id"], plate_bytes)
    refused = client.get(f"/api/assays/{assay['id']}/mean-expression", params={"signal": "YFP"})
    assert refused.status_code == 422, refused.text
    me = client.get(f"/api/assays/{assay['id']}/mean-expression",
                    params={"signal": "YFP", "correct": "false"}).json()
    assert me["corrected"] is False


def test_deleting_removes_raw_files_only_when_unused(client, data_dir, plate_bytes):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    first = _upload(client, study["id"], plate_bytes)
    second = _upload(client, study["id"], plate_bytes)
    sha = first["raw_file"]["sha256"]
    path = data_dir / "artifacts" / sha[:2] / sha
    assert path.exists()
    assert client.delete(f"/api/assays/{first['id']}").status_code == 204
    assert path.exists() and client.get(f"/api/assays/{second['id']}/raw").status_code == 200
    assert client.delete(f"/api/studies/{study['id']}").status_code == 204
    assert not path.exists()


def test_deleting_a_workspace_removes_its_raw_files(client, data_dir, plate_bytes):
    signup(client, "ada@lab.test")
    ws = client.post("/api/workspaces", json={"name": "Temp"}).json()
    _, study = _project(client, ws["id"])
    sha = _upload(client, study["id"], plate_bytes)["raw_file"]["sha256"]
    path = data_dir / "artifacts" / sha[:2] / sha
    assert client.delete(f"/api/workspaces/{ws['id']}").status_code == 204
    assert not path.exists()


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_api_docs_load_nothing_from_other_sites(client):
    page = client.get("/docs")
    assert page.status_code == 200
    policy = page.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy and "https:" not in policy
    sources = re.findall(r'(?:src|href)="([^"]+)"|url: ?["\']([^"\']+)', page.text)
    assert sources and all(not (a or b).startswith(("http:", "https:", "//")) for a, b in sources)
    assert '"validatorUrl": null' in page.text
    for asset in ("/docs-static/swagger-ui-bundle.js", "/docs-static/swagger-ui.css"):
        assert client.get(asset).status_code == 200
    assert client.get("/redoc").status_code == 404


def test_unknown_pages_get_the_html_404_and_unknown_api_paths_stay_json(data_dir, monkeypatch):
    monkeypatch.setenv("BOB_MODE", "full")
    from bob.main import create_app

    with TestClient(create_app()) as c:
        page = c.get("/no/such/page")
        assert page.status_code == 404 and "text/html" in page.headers["content-type"]
        assert "Page not found" in page.text
        api = c.get("/api/no-such-endpoint")
        assert api.status_code == 404 and api.json() == {"detail": "Not Found"}
        assert c.get("/").status_code == 200


def test_the_page_names_its_release_so_browsers_drop_older_files(data_dir, monkeypatch):
    monkeypatch.setenv("BOB_MODE", "full")
    from bob import __version__
    from bob.main import create_app

    with TestClient(create_app()) as c:
        for path in ("/", "/index.html"):
            page = c.get(path)
            assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
            assert f"app.js?v={__version__}" in page.text and f"style.css?v={__version__}" in page.text and "__BOB_VERSION__" not in page.text
        for asset in ("/app.js", "/style.css", "/plot.js", "/icon.svg"):
            assert c.get(asset).headers["cache-control"] == "no-cache"
        assert c.get("/no/such/page").headers["cache-control"] == "no-cache"


def test_text_is_cleaned_and_blank_names_refused(client, plate_bytes):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    assert client.post(f"/api/workspaces/{ws['id']}/investigations", json={"title": "   "}).status_code == 422
    inv = client.post(f"/api/workspaces/{ws['id']}/investigations", json={"title": "Soft\x0bbreak \x00here"}).json()
    assert inv["title"] == "Soft break  here"
    study = client.post(f"/api/investigations/{inv['id']}/studies", json={"title": "S\x0b1"}).json()
    client.post(f"/api/studies/{study['id']}/samples", json={"name": "Sample\x0b", "components": [{"role": "strain", "iri": "https://sbh.test/a/1", "label": "L\x0b"}]})
    bad_iri = {"name": "X", "components": [{"role": "strain", "iri": "https://sbh.test/<a>"}]}
    assert client.post(f"/api/studies/{study['id']}/samples", json=bad_iri).status_code == 422
    files = {"file": ("..", plate_bytes, "application/octet-stream")}
    a = client.post(f"/api/studies/{study['id']}/assays", data={"mapping_key": "biotek-gen5-kinetic"}, files=files).json()
    assert a["raw_file"]["filename"] == "upload.xlsx"
    assert client.get(f"/api/studies/{study['id']}/sbol").status_code == 200


def test_demo_seed(data_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from bob.main import create_app

    monkeypatch.setenv("BOB_SEED_DEMO", "1")
    with TestClient(create_app()) as c:
        assert c.post("/api/auth/login", json={"email": "demo@bob.local", "password": "bob-demo-2026"}).status_code == 200
        ws = c.get("/api/auth/me").json()["workspaces"][0]
        (inv,) = c.get(f"/api/workspaces/{ws['id']}/investigations").json()
        (study,) = c.get(f"/api/investigations/{inv['id']}/studies").json()
        (assay,) = c.get(f"/api/studies/{study['id']}/assays").json()
        layout = c.get(f"/api/assays/{assay['id']}/layout").json()
        by_name = {s["name"]: s for s in layout["samples"]}
        host_id = next(s["id"] for s in layout["samples"] if s["sample_type"] == "untransformed")
        untransformed = sorted(p["position"] for p in layout["positions"]
                               if p["sample_id"] == host_id)
        consortium = by_name["Consortium X"]["id"]
        me = c.get(f"/api/assays/{assay['id']}/mean-expression", params={
            "signal": "YFP", "controls": ",".join(untransformed),
            "samples": consortium, "context_acknowledged": "true"}).json()
        assert next(g for g in me["groups"] if g["group"] == "Consortium X")["mean"] == pytest.approx(300.0)
    with TestClient(create_app()) as c:
        assert c.post("/api/auth/login", json={"email": "demo@bob.local", "password": "bob-demo-2026"}).status_code == 200


def test_the_home_page_overview_counts_a_workspace_and_ranks_studies_by_activity(client, plate_bytes):
    ws = signup(client, "ada@lab.test", "Ada")["workspaces"][0]
    inv, older = _project(client, ws["id"])
    newer = client.post(f"/api/investigations/{inv['id']}/studies", json={"title": "Newer"}).json()
    _samples(client, older["id"])
    _upload(client, older["id"], plate_bytes)
    out = client.get(f"/api/workspaces/{ws['id']}/overview").json()
    assert (out["investigations"], out["studies"], out["assays"], out["published"]) == (1, 2, 1, 0) and out["samples"] > 0
    assert [s["id"] for s in out["recent"]] == [older["id"], newer["id"]]
    assert out["recent"][0]["investigation_title"] == "Inv" and out["recent"][0]["last_activity"]
    client.post("/api/auth/logout")
    signup(client, "eve@lab.test", "Eve")
    assert client.get(f"/api/workspaces/{ws['id']}/overview").status_code in (403, 404)
