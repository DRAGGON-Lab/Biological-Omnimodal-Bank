"""ISA-JSON serialization of study snapshots (see bob.versions).

Follows the ISA-JSON layout (investigation, studies, materials, protocols, processes, assays,
data files). Sample links to strains and other components travel as comments carrying the IRI,
because ISA has no native slot for an external design reference.
"""

import re

from bob.models import Investigation
from bob.terms import OBI, ONTOLOGY_SOURCES, XLSX_FORMAT

RECIPE_COMMENT = "BOB analysis recipe manifest"
PROTOCOL_TYPE = {"annotationValue": "assay", "termSource": "OBI", "termAccession": OBI + "0000070", "comments": []}
PLATE_READER = {"annotationValue": "microplate reader", "termSource": "OBI", "termAccession": OBI + "0001058", "comments": []}


def _comment(name: str, value) -> dict:
    return {"name": name, "value": "" if value is None else str(value)}


def _date(iso: str | None) -> str:
    return iso[:10] if iso else ""


def person(author: dict, n: int) -> dict:
    comments = [_comment("ORCID", "https://orcid.org/" + author["orcid"])] if author.get("orcid") else []
    return {
        "@id": f"#person/{n}",
        "firstName": author["given_name"],
        "lastName": author.get("family_name", ""),
        "midInitials": "",
        "email": "",
        "phone": "",
        "fax": "",
        "address": "",
        "affiliation": author.get("affiliation", ""),
        "roles": [],
        "comments": comments,
    }


def _annotation(value: str) -> dict:
    return {"annotationValue": value, "termSource": "", "termAccession": "", "comments": []}


def _amounts(samples: list[dict]) -> tuple[dict[str, list[dict]], list[dict], list[dict]]:
    """Each part with an amount as a characteristic of its sample, named after the part."""
    per_sample: dict[str, list[dict]] = {}
    categories: dict[str, dict] = {}
    units: dict[str, dict] = {}
    for s in samples:
        for c in s["components"]:
            if c.get("amount") is None:
                continue
            name = c["label"] or c["role"]
            cat_id = "#characteristic_category/" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "part")
            categories.setdefault(cat_id, {"@id": cat_id, "characteristicType": _annotation(name)})
            value = {"category": {"@id": cat_id}, "value": c["amount"], "comments": [_comment("IRI", c["iri"])]}
            if c.get("unit"):
                unit_id = "#unit/" + (re.sub(r"[^a-z0-9]+", "-", c["unit"].lower()).strip("-") or "unit")
                units.setdefault(unit_id, {"@id": unit_id, **_annotation(c["unit"])})
                value["unit"] = {"@id": unit_id}
            per_sample.setdefault(s["id"], []).append(value)
    return per_sample, list(categories.values()), list(units.values())


def _protocol_id(a: dict) -> str:
    return f"#protocol/{a['mapping_key']}/v{a['mapping_version']}"


