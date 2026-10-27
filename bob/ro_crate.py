"""A study as an RO-Crate 1.2 following the ISA RO-Crate profile 1.0: the raw files, the study's
ISA-JSON and SBOL documents, and ro-crate-metadata.json describing them.

The crate's root is the ISA investigation; for a single study it is built from the study itself,
like isa_export.export_study, so a public study's crate carries nothing from its investigation.
"""

import io
import json
import re
import zipfile

from bob.models import LICENSES
from bob.terms import OBI, SIGNAL_TERMS

RO_CRATE = "https://w3id.org/ro/crate/1.2"
ISA_PROFILE = "https://github.com/nfdi4plants/isa-ro-crate-profile"
CONTEXT = [
    RO_CRATE + "/context",
    {
        "Sample": "https://bioschemas.org/Sample",
        "LabProcess": "https://bioschemas.org/LabProcess",
        "LabProtocol": "https://bioschemas.org/LabProtocol",
        "executesLabProtocol": "https://bioschemas.org/properties/executesLabProtocol",
        "parameterValue": "https://bioschemas.org/properties/parameterValue",
        "intendedUse": "https://bioschemas.org/properties/intendedUse",
        "labEquipment": "https://bioschemas.org/properties/labEquipment",
        # The ISA profile reads a Sample's characteristics from the Bioschemas property.
        "additionalProperty": "https://bioschemas.org/properties/additionalProperty",
        "sha256": "https://w3id.org/ro/terms/workflow-run#sha256",
    },
]
LICENSE_NAMES = {"CC-BY-4.0": "Creative Commons Attribution 4.0 International", "CC0-1.0": "Creative Commons Zero 1.0 Universal"}
NO_LICENSE = "ALL RIGHTS RESERVED BY THE AUTHORS"


