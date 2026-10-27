"""Versions of public studies: every saved change to a public study becomes a new version that
readers can always return to, and every version is served from its snapshot, never from live rows."""

import json
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import recipes
from bob.models import Artifact, Assay, FrozenAssay, InstrumentMapping, Study, StudyVersion, User

SNAPSHOT_FORMAT = "bob-study-snapshot/2"   # /2 adds the frozen recipe inventory


@dataclass
class SignalData:
    name: str
    label: str
    kind: str
    unit: str
    optics: dict
    times: list
    series: dict[str, list]


@dataclass
class SampleComponentRef:
    role: str
    iri: str
    label: str = ""
    amount: float | None = None
    unit: str | None = None


@dataclass
class SampleRef:
    id: str
    name: str
    sample_type: str
    components: list["SampleComponentRef"] = field(default_factory=list)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _well_key(pos: str) -> tuple[str, int]:
    return pos[0], int(pos[1:]) if pos[1:].isdigit() else 0


def _mapping_name(db: Session, a: Assay) -> str:
    name = db.scalar(select(InstrumentMapping.name).where(InstrumentMapping.id == a.mapping_id)) if a.mapping_id else None
    return name or a.mapping_key


def _source_facts(assay_dict: dict, samples: list[dict]) -> dict:
    """What a resolved source actually holds, for the checks `recipes.assess` records."""
    from bob import services

    return {
        "layout_fingerprint": recipes.source_fingerprint(services.snapshot_layout(assay_dict, samples)),
        "raw_file_sha256": (assay_dict.get("raw_file") or {}).get("sha256"),
        # by name, so a plate with two channels of one kind is compared against the selected one
        "channel_units": {s["name"]: s["unit"] for s in assay_dict.get("signals") or ()},
    }


def _recipe_status(db: Session, study: Study, rec, entry: dict) -> dict:
    """Assess a recipe against the source IT NAMES, which may be an earlier published version than
    the one now being written. Frozen into the snapshot, so a later download never reassesses it
    against whatever the checking code has since become."""
    src = rec.source or {}
    assay_id = src.get("assay_id")
    number = src.get("snapshot_version")
    scope = (f"recorded source: published version {number} of this study, checked at capture against "
             f"that version and this implementation" if number is not None else
             "recorded source: the live study state captured in this version, checked at capture "
             "against that state and this implementation")
    if not assay_id:
        return recipes.assess(entry, scope=scope, source=None,
                              problem="this recipe records no source assay")

    if number is not None:
        v = db.scalar(select(StudyVersion).where(StudyVersion.study_id == study.id,
                                                 StudyVersion.number == number))
        if v is None:
            return recipes.assess(entry, scope=scope, source=None,
                                  problem=f"version {number} of this study is not available")
        a = next((x for x in v.snapshot.get("assays") or () if x["id"] == assay_id), None)
        if a is None:
            return recipes.assess(entry, scope=scope, source=None,
                                  problem=f"the recorded source assay is not part of version {number}")
        return recipes.assess(entry, scope=scope,
                              source=_source_facts(a, v.snapshot.get("samples") or []))

    assay = db.get(Assay, assay_id)
    if assay is None or assay.study_id != study.id:
        return recipes.assess(entry, scope=scope, source=None,
                              problem="the recorded source assay is no longer in this study")
    live = {
        "layout": {w.position: w.sample_id for w in assay.wells if w.sample_id},
        "raw_file": {"sha256": getattr(getattr(assay, "artifact", None), "sha256", None)},
        "signals": [{"name": s.name, "kind": s.kind, "unit": s.unit} for s in assay.signals],
    }
    samples = [{"id": s.id, "name": s.name, "sample_type": s.sample_type,
                "components": [{"role": c.role, "iri": c.iri, "label": c.label,
                                "amount": c.amount, "unit": c.unit} for c in s.components]}
               for s in study.samples]
    return recipes.assess(entry, scope=scope, source=_source_facts(live, samples))


def _recipe_entries(db: Session, study: Study) -> list[dict]:
    out = []
    for rec in sorted(study.recipes, key=lambda r: r.id):
        entry = recipes.stored_entry(rec, {})
        entry["source_status"] = _recipe_status(db, study, rec, entry)
        out.append(entry)
    return out


