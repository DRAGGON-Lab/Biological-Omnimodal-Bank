"""Imports an Excel-to-SBOL Assay workbook with its plate files. `plan` works out everything the
import would do and writes nothing, which is what the check-only call returns; `apply` writes a
plan that has no problems."""

import hashlib
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import designs, services, workbook
from bob.config import Settings
from bob.mappings.engine import ParsedRun
from bob.models import Assay, InstrumentMapping, Sample, Study, StudyEvent, User
from bob.text import clean_line


@dataclass
class PlannedAssay:
    source: workbook.WorkbookAssay
    filename: str
    data: bytes
    mapping: InstrumentMapping
    run: ParsedRun
    signal_names: list[tuple[str, str, str]] | None
    action: str
    previous: list[Assay]


@dataclass
class PlannedSample:
    name: str
    iri: str
    action: str
    parts: list[dict]
    error: str = ""


@dataclass
class Plan:
    filename: str
    sha256: str
    book: workbook.AssayWorkbook | None = None
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pairing: list[dict] = field(default_factory=list)
    assays: list[PlannedAssay] = field(default_factory=list)
    samples: list[PlannedSample] = field(default_factory=list)


def suggest_assay(filename: str, assay_ids: list[str]) -> str | None:
    """The assay whose ID the file name contains; the longest wins, so plate_10 beats plate_1."""
    hits = sorted((a for a in assay_ids if a.lower() in filename.lower()), key=len, reverse=True)
    if not hits or (len(hits) > 1 and len(hits[0]) == len(hits[1])):
        return None
    return hits[0]


def _pair(plan: Plan, book: workbook.AssayWorkbook, plates: list[tuple[str, bytes]], chosen: dict[str, str] | None) -> list[tuple]:
    by_id = {a.id: a for a in book.assays}
    open_assays = [a for a in book.assays if a.wells] or book.assays
    names = [n for n, _ in plates]
    doubled = sorted({n for n in names if names.count(n) > 1})
    if doubled:
        plan.problems.append(f"Two plate files are named {', '.join(doubled)}; rename one")
    if chosen:
        plan.pairing = [{"plate": n, "assay_id": chosen.get(n), "source": "chosen" if n in chosen else None} for n in names]
        unknown = sorted(set(chosen.values()) - set(by_id))
        if unknown:
            plan.problems.append(f"No assay with ID {', '.join(unknown)} in {plan.filename}")
        missing = sorted(set(chosen) - set(names))
        if missing:
            plan.problems.append(f"No uploaded plate file named {', '.join(missing)}")
        unpaired = [n for n in names if n not in chosen]
        if unpaired:
            plan.problems.append(f"Say which assay {', '.join(unpaired)} belongs to")
        values = list(chosen.values())
        twice = sorted({v for v in values if values.count(v) > 1})
        if twice:
            plan.problems.append(f"More than one plate file is paired with {', '.join(twice)}")
        return [(by_id[chosen[n]], n, blob) for n, blob in plates if chosen.get(n) in by_id]
    if len(plates) == 1 and len(open_assays) == 1:
        plan.pairing = [{"plate": names[0], "assay_id": open_assays[0].id, "source": "only one"}]
        return [(open_assays[0], names[0], plates[0][1])]
    ids = [a.id for a in open_assays]
    plan.pairing = [{"plate": n, "assay_id": (s := suggest_assay(n, ids)), "source": "file name" if s else None} for n in names]
    plan.problems.append(f"{plan.filename} lists {len(open_assays)} assays and {len(plates)} plate files came with it; say which file belongs to which assay")
    return []


def _seen_workbooks(db: Session, study: Study) -> set[str]:
    details = db.scalars(select(StudyEvent.detail).where(StudyEvent.study_id == study.id, StudyEvent.kind == "workbook"))
    return {d.rsplit("(sha256 ", 1)[1].rstrip(")") for d in details if "(sha256 " in d}


