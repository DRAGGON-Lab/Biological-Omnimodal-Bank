import sbol2

from bob.sbol_export import AssayRecord, ComponentRef, RawFile, SampleRecord, StudyRecord, export_study, read_document

STRAIN_A = "https://synbiohub.org/public/demo/strain_a/1"
STRAIN_B = "https://synbiohub.org/public/demo/strain_b/1"


def _study() -> StudyRecord:
    return StudyRecord(
        id="s1",
        title="Consortium study",
        description="two strains",
        assays=[AssayRecord("a1", "Plate 1", RawFile("https://bob.test/api/assays/a1/raw", "ab" * 32, 1234, "application/xlsx"), ["c1"])],
        samples=[
            SampleRecord("c1", "Consortium X", "A1,A2,A3", [ComponentRef(STRAIN_A, "strain", "A"), ComponentRef(STRAIN_B, "strain", "B")]),
            SampleRecord("m1", "Medium", "H1", []),
        ],
    )


def test_round_trip_keeps_experiment_structure():
    doc = read_document(export_study(_study(), "https://bob.test"))
    (exp,) = doc.experiments
    (data,) = doc.experimentalData
    assert exp.name == "Consortium study"
    assert list(exp.experimentalData) == [data.identity]
    (att,) = doc.attachments
    assert list(data.attachments) == [att.identity]
    # SBOL 2.3 section 7.13 defines the optional hash as SHA-1, so the raw file's SHA-256 travels
    # under a property that names its algorithm instead. The claim is unchanged: the digest, the
    # source URL and the size all survive the round trip.
    assert att.source == "https://bob.test/api/assays/a1/raw" and int(att.size) == 1234
    # a re-read document exposes annotations through `properties`, not as attributes
    def annotation(name):
        return [str(v) for v in att.properties.get(f"https://bob.test/sbol/{name}", [])]

    assert annotation("rawFileSha256") == ["ab" * 32]
    assert annotation("rawFileHashAlgorithm") == ["SHA-256"]
    assert att.properties.get("http://sbols.org/v2#hash", []) == []


def test_consortium_is_a_collection_of_one_implementation_per_strain():
    doc = read_document(export_study(_study(), "https://bob.test"))
    consortium = next(c for c in doc.collections if c.name == "Consortium X")
    built = sorted(doc.implementations[m].built for m in consortium.members)
    assert built == [STRAIN_A, STRAIN_B]
    (data,) = doc.experimentalData
    assert list(data.wasDerivedFrom) == [consortium.identity]


def test_identities_live_under_the_bob_namespace():
    text = export_study(_study(), "https://bob.test")
    assert "https://bob.test/sbol/study_s1" in text
    assert sbol2.Config.getOption(sbol2.ConfigOptions.VALIDATE.value) is False