def snapshot(db: Session, study: Study) -> dict:
    samples = sorted(study.samples, key=lambda s: (s.sample_type != "sample", s.name.lower(), s.id))
    assays = sorted(study.assays, key=lambda a: (a.created_at, a.id))
    return {
        "format": SNAPSHOT_FORMAT,
        "study": {
            "id": study.id,
            "title": study.title,
            "description": study.description,
            "license": study.license,
            "authors": study.authors or [],
            "created_at": _iso(study.created_at),
        },
        "samples": [
            {
                "id": s.id,
                "name": s.name,
                "sample_type": s.sample_type,
                "description": s.description,
                "components": [
                    {"role": c.role, "iri": c.iri, "label": c.label, "amount": c.amount, "unit": c.unit, "sbol_version": c.sbol_version, "sbol_class": c.sbol_class}
                    for c in s.components
                ],
            }
            for s in samples
        ],
        "assays": [
            {
                "id": a.id,
                "name": a.name,
                "modality": a.modality,
                "mapping_key": a.mapping_key,
                "mapping_version": a.mapping_version,
                "mapping_name": _mapping_name(db, a),
                "run_metadata": a.run_metadata or {},
                "warnings": a.warnings or [],
                "created_at": _iso(a.created_at),
                "raw_file": {
                    "artifact_id": a.artifact.id,
                    "filename": a.artifact.filename,
                    "sha256": a.artifact.sha256,
                    "size": a.artifact.size,
                    "media_type": a.artifact.media_type,
                },
                "signals": [{"name": s.name, "label": s.label, "kind": s.kind, "unit": s.unit, "description": s.description, "color": s.color,
                             "optics": s.optics, "n_times": len(s.times)} for s in a.signals],
                "positions": sorted((w.position for w in a.wells), key=_well_key),
                "layout": {w.position: w.sample_id for w in sorted(a.wells, key=lambda w: _well_key(w.position)) if w.sample_id},
            }
            for a in assays
        ],
        # frozen with the rest of the content: a published version keeps the analysis configuration
        # it had, and never acquires today's
        "recipes": _recipe_entries(db, study),
    }


def live_signals(assay: Assay) -> list[SignalData]:
    return [SignalData(s.name, s.label, s.kind, s.unit, s.optics or {}, list(s.times), {r.position: list(r.values) for r in s.series}) for s in assay.signals]


def frozen_signals(frozen: FrozenAssay) -> list[SignalData]:
    return [SignalData(s["name"], s["label"], s["kind"], s["unit"], s.get("optics") or {}, s["times"], s["series"]) for s in frozen.signals]


def _freeze(db: Session, assay: Assay) -> None:
    if db.get(FrozenAssay, assay.id) is not None:
        return
    signals = [
        {"name": s.name, "label": s.label, "kind": s.kind, "unit": s.unit, "optics": s.optics, "times": s.times, "series": s.series}
        for s in live_signals(assay)
    ]
    db.add(FrozenAssay(assay_id=assay.id, study_id=assay.study_id, artifact_id=assay.artifact_id, signals=signals))


def latest(db: Session, study: Study) -> StudyVersion | None:
    return db.scalar(select(StudyVersion).where(StudyVersion.study_id == study.id).order_by(StudyVersion.number.desc()))


def _same(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def record(db: Session, study: Study, user: User | None, note: str) -> StudyVersion | None:
    """Records the study's current state as a new version if it is public and something changed."""
    if study.visibility != "public":
        return None
    db.flush()
    # A sample delete clears well assignments in the database (ON DELETE SET NULL), not in loaded objects.
    db.expire_all()
    snap = snapshot(db, study)
    last = latest(db, study)
    if last is not None and _same(last.snapshot, snap):
        return None
    for assay in study.assays:
        _freeze(db, assay)
    version = StudyVersion(study_id=study.id, number=(last.number if last else 0) + 1, note=note[:200], snapshot=snap, created_by=user.id if user else None)
    db.add(version)
    db.flush()
    return version


def ensure_first(db: Session, study: Study) -> None:
    """Studies made public before versions existed get their first version when first needed."""
    if study.visibility == "public" and latest(db, study) is None:
        record(db, study, None, "Public before BOB kept versions")
        db.commit()


def get(db: Session, study: Study, number: int) -> StudyVersion:
    ensure_first(db, study)
    v = db.scalar(select(StudyVersion).where(StudyVersion.study_id == study.id, StudyVersion.number == number))
    if v is None:
        raise HTTPException(404, f"This study has no version {number}")
    return v


def snapshot_assay(version: StudyVersion, assay_id: str) -> dict:
    for a in version.snapshot["assays"]:
        if a["id"] == assay_id:
            return a
    raise HTTPException(404, f"Assay not found in version {version.number}")


def frozen(db: Session, assay_id: str) -> FrozenAssay:
    row = db.get(FrozenAssay, assay_id)
    if row is None:
        raise HTTPException(404, "Assay not found")
    return row


def artifact(db: Session, artifact_id: str) -> Artifact:
    row = db.get(Artifact, artifact_id)
    if row is None:
        raise HTTPException(410, "The raw file is missing from storage")
    return row