def _action(a: workbook.WorkbookAssay, study: Study, seen: set[str], book_sha: str, plate_sha: str, mapping: InstrumentMapping) -> tuple[str, list[Assay]]:
    previous = [x for x in study.assays if (x.run_metadata or {}).get("workbook_assay_id") == a.id]
    if not previous:
        return "new", []
    (only, *more) = previous
    same_book = book_sha in seen or (only.run_metadata or {}).get("workbook_sha256") == book_sha
    if not more and same_book and only.artifact.sha256 == plate_sha and only.mapping_key == mapping.key:
        return "unchanged", previous
    return "replace", previous


def _signal_names(plan: Plan, book: workbook.AssayWorkbook, filename: str, run: ParsedRun) -> list[tuple[str, str, str]] | None:
    if not book.signals:
        return None
    if len(book.signals) != len(run.signals):
        named = ", ".join(s.name for s in book.signals)
        read = ", ".join(s.label for s in run.signals)
        plan.problems.append(f"{filename}: the workbook's signal sheet names {len(book.signals)} signals ({named}) "
                             f"but the file holds {len(run.signals)} channels ({read})")
        return None
    return [(s.name, s.description, s.color) for s in book.signals]


def _plan_samples(plan: Plan, settings: Settings, study: Study, book: workbook.AssayWorkbook, tokens: dict[str, str | None]) -> None:
    used = sorted({d for pa in plan.assays if pa.action != "unchanged" for d in pa.source.wells.values()})
    existing = {s.name: s for s in study.samples}
    links: dict[str, str | None] = {}
    to_resolve: dict[str, str] = {}
    for name in used:
        iri = book.designs.get(name, "")
        s = existing.get(name)
        link = links[name] = next((c.iri for c in s.components if c.role == "design"), None) if s else None
        if s is not None and (link is None or not iri or (link == iri and any(c.role != "design" for c in s.components))):
            plan.samples.append(PlannedSample(name, iri, "keep", []))
            continue
        if not iri:
            plan.warnings.append(f"{name} has no SynBioHub IRI in the workbook's design list, so its sample has no parts")
            plan.samples.append(PlannedSample(name, "", "new", []))
            continue
        to_resolve[name] = iri
        plan.samples.append(PlannedSample(name, iri, "new" if s is None else "update", []))
    found = designs.resolve_designs(to_resolve, settings.synbiohub_instances, tokens)
    for ps in plan.samples:
        if ps.name not in found:
            continue
        got = found[ps.name]
        if got.unsupported:
            # a composition BOB cannot record faithfully is refused, not downgraded to a link
            ps.error = got.error
            plan.problems.append(f"{ps.name}: {got.error}")
            continue
        if got.error:
            ps.error = got.error
            ps.parts = [designs.parts(designs.SampleDesign(ps.name, ps.iri))[0]]
            if ps.action == "update" and links[ps.name] == ps.iri:
                ps.action = "keep"
            plan.warnings.append(f"{ps.name}: its parts could not be read from SynBioHub ({got.error}); the sample keeps only its design link")
        else:
            ps.parts = got.parts


def plan(db: Session, settings: Settings, study: Study, data: bytes, filename: str, plates: list[tuple[str, bytes]],
         chosen: dict[str, str] | None, mapping_key: str, tokens: dict[str, str | None]) -> Plan:
    out = Plan(filename, hashlib.sha256(data).hexdigest())
    try:
        book = workbook.read(data)
    except workbook.WorkbookError as exc:
        out.problems.append(f"{filename}: {exc}")
        return out
    out.book = book
    seen = _seen_workbooks(db, study)
    workspace_id = study.investigation.workspace_id
    for a, name, blob in _pair(out, book, plates, chosen):
        try:
            mapping, run = services.parse_plate(db, workspace_id, mapping_key, blob)
        except HTTPException as exc:
            out.problems.append(f"{name}: {exc.detail}")
            continue
        outside = sorted(set(a.wells) - set(run.positions), key=lambda pos: (pos[0], int(pos[1:])))
        if outside:
            out.warnings.append(f"{a.name}: the workbook names wells the plate file has no data for ({', '.join(outside[:8])}{'…' if len(outside) > 8 else ''})")
        action, previous = _action(a, study, seen, out.sha256, hashlib.sha256(blob).hexdigest(), mapping)
        out.assays.append(PlannedAssay(a, name, blob, mapping, run, _signal_names(out, book, name, run), action, previous))
    paired = {pa.source.id for pa in out.assays}
    waiting = [a.id for a in book.assays if a.wells and a.id not in paired]
    if waiting and not out.problems:
        out.warnings.append(f"No plate file came for {', '.join(waiting)}; import those assays when their files are ready")
    if not out.problems:
        _plan_samples(out, settings, study, book, tokens)
    return out