def _term(iri: str, name: str) -> dict:
    return {"@id": iri, "@type": "DefinedTerm", "name": name, "termCode": iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _people(authors: list[dict]) -> tuple[list[dict], list[dict]]:
    people, orgs = [], {}
    for n, a in enumerate(authors, start=1):
        p = {"@id": f"https://orcid.org/{a['orcid']}" if a.get("orcid") else f"#person/{n}", "@type": "Person", "givenName": a["given_name"]}
        if a.get("family_name"):
            p["familyName"] = a["family_name"]
        p["name"] = " ".join(x for x in (a["given_name"], a.get("family_name", "")) if x)
        if a.get("orcid"):
            p["identifier"] = p["@id"]
        if a.get("affiliation"):
            org_id = "#organization/" + _slug(a["affiliation"])
            orgs.setdefault(org_id, {"@id": org_id, "@type": "Organization", "name": a["affiliation"]})
            p["affiliation"] = {"@id": org_id}
        people.append(p)
    return people, list(orgs.values())


def _single(entity: dict) -> dict:
    """RO-Crate 1.2 writes a one-element list as the element itself; JSON-LD reads both the same."""
    return {k: (v[0] if isinstance(v, list) and len(v) == 1 and k != "@context" else v) for k, v in entity.items()}


def metadata(snap: dict, *, base_iri: str, released: str, created: str, version: int | None, link: str, documents: dict[str, int]) -> dict:
    """ro-crate-metadata.json. `released` is the first publication date, empty if never published;
    `created` is the crate's creation date, which the profile uses as datePublished otherwise.
    `documents` maps the ISA-JSON and SBOL file names to their sizes."""
    isa_name, sbol_name, *rest = documents
    recipe_name = rest[0] if rest else None
    st = snap["study"]
    study_dir = f"studies/{st['id']}/"
    people, orgs = _people(st.get("authors", []))
    creators = [{"@id": p["@id"]} for p in people]
    license_url = LICENSES.get(st.get("license"))

    graph: list[dict] = [{"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "conformsTo": {"@id": RO_CRATE}, "about": {"@id": "./"}}]
    root = {
        "@id": "./",
        "@type": "Dataset",
        "additionalType": "Investigation",
        "conformsTo": {"@id": ISA_PROFILE},
        "identifier": link,
        "name": st["title"],
        "description": st["description"] or f"The study {st['title']}, exported from BOB.",
        "license": {"@id": license_url} if license_url else NO_LICENSE,
        "datePublished": released or created,
        "dateCreated": st["created_at"][:10],
        "hasPart": [{"@id": study_dir}, {"@id": isa_name}, {"@id": sbol_name}]
                   + ([{"@id": recipe_name}] if recipe_name else []),
    }
    if version:
        root["version"] = str(version)
    if creators:
        root["creator"] = creators
    graph.append(root)
    graph.append({"@id": ISA_PROFILE, "@type": ["CreativeWork", "Profile"], "name": "ISA RO-Crate profile", "version": "1.0.0-draft.1"})
    if license_url:
        graph.append({"@id": license_url, "@type": "CreativeWork", "name": LICENSE_NAMES[st["license"]], "identifier": st["license"],
                      "description": "The terms under which the data in this crate may be reused."})

    study = {
        "@id": study_dir,
        "@type": "Dataset",
        "additionalType": "Study",
        "identifier": st["id"],
        "name": st["title"],
        "description": st["description"] or st["title"],
        "dateCreated": st["created_at"][:10],
        "hasPart": [{"@id": f"assays/{a['id']}/"} for a in snap["assays"]],
    }
    if released:
        study["datePublished"] = released
    if creators:
        study["creator"] = creators
    graph.append(study)
    graph += people + orgs

    terms = {OBI + "0000070": _term(OBI + "0000070", "assay"), OBI + "0001058": _term(OBI + "0001058", "microplate reader")}
    protocols: dict[str, dict] = {}
    for a in snap["assays"]:
        raw = a["raw_file"]
        assay_dir = f"assays/{a['id']}/"
        file_id = f"{assay_dir}dataset/{raw['filename']}"
        protocol_id = f"#protocol/{a['mapping_key']}/v{a['mapping_version']}"
        protocols.setdefault(protocol_id, {
            "@id": protocol_id,
            "@type": ["LabProtocol", "HowTo"],
            "name": f"Plate-reader measurement read with BOB mapping {a['mapping_key']} v{a['mapping_version']}",
            "description": f"Kinetic plate-reader run exported by the instrument and read by the BOB mapping {a['mapping_name']}.",
            "intendedUse": {"@id": OBI + "0000070"},
            "labEquipment": {"@id": OBI + "0001058"},
            "version": str(a["mapping_version"]),
        })
        measured = sorted(set(a["layout"].values()))
        model = (a["run_metadata"] or {}).get("instrument_model", "")
        variables = []
        for sig in a["signals"]:
            v = {"@id": f"#variable/{a['id']}/{_slug(sig['name'])}", "@type": "PropertyValue", "name": sig["name"], "unitText": sig["unit"]}
            if sig.get("description"):
                v["description"] = sig["description"]
            if sig["kind"] in SIGNAL_TERMS:
                v["propertyID"] = SIGNAL_TERMS[sig["kind"]][0]
            variables.append(v)
        assay = {
            "@id": assay_dir,
            "@type": "Dataset",
            "additionalType": "Assay",
            "identifier": a["id"],
            "name": a["name"],
            "description": f"Plate-reader assay with {len(a['signals'])} signals across {len(a['positions'])} wells.",
            "about": [{"@id": f"#process/{a['id']}"}],
            "hasPart": [{"@id": file_id}],
            "measurementMethod": {"@id": OBI + "0001058"},
            "variableMeasured": [{"@id": v["@id"]} for v in variables],
        }
        if model:
            technique = f"#instrument/{_slug(model)}"
            terms[technique] = {"@id": technique, "@type": "DefinedTerm", "name": model}
            assay["measurementTechnique"] = {"@id": technique}
        if creators:
            assay["creator"] = creators
        params = []
        for sig in a["signals"]:
            for optic, value in sorted((sig.get("optics") or {}).items()):
                params.append({"@id": f"#parameter/{a['id']}/{_slug(sig['name'])}/{optic}", "@type": "PropertyValue", "additionalType": "ParameterValue",
                               "name": f"{sig['name']} {optic}", "value": str(value), "unitText": "nm"})
        plate = (a["run_metadata"] or {}).get("plate_type")
        if plate:
            params.append({"@id": f"#parameter/{a['id']}/plate-type", "@type": "PropertyValue", "additionalType": "ParameterValue", "name": "plate type", "value": str(plate)})
        process = {
            "@id": f"#process/{a['id']}",
            "@type": ["LabProcess", "Action"],
            "name": a["name"],
            "object": [{"@id": f"#sample/{sid}"} for sid in measured],
            "result": [{"@id": file_id}],
            "executesLabProtocol": {"@id": protocol_id},
            "parameterValue": [{"@id": x["@id"]} for x in params],
        }
        run_date = (a["run_metadata"] or {}).get("run_date")
        if run_date:
            process["endTime"] = str(run_date)
        graph += [assay, process, *variables, *params]
        graph.append({
            "@id": file_id,
            "@type": "File",
            "name": raw["filename"],
            "encodingFormat": raw["media_type"],
            "contentSize": str(raw["size"]),
            "sha256": raw["sha256"],
            "description": f"The instrument's export of assay {a['name']}, exactly as uploaded to BOB.",
            "disambiguatingDescription": "Raw Data File",
        })

    for s in snap["samples"]:
        props = [{"@id": f"#characteristic/{s['id']}/type", "@type": "PropertyValue", "additionalType": "CharacteristicValue", "name": "sample type", "value": s["sample_type"]}]
        for n, c in enumerate(s["components"], start=1):
            props.append({
                "@id": f"#characteristic/{s['id']}/{n}",
                "@type": "PropertyValue",
                "additionalType": "CharacteristicValue",
                "name": c["role"],
                "value": c["label"] or c["iri"],
                "valueReference": c["iri"],
            })
            if c.get("amount") is not None:
                props.append({
                    "@id": f"#characteristic/{s['id']}/{n}/amount",
                    "@type": "PropertyValue",
                    "additionalType": "CharacteristicValue",
                    "name": c["label"] or c["role"],
                    # JSON-LD reads a fractional number as xsd:double, which the ISA RO-Crate profile refuses.
                    "value": str(c["amount"]),
                    "valueReference": c["iri"],
                    **({"unitText": c["unit"]} if c.get("unit") else {}),
                })
        graph.append({"@id": f"#sample/{s['id']}", "@type": ["Sample", "Thing"], "name": s["name"], "additionalProperty": [{"@id": p["@id"]} for p in props]})
        graph += props

    graph += list(protocols.values()) + list(terms.values())
    graph.append({"@id": isa_name, "@type": "File", "name": "ISA-JSON description of the study", "encodingFormat": "application/json",
                  "contentSize": str(documents[isa_name]), "description": "The study, its samples, protocols, and assays as ISA-JSON."})
    graph.append({"@id": sbol_name, "@type": "File", "name": "SBOL 2.3 description of the study", "encodingFormat": "application/rdf+xml",
                  "contentSize": str(documents[sbol_name]), "description": "The study as SBOL 2.3: its experiment, data, and the designs its samples were built from."})
    if recipe_name:
        # a data entity per the RO-Crate 1.2 file model; it describes configuration, and asserts
        # nothing about a workflow having been executed
        graph.append({"@id": recipe_name, "@type": "File", "name": "Saved analysis configuration",
                      "encodingFormat": "application/json",
                      "contentSize": str(documents[recipe_name]),
                      "description": "Saved figure recipes of this study: the analysis configuration "
                                     "and the input state each was saved against. Not an executed "
                                     "analysis and not a verified biological result.",
                      "about": [{"@id": study_dir}] + [{"@id": f"assays/{a['id']}/"} for a in snap["assays"]]})
    return {"@context": CONTEXT, "@graph": [_single(e) for e in graph]}


def package(meta: dict, documents: dict[str, bytes], raw_files: dict[str, bytes]) -> bytes:
    """The crate as a zip: metadata first, then the study's documents and raw files by crate path."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ro-crate-metadata.json", json.dumps(meta, indent=2, ensure_ascii=False))
        for entity in meta["@graph"]:
            if entity.get("@type") == "Dataset" and entity["@id"] != "./":
                z.writestr(zipfile.ZipInfo(entity["@id"]), b"")
        for name, data in {**documents, **raw_files}.items():
            z.writestr(name, data)
    return buf.getvalue()
