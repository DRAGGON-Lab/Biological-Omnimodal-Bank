"""Container self-check: SBOL writes offline and the app builds and reports healthy."""

import sys

from bob.sbol_export import AssayRecord, ComponentRef, RawFile, SampleRecord, StudyRecord, export_study, read_document


def main() -> int:
    study = StudyRecord(
        id="smoke",
        title="Smoke",
        description="",
        assays=[AssayRecord("a1", "Plate", RawFile("http://localhost/raw/1", "0" * 64, 1, "application/vnd.ms-excel"), ["s1"])],
        samples=[SampleRecord("s1", "Consortium", "A1", [ComponentRef("https://synbiohub.org/public/igem/BBa_K000001/1", "strain")])],
    )
    doc = read_document(export_study(study, "http://localhost:8000"))
    assert len(doc.experiments) == 1 and len(doc.implementations) == 1, "SBOL round trip lost objects"

    from bob.main import create_app

    app = create_app()
    health = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/health")
    assert health()["status"] == "ok"
    print("smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