def apply(db: Session, settings: Settings, study: Study, p: Plan, user: User | None) -> dict:
    samples = {s.name: s for s in study.samples}
    created = updated = 0
    for ps in p.samples:
        if ps.action == "keep":
            continue
        s = samples.get(ps.name)
        if s is None:
            s = Sample(study_id=study.id, name=clean_line(ps.name)[:200])
            db.add(s)
            samples[ps.name] = s
            created += 1
        else:
            updated += 1
        services.set_sample_components(s, ps.parts)
    db.flush()

    out = []
    for pa in p.assays:
        a = pa.source
        if pa.action == "unchanged":
            prev = pa.previous[0]
            out.append({"id": prev.id, "name": prev.name, "workbook_assay_id": a.id, "action": "unchanged",
                        "wells_assigned": sum(1 for w in prev.wells if w.sample_id)})
            continue
        for old in pa.previous:
            db.delete(old)
        assay = services.store_assay(db, settings, study, a.name, pa.mapping, pa.run, pa.filename, pa.data, user, pa.signal_names)
        assay.run_metadata = {**(assay.run_metadata or {}), "workbook_assay_id": a.id, "workbook_sha256": p.sha256,
                              **({"temperature_c": a.temperature} if a.temperature else {}), **({"description": a.description} if a.description else {})}
        db.flush()
        wells = {w.position: w for w in assay.wells}
        for pos, design in a.wells.items():
            if pos in wells:
                wells[pos].sample_id = samples[design].id
        out.append({"id": assay.id, "name": assay.name, "workbook_assay_id": a.id, "action": pa.action,
                    "wells_assigned": sum(1 for pos in a.wells if pos in wells)})
    changed = bool(created or updated or any(x["action"] != "unchanged" for x in out))
    return {"assays": out, "samples_created": created, "samples_updated": updated, "warnings": p.warnings, "changed": changed}


def describe(p: Plan) -> dict:
    """What the check-only call shows: everything the import would do, nothing written."""
    book = p.book
    return {
        "ok": not p.problems,
        "problems": p.problems,
        "warnings": p.warnings,
        "workbook": {
            "filename": p.filename,
            "sha256": p.sha256,
            "assays": [{"id": a.id, "name": a.name, "wells": len(a.wells)} for a in book.assays] if book else [],
            "signals": [{"name": s.name, "description": s.description, "color": s.color} for s in book.signals] if book else [],
        },
        "pairing": p.pairing,
        "assays": [
            {
                "workbook_assay_id": pa.source.id,
                "name": pa.source.name,
                "plate": pa.filename,
                "action": pa.action,
                "wells": len(pa.source.wells),
                "channels": [
                    {"read": i, "label": s.label, "kind": s.kind, "unit": s.unit,
                     **({"name": n[0], "description": n[1], "color": n[2]} if pa.signal_names else {"name": s.name, "description": "", "color": ""})}
                    for i, (s, n) in enumerate(zip(pa.run.signals, pa.signal_names or [None] * len(pa.run.signals)), start=1)
                ],
            }
            for pa in p.assays
        ],
        "samples": [{"name": s.name, "iri": s.iri, "action": s.action, "resolved": bool(s.parts) and not s.error,
                     "error": s.error, "parts": s.parts} for s in p.samples],
    }
