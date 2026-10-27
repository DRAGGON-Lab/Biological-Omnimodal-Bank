"""SBOL 2.3 serialization of a Study.

BOB owns only the experiment layer: one Experiment per Study, one ExperimentalData per Assay
(attaching the raw file), and one Collection per sample grouping one Implementation per strain.
Strain designs stay where they live; `built` carries their IRI verbatim, which is valid in
SBOL 2.3 because those designs are SBOL 2 ComponentDefinitions or ModuleDefinitions.
"""

import re
from dataclasses import dataclass, field

import sbol2
from rdflib import URIRef

DCTERMS = "http://purl.org/dc/terms/"
SCHEMA = "http://schema.org/"


@dataclass
class RawFile:
    url: str
    sha256: str
    size: int
    media_type: str


@dataclass
class AssayRecord:
    id: str
    name: str
    raw_file: RawFile | None
    sample_ids: list[str] = field(default_factory=list)


@dataclass
class ComponentRef:
    iri: str
    role: str
    label: str = ""
    amount: float | None = None
    unit: str | None = None


class PartValue(sbol2.Identified):
    """A sample's part as a schema.org PropertyValue: SBOL's own Measure needs a unit IRI, and a
    design's concentrations come without a unit."""

    def __init__(self, uri=URIRef("example"), version=sbol2.VERSION_STRING, type_uri=SCHEMA + "PropertyValue"):
        super().__init__(type_uri, uri, version)
        self.role = sbol2.TextProperty(self, SCHEMA + "name", "0", "1", None)
        self.reference = sbol2.URIProperty(self, SCHEMA + "valueReference", "0", "1", None)
        self.amount = sbol2.FloatProperty(self, SCHEMA + "value", "0", "1", None)
        self.unit = sbol2.TextProperty(self, SCHEMA + "unitText", "0", "1", None)


sbol2.Config.register_extension_class(PartValue, SCHEMA + "PropertyValue")


@dataclass
class SampleRecord:
    id: str
    name: str
    position: str
    components: list[ComponentRef] = field(default_factory=list)


@dataclass
class StudyRecord:
    id: str
    title: str
    description: str
    assays: list[AssayRecord]
    samples: list[SampleRecord]
    # A published study's version number, which SBOL carries in every identity.
    version: str = "1"
    creators: list[str] = field(default_factory=list)
    license_url: str = ""
    # the recipe manifest as a JSON literal; SBOL 2.3 section 7.16 permits application-specific
    # annotations, and this is provenance about configuration, not a genetic design
    recipe_manifest: str = ""


def _display_id(prefix: str, raw: str) -> str:
    """SBOL displayIds must match [A-Za-z_][A-Za-z0-9_]*."""
    return f"{prefix}_{re.sub(r'[^A-Za-z0-9_]', '_', raw)}"


def _configure(base_iri: str) -> None:
    # Validation defaults to posting the document to an online service; BOB must work offline.
    sbol2.Config.setOption(sbol2.ConfigOptions.VALIDATE.value, False)
    sbol2.Config.setOption(sbol2.ConfigOptions.VALIDATE_ONLINE.value, False)
    sbol2.Config.setOption(sbol2.ConfigOptions.SBOL_TYPED_URIS.value, False)
    sbol2.setHomespace(f"{base_iri}/sbol")


def build_document(study: StudyRecord, base_iri: str) -> sbol2.Document:
    _configure(base_iri)
    doc = sbol2.Document()
    doc.addNamespace(f"{base_iri}/sbol/", "bob")
    doc.addNamespace(DCTERMS, "dcterms")
    doc.addNamespace(SCHEMA, "sdo")

    collections: dict[str, sbol2.Collection] = {}
    for sample in study.samples:
        coll = sbol2.Collection(_display_id("sample", sample.id), study.version)
        coll.name = sample.name or sample.position
        coll.description = f"Well {sample.position}" if sample.position else ""
        doc.addCollection(coll)
        # A sample design (an SBOL ModuleDefinition of strain, medium, and supplements) is built like a
        # strain, and holds the strain, so a sample that has one is built from it alone.
        built = [c for c in sample.components if c.role == "design"] or [c for c in sample.components if c.role == "strain"]
        members = []
        for i, comp in enumerate(built, start=1):
            impl = sbol2.Implementation(_display_id("impl", f"{sample.id}_{i}"), study.version)
            impl.name = comp.label or comp.iri
            impl.built = comp.iri
            doc.add(impl)
            members.append(impl.identity)
        coll.members = members
        others = [c for c in sample.components if c not in built]
        if others:
            coll.parts = sbol2.OwnedObject(coll, SCHEMA + "additionalProperty", PartValue, "0", "*", None)
            for i, comp in enumerate(others, start=1):
                part = PartValue(f"part_{i}", study.version)
                part.role = comp.role
                part.reference = comp.iri
                part.name = comp.label or None
                if comp.amount is not None:
                    part.amount = comp.amount
                if comp.unit:
                    part.unit = comp.unit
                coll.parts.add(part)
        collections[sample.id] = coll

    data_ids = []
    for assay in study.assays:
        ed = sbol2.ExperimentalData(_display_id("assay", assay.id), study.version)
        ed.name = assay.name
        if assay.raw_file:
            att = sbol2.Attachment(_display_id("raw", assay.id), version=study.version)
            att.source = assay.raw_file.url
            att.format = assay.raw_file.media_type
            att.size = assay.raw_file.size
            # SBOL 2.3 section 7.13 defines the optional hash as a SHA-1 digest, so a SHA-256 is
            # not written there; it travels under a property that names the algorithm instead.
            att.rawFileSha256 = sbol2.TextProperty(att, f"{base_iri}/sbol/rawFileSha256", "0", "1", [])
            att.rawFileSha256 = assay.raw_file.sha256
            att.rawFileHashAlgorithm = sbol2.TextProperty(att, f"{base_iri}/sbol/rawFileHashAlgorithm", "0", "1", [])
            att.rawFileHashAlgorithm = "SHA-256"
            doc.add(att)
            ed.attachments = [att.identity]
        ed.wasDerivedFrom = [collections[s].identity for s in assay.sample_ids if s in collections]
        doc.add(ed)
        data_ids.append(ed.identity)

    exp = sbol2.Experiment(_display_id("study", study.id), study.version)
    exp.name = study.title
    exp.description = study.description or ""
    exp.experimentalData = data_ids
    # SBOL annotations; SynBioHub shows dcterms:creator as the creator of an object.
    if study.creators:
        exp.creators = sbol2.TextProperty(exp, DCTERMS + "creator", "0", "*", [])
        exp.creators = study.creators
    if study.license_url:
        exp.license = sbol2.URIProperty(exp, DCTERMS + "license", "0", "1", [])
        exp.license = study.license_url
    if study.recipe_manifest:
        exp.recipeManifest = sbol2.TextProperty(exp, f"{base_iri}/sbol/recipeManifest", "0", "1", [])
        exp.recipeManifest = study.recipe_manifest
    doc.add(exp)
    return doc


def export_study(study: StudyRecord, base_iri: str) -> str:
    return build_document(study, base_iri).writeString()


def read_document(text: str) -> sbol2.Document:
    doc = sbol2.Document()
    doc.readString(text)
    return doc
