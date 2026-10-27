import io
import json
import zipfile
from pathlib import Path

import pytest
import requests
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from rocrate_validator import services as rocrate_validation
from rocrate_validator.models import Severity, ValidationSettings
from sbol2 import config as sbol_config

from bob import fixtures
from tests.conftest import signup
from tests.test_api import _project, _samples, _upload

ISA_JSON = Path(__file__).parent / "standards" / "isa-json"
SBOL_VALIDATOR_TIMEOUT_S = 60


@pytest.fixture
def exported(client, plate_bytes):
    ws = signup(client, "ada@lab.test")["workspaces"][0]
    _, study = _project(client, ws["id"])
    samples = _samples(client, study["id"])
    parts = [{"role": "design", "iri": "https://sbh.test/design/1"}, {"role": "strain", "iri": "https://sbh.test/a/1", "label": "host"},
             {"role": "supplement", "iri": "https://sbh.test/iptg/1", "label": "IPTG", "amount": 1.0, "unit": "mM"},
             {"role": "supplement", "iri": "https://sbh.test/ara/1", "label": "arabinose", "amount": 0.004}]
    assert client.patch(f"/api/samples/{samples['consortium']['id']}", json={"components": parts}).status_code == 200
    assay = _upload(client, study["id"], plate_bytes)
    assign = {p: samples["consortium"]["id"] for p in fixtures.CONSORTIUM}
    assign |= {p: samples["host"]["id"] for p in fixtures.UNTRANSFORMED}
    assign |= {p: samples["medium"]["id"] for p in fixtures.MEDIUM}
    client.put(f"/api/assays/{assay['id']}/layout", json={"assignments": assign})
    client.post(f"/api/studies/{study['id']}/publish", json={"license": "CC-BY-4.0", "authors": [{"given_name": "Ada", "family_name": "Lovelace", "orcid": "0000-0002-1825-0097", "affiliation": "Analytical Engine Lab"}]})
    client.patch(f"/api/studies/{study['id']}", json={"description": "Second version"})
    sid = study["id"]
    isa = {
        "investigation": client.get(f"/api/investigations/{study['investigation_id']}/isa").json(),
        "study": client.get(f"/api/studies/{sid}/isa").json(),
        "study version 1": client.get(f"/api/studies/{sid}/isa?version=1").json(),
    }
    sbol = {"latest": client.get(f"/api/studies/{sid}/sbol").text, "version 1": client.get(f"/api/studies/{sid}/sbol?version=1").text}
    crates = {"latest": client.get(f"/api/studies/{sid}/ro-crate").content, "version 1": client.get(f"/api/studies/{sid}/ro-crate?version=1").content}
    return isa, sbol, crates


def validate_isa(isa) -> list[str]:
    """The pinned official ISA-JSON schemas. Returns the errors, empty when the document is valid."""
    files = sorted(ISA_JSON.glob("*_schema.json"))
    schemas = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    # The schemas' $ids point at isa-api's moving master branch; registering the pinned copies
    # under those ids keeps every relative $ref local. Each is also registered under its file
    # name, as isatools resolves them, because ontology_source_reference_schema.json declares
    # the $id ontology_source_schema.json while the investigation schema refers to the file name.
    base = schemas[0]["$id"].rsplit("/", 1)[0] + "/"
    resources = [(s["$id"], Resource.from_contents(s)) for s in schemas]
    resources += [(base + f.name, Resource.from_contents(s)) for f, s in zip(files, schemas)]
    registry = Registry().with_resources(resources)
    root = next(s for s in schemas if s["$id"].endswith("/investigation_schema.json"))
    validator = Draft202012Validator(root, registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(isa), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors[:20]]


@pytest.mark.parametrize("which", ["investigation", "study", "study version 1"])
def test_isa_json_export_matches_the_official_schemas(exported, which):
    errors = validate_isa(exported[0][which])
    assert not errors, "\n".join(errors)


def validate_sbol(sbol: str) -> dict:
    """The official SBOL validator. Skips the calling test when it cannot be reached."""
    opts = sbol_config.options
    keys = ("language", "test_equality", "check_uri_compliance", "check_completeness", "check_best_practices",
            "fail_on_first_error", "provide_detailed_stack_trace", "subset_uri", "uri_prefix", "version",
            "insert_type", "main_file_name", "diff_file_name")
    body = {"options": {k: opts[k] for k in keys if k in opts}, "return_file": False, "main_file": sbol}
    try:
        r = requests.post(opts["validator_url"], json=body, headers={"Accept": "application/json"},
                          timeout=SBOL_VALIDATOR_TIMEOUT_S)
        r.raise_for_status()
    except (requests.ConnectionError, requests.Timeout) as exc:
        pytest.skip(f"SBOL validator unreachable ({type(exc).__name__})")
    return r.json()


@pytest.mark.parametrize("which", ["latest", "version 1"])
def test_sbol_export_passes_the_official_sbol_validator(exported, which):
    result = validate_sbol(exported[1][which])
    assert result["valid"], "\n".join(e.strip() for e in result.get("errors", []) if e.strip())


@pytest.mark.parametrize("which", ["latest", "version 1"])
def test_ro_crate_export_passes_the_ro_crate_validator(exported, which, tmp_path):
    crate = tmp_path / "crate"
    zipfile.ZipFile(io.BytesIO(exported[2][which])).extractall(crate)
    meta = json.loads((crate / "ro-crate-metadata.json").read_text(encoding="utf-8"))
    root = next(e for e in meta["@graph"] if e["@id"] == "./")
    assert root["additionalType"] == "Investigation" and root["version"] == ("2" if which == "latest" else "1")
    assert (crate / root["hasPart"][1]["@id"]).exists() and any(crate.glob("assays/*/dataset/*.xlsx"))
    validate_crate_dir(crate)


def validate_crate_dir(crate) -> None:
    """roc-validator for ro-crate-1.2 and the ISA profile, at REQUIRED severity."""
    for profile in ("ro-crate-1.2", "isa-ro-crate"):
        # The ISA profile is defined on RO-Crate 1.1, whose descriptor rule asks for version 1.1;
        # its inherited rules still run, so the ISA ones can apply, but are not reported.
        settings = ValidationSettings(rocrate_uri=crate.as_posix(), profile_identifier=profile, requirement_severity=Severity.REQUIRED,
                                      disable_inherited_profiles_issue_reporting=profile == "isa-ro-crate")
        issues = rocrate_validation.validate(settings).get_issues()
        unreachable = [i for i in issues if "Unable to retrieve the JSON-LD context" in i.message]
        if unreachable:
            pytest.skip("The RO-Crate JSON-LD context could not be fetched")
        assert not issues, "\n".join(f"{profile}: {i.message}" for i in issues)