def study_block(snap: dict, base_iri: str, released: str = "", version: int | None = None) -> dict:
    """One ISA study. `released` is the date the study was first published, empty if never."""
    query = f"?version={version}" if version else ""
    st = snap["study"]
    amounts, categories, units = _amounts(snap["samples"])
    samples = [
        {
            "@id": f"#sample/{s['id']}",
            "name": s["name"],
            "characteristics": amounts.get(s["id"], []),
            "factorValues": [],
            "derivesFrom": [],
            "comments": [_comment("sample type", s["sample_type"]), *[_comment(f"{c['role']} IRI", c["iri"]) for c in s["components"]]],
        }
        for s in snap["samples"]
    ]
    protocols, assays = {}, []
    for a in snap["assays"]:
        raw = a["raw_file"]
        kinds = sorted({sig["kind"] for sig in a["signals"]})
        model = (a["run_metadata"] or {}).get("instrument_model", "")
        protocols.setdefault(_protocol_id(a), {
            "@id": _protocol_id(a),
            "name": f"Plate-reader measurement read with BOB mapping {a['mapping_key']} v{a['mapping_version']}",
            "protocolType": PROTOCOL_TYPE,
            "description": f"Kinetic plate-reader run exported by the instrument and read by the BOB mapping {a['mapping_name']}.",
            "uri": "",
            "version": str(a["mapping_version"]),
            "parameters": [],
            "components": [{"componentName": model or "microplate reader", "componentType": PLATE_READER}],
            "comments": [],
        })
        data_id = f"#data/{raw['artifact_id']}"
        measured = sorted(set(a["layout"].values()))
        assays.append(
            {
                "@id": f"#assay/{a['id']}",
                "filename": f"a_{a['id']}.txt",
                "measurementType": {"annotationValue": ", ".join(kinds), "termSource": "", "termAccession": "", "comments": []},
                "technologyType": PLATE_READER,
                "technologyPlatform": model,
                "dataFiles": [
                    {
                        "@id": data_id,
                        "name": raw["filename"],
                        "type": "Raw Data File",
                        "comments": [
                            _comment("sha256", raw["sha256"]),
                            _comment("url", f"{base_iri}/api/assays/{a['id']}/raw{query}"),
                            _comment("format", XLSX_FORMAT),
                            _comment("BOB mapping", f"{a['mapping_key']} v{a['mapping_version']}"),
                        ],
                    }
                ],
                "materials": {"samples": [{"@id": f"#sample/{sid}"} for sid in measured], "otherMaterials": []},
                "processSequence": [
                    {
                        "@id": f"#process/{a['id']}",
                        "name": a["name"],
                        "executesProtocol": {"@id": _protocol_id(a)},
                        "parameterValues": [],
                        "date": (a["run_metadata"] or {}).get("run_date", ""),
                        "inputs": [{"@id": f"#sample/{sid}"} for sid in measured],
                        "outputs": [{"@id": data_id}],
                        "comments": [],
                    }
                ],
                "characteristicCategories": [],
                "unitCategories": [],
                "comments": [_comment("name", a["name"])],
            }
        )
    comments = [_comment("BOB IRI", f"{base_iri}/api/studies/{st['id']}{query}")]
    if version:
        comments.append(_comment("BOB version", version))
    if st.get("license"):
        comments.append(_comment("license", st["license"]))
    return {
        "@id": f"#study/{st['id']}",
        "identifier": st["id"],
        "filename": f"s_{st['id']}.txt",
        "title": st["title"],
        "description": st["description"],
        "submissionDate": _date(st["created_at"]),
        "publicReleaseDate": released,
        "materials": {"sources": [], "samples": samples, "otherMaterials": []},
        "protocols": list(protocols.values()),
        "processSequence": [],
        "assays": assays,
        "factors": [],
        "characteristicCategories": categories,
        "unitCategories": units,
        "people": [person(a, n) for n, a in enumerate(st.get("authors", []), start=1)],
        "publications": [],
        "studyDesignDescriptors": [],
        "comments": comments,
    }


def with_recipe_manifest(study: dict, manifest_json: str) -> dict:
    """Attach the recipe manifest as a documented study-level comment, serialized as a string.

    ISA has no native representation for analysis configuration, and the schemas forbid arbitrary
    properties, so a comment is the supported carrier. The payload stays independently parseable.
    """
    out = dict(study)
    out["comments"] = [c for c in study.get("comments", []) if c.get("name") != RECIPE_COMMENT]
    out["comments"] = out["comments"] + [_comment(RECIPE_COMMENT, manifest_json)]
    return out


def export_investigation(inv: Investigation, workspace_name: str, base_iri: str, studies: list[dict]) -> dict:
    """The whole investigation, for its workspace members. `studies` are study blocks."""
    return {
        "identifier": inv.id,
        "title": inv.title,
        "description": inv.description,
        "submissionDate": inv.created_at.date().isoformat(),
        "publicReleaseDate": "",
        "ontologySourceReferences": ONTOLOGY_SOURCES,
        "people": [],
        "publications": [],
        "comments": [_comment("BOB workspace", workspace_name), _comment("BOB IRI", f"{base_iri}/api/investigations/{inv.id}")],
        "studies": studies,
    }


def export_study(block: dict) -> dict:
    """One study wrapped as an investigation, carrying nothing from the real investigation, so it
    can go to readers of a public study who are not members of its workspace."""
    return {
        "identifier": block["identifier"],
        "title": block["title"],
        "description": block["description"],
        "submissionDate": block["submissionDate"],
        "publicReleaseDate": block["publicReleaseDate"],
        "ontologySourceReferences": ONTOLOGY_SOURCES,
        "people": block["people"],
        "publications": [],
        "comments": [],
        "studies": [block],
    }

