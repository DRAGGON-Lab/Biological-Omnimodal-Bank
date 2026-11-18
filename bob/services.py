import hashlib
import os
import re
import tempfile
from pathlib import Path

import numpy as _np
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bob import analysis
from bob.text import clean_line
from bob.config import Settings
from bob.mappings import MappingSpec, builtin_mappings, parse_file
from bob.mappings.engine import MappingError, ParsedRun, parse_file_isolated
from bob.models import (
    LICENSES,
    Artifact,
    Assay,
    FrozenAssay,
    InstrumentMapping,
    Membership,
    Sample,
    SampleComponent,
    Series,
    Signal,
    Study,
    User,
    Well,
    Workspace,
)
from bob.sbol_export import AssayRecord, ComponentRef, RawFile, SampleRecord, StudyRecord
from bob.terms import XLSX_FORMAT
from bob.versions import SampleComponentRef, SampleRef, SignalData
from bob.security import hash_password

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# SBOL Attachment.format must be an IRI; EDAM names the file format.
FORMAT_IRIS = {XLSX_MEDIA_TYPE: XLSX_FORMAT}


def slugify(text: str, fallback: str = "workspace") -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:100] or fallback


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while db.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_workspace(db: Session, owner: User, name: str) -> Workspace:
    ws = Workspace(name=name.strip(), slug=unique_slug(db, name))
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=owner.id, role="owner"))
    return ws


def create_user(db: Session, email: str, name: str, password: str) -> tuple[User, Workspace]:
    email = email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, name=name.strip(), password_hash=hash_password(password))
    db.add(user)
    db.flush()
    ws = create_workspace(db, user, f"{user.name}'s Workspace")
    return user, ws


def owner_count(db: Session, workspace_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id == workspace_id, Membership.role == "owner"))


def sync_builtin_mappings(db: Session) -> None:
    """A changed built-in spec becomes a new version, so assays keep the version that read them."""
    for spec in builtin_mappings():
        latest = db.scalar(
            select(InstrumentMapping)
            .where(InstrumentMapping.workspace_id.is_(None), InstrumentMapping.key == spec.key)
            .order_by(InstrumentMapping.version.desc())
        )
        if latest is None or latest.spec != spec.to_json():
            db.add(_mapping_row(spec, workspace_id=None, builtin=True, version=(latest.version + 1) if latest else 1, user_id=None))
    db.commit()


def _mapping_row(spec: MappingSpec, workspace_id, builtin, version, user_id) -> InstrumentMapping:
    return InstrumentMapping(
        workspace_id=workspace_id,
        key=spec.key,
        version=version,
        name=spec.name,
        emoji=spec.emoji,
        modality=spec.modality,
        description=spec.description,
        spec=spec.to_json(),
        builtin=builtin,
        created_by=user_id,
    )


def save_mapping(db: Session, workspace_id: str, spec: MappingSpec, user: User) -> InstrumentMapping:
    latest = db.scalar(
        select(func.max(InstrumentMapping.version)).where(InstrumentMapping.workspace_id == workspace_id, InstrumentMapping.key == spec.key)
    )
    row = _mapping_row(spec, workspace_id, False, (latest or 0) + 1, user.id)
    db.add(row)
    return row


def resolve_mapping(db: Session, workspace_id: str, key: str) -> InstrumentMapping:
    """A workspace's own mapping wins over a built-in one with the same key; latest version wins."""
    for scope in (InstrumentMapping.workspace_id == workspace_id, InstrumentMapping.workspace_id.is_(None)):
        row = db.scalar(select(InstrumentMapping).where(scope, InstrumentMapping.key == key).order_by(InstrumentMapping.version.desc()))
        if row:
            return row
    raise HTTPException(422, f"Unknown mapping {key!r}")


def safe_filename(filename: str) -> str:
    name = clean_line(Path(filename.replace("\\", "/")).name)[:255]
    return name if name.strip(". ") else "upload.xlsx"


def store_artifact(db: Session, settings: Settings, workspace_id: str, filename: str, data: bytes, user: User | None) -> Artifact:
    digest = hashlib.sha256(data).hexdigest()
    key = f"{digest[:2]}/{digest}"
    path: Path = settings.artifact_dir / key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # A digest has one final path, but concurrent uploads need distinct temporary files.
        # Replacing the destination is safe even if another request won the race because both
        # requests computed the same digest over identical bytes.
        handle, tmp_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".part", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    artifact = Artifact(
        workspace_id=workspace_id,
        filename=safe_filename(filename),
        sha256=digest,
        size=len(data),
        media_type=XLSX_MEDIA_TYPE,
        storage_key=key,
        uploaded_by=user.id if user else None,
    )
    db.add(artifact)
    return artifact


def purge_unused_artifacts(db: Session, settings: Settings, extra_keys: set[str] | None = None) -> None:
    """Drop artifact rows no assay or published version uses, then delete files no remaining row points at.

    Files are content-addressed and can be shared by several rows, so a file goes only when its
    last row does. `extra_keys` covers rows already removed by a cascade, such as a workspace delete.
    """
    used = select(Assay.artifact_id).where(Assay.artifact_id.is_not(None))
    published = select(FrozenAssay.artifact_id)
    keys = set(extra_keys or ())
    for art in db.scalars(select(Artifact).where(Artifact.id.not_in(used), Artifact.id.not_in(published))).all():
        keys.add(art.storage_key)
        db.delete(art)
    db.commit()
    for key in keys:
        if not db.scalar(select(Artifact.id).where(Artifact.storage_key == key)):
            (settings.artifact_dir / key).unlink(missing_ok=True)


def parse_plate(db: Session, workspace_id: str, mapping_key: str, data: bytes) -> tuple[InstrumentMapping, ParsedRun]:
    if not data:
        raise HTTPException(422, "The uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Files over 50 MB are not accepted yet")
    mapping = resolve_mapping(db, workspace_id, mapping_key)
    spec = MappingSpec.model_validate(mapping.spec)
    try:
        if mapping.builtin:
            return mapping, parse_file(data, spec)
        return mapping, parse_file_isolated(data, spec, float(os.environ.get("BOB_MAPPING_TIMEOUT_S", "30")))
    except MappingError as exc:
        raise HTTPException(422, str(exc)) from exc


def preview_mapping(spec: MappingSpec, data: bytes, filename: str, label_has_optics: bool = True,
                    channels_named: bool = True) -> dict:
    """Parse one file with a proposed mapping and report what it found. Nothing is stored.

    This is the same parser the import uses, so a preview that reads cleanly is evidence about the
    mapping rather than about a second implementation.
    """
    if not data:
        raise HTTPException(422, "The uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Files over 50 MB are not accepted yet")
    out: dict = {"ok": False, "file": {"name": safe_filename(filename), "bytes": len(data),
                                       "sha256": hashlib.sha256(data).hexdigest()},
                 "mapping_key": spec.key, "channels_named": channels_named, "next_step": "",
                 "problems": [], "warnings": [], "channels": [], "wells": [], "metadata": {}}
    try:
        run = parse_file_isolated(data, spec, float(os.environ.get("BOB_MAPPING_TIMEOUT_S", "30")))
    except MappingError as exc:
        out["problems"].append(str(exc))
        return out
    except Exception as exc:
        out["problems"].append(f"the file could not be read with this mapping: {exc}")
        return out

    out["metadata"] = run.metadata
    out["warnings"] = list(run.warnings)
    out["wells"] = run.positions
    for sig in run.signals:
        head, optics = sig.label.partition(":")[0].strip(), sig.label.partition(":")[2].strip()
        times_h = [round(t / 3600.0, 4) for t in sig.times]
        measured = [p for p, vals in sig.values.items() if any(v is not None for v in vals)]
        # the first header position can be an empty well, which would preview as all n/a
        sample_wells = (measured or sig.positions)[:3]
        out["channels"].append({
            "label": sig.label,
            "instrument_label": head if label_has_optics and optics else sig.label,
            "optics_text": optics if label_has_optics else "",
            "name": sig.name,
            "kind": sig.kind,
            "unit": sig.unit,
            "optics": sig.optics,
            "header_position_count": len(sig.positions),
            "measured_well_count": len(measured),
            "point_count": len(sig.times),
            "first_time_h": times_h[0] if times_h else None,
            "last_time_h": times_h[-1] if times_h else None,
            "has_temperature": any(v is not None for v in sig.temperatures),
            "preview": {"time_h": times_h[:3],
                        "wells": [{"position": p, "values": sig.values[p][:3]} for p in sample_wells]},
        })
    if not channels_named:
        out["next_step"] = ("the file was read; say what each channel measures, because nothing is "
                            "claimed about kind or unit until you do")
        return out
    out["ok"] = not out["problems"]
    return out


def import_assay(db: Session, settings: Settings, study: Study, name: str, mapping_key: str, filename: str, data: bytes, user: User | None) -> Assay:
    mapping, run = parse_plate(db, study.investigation.workspace_id, mapping_key, data)
    return store_assay(db, settings, study, name, mapping, run, filename, data, user)


def store_assay(db: Session, settings: Settings, study: Study, name: str, mapping: InstrumentMapping, run: ParsedRun, filename: str, data: bytes,
                user: User | None, signal_names: list[tuple[str, str, str]] | None = None) -> Assay:
    """`signal_names` renames the run's signals in read order, with a description and color for each."""
    workspace_id = study.investigation.workspace_id
    artifact = store_artifact(db, settings, workspace_id, filename, data, user)
    db.flush()
    assay = Assay(
        study_id=study.id,
        name=(clean_line(name) or Path(safe_filename(filename)).stem)[:200],
        modality=mapping.modality,
        mapping_id=mapping.id,
        mapping_key=mapping.key,
        mapping_version=mapping.version,
        artifact_id=artifact.id,
        run_metadata=run.metadata,
        warnings=run.warnings,
        created_by=user.id if user else None,
    )
    db.add(assay)
    db.flush()
    for i, parsed in enumerate(run.signals):
        name, description, color = signal_names[i] if signal_names else (parsed.name, "", "")
        signal = Signal(
            assay_id=assay.id,
            position=i,
            name=name[:80],
            label=parsed.label[:200],
            kind=parsed.kind,
            unit=parsed.unit[:24],
            description=description[:200],
            color=color[:32],
            optics=parsed.optics,
            times=parsed.times,
        )
        db.add(signal)
        db.flush()
        db.add_all(Series(signal_id=signal.id, position=pos, values=vals) for pos, vals in parsed.values.items())
    db.add_all(Well(assay_id=assay.id, position=pos) for pos in run.positions)
    return assay


def set_sample_components(sample: Sample, components: list[dict]) -> None:
    sample.components.clear()
    for i, c in enumerate(components):
        iri = (c.get("iri") or "").strip()
        if not iri:
            continue
        sample.components.append(
            SampleComponent(
                position=i,
                role=c.get("role", "strain"),
                iri=iri,
                label=(c.get("label") or "").strip(),
                amount=c.get("amount"),
                unit=(c.get("unit") or "").strip() or None,
                sbol_version=c.get("sbol_version"),
                sbol_class=c.get("sbol_class"),
            )
        )


def live_layout(assay: Assay) -> dict[str, Sample]:
    return {w.position: w.sample for w in assay.wells if w.sample is not None}


def snapshot_layout(snap_assay: dict, snap_samples: list[dict]) -> dict[str, SampleRef]:
    samples = {
        s["id"]: SampleRef(
            s["id"], s["name"], s["sample_type"],
            [SampleComponentRef(c["role"], c["iri"], c.get("label", ""), c.get("amount"), c.get("unit"))
             for c in s.get("components", [])],
        )
        for s in snap_samples
    }
    return {pos: samples[sid] for pos, sid in snap_assay["layout"].items() if sid in samples}


def _signal(signals: list[SignalData], name: str) -> SignalData:
    for s in signals:
        if s.name == name:
            return s
    raise HTTPException(404, f"Assay has no signal {name!r}")


# which sample type can serve as a channel's background: medium-only wells for absorbance,
# matched untransformed cells for a reporter. A shared type is not evidence of compatibility.
CONTROL_TYPE_FOR_KIND = {"absorbance": "medium", "fluorescence": "untransformed"}


def control_candidates(kind: str, layout: dict) -> tuple[str | None, dict[str, list[str]]]:
    """The sample groups that could serve as this channel's background, by sample id."""
    want = CONTROL_TYPE_FOR_KIND.get(kind)
    if want is None:
        return None, {}
    out: dict[str, list[str]] = {}
    for pos, sample in layout.items():
        if sample.sample_type == want:
            out.setdefault(sample.id, []).append(pos)
    return want, {sid: sorted(ps, key=_well_order) for sid, ps in out.items()}


def _chemical_context(sample) -> set:
    return {(c.role, c.iri, c.amount, c.unit)
            for c in getattr(sample, "components", []) if c.role not in NON_CHEMICAL_ROLES}


def check_controls(layout: dict, measured: dict[str, list[str]], controls: list[str],
                   want_type: str, role: str, context_acknowledged: bool,
                   name_groups: bool = False, available: set | None = None) -> tuple[list[str], list[str]]:
    """Validate explicitly selected control wells against every measured group.

    Returns the wells whose context is unrecorded and those whose host is unestablished. Raises
    ValueError on anything that cannot be resolved into a defensible background.
    """
    if not controls:
        raise ValueError(f"select explicit {want_type} control wells for the {role} background, "
                         f"or turn correction off to plot raw values")
    known = set(layout)
    bad = [p for p in controls if p not in known]
    if bad:
        raise ValueError(f"control wells not assigned in the plate map: {', '.join(sorted(bad))}")
    # background_correct drops positions it has no series for, so a well assigned in the layout but
    # unread in this channel would be reported as the background while contributing nothing
    if available is not None:
        unread = [p for p in controls if p not in available]
        if unread:
            raise ValueError(f"no readings in this channel for the selected control wells: "
                             f"{', '.join(sorted(unread))}")
    measured_positions = {p for ps in measured.values() for p in ps}
    overlap = measured_positions & set(controls)
    if overlap:
        raise ValueError(
            f"a well cannot be both measured and its own control: {', '.join(sorted(overlap))}. "
            f"Select the sample group you are analysing, so its controls are not among the wells plotted.")
    for p in controls:
        if layout[p].sample_type != want_type:
            raise ValueError(f"{p} is {layout[p].sample_type!r}; the {role} background needs {want_type!r} wells")

    unknown_context: list[str] = []
    for sid, positions in measured.items():
        if not positions:
            continue
        ctx = _chemical_context(layout[positions[0]])
        for p in controls:
            have = _chemical_context(layout[p])
            if not ctx or not have:
                unknown_context.append(p)
            elif have != ctx:
                where = f" of {layout[positions[0]].name!r}" if name_groups else ""
                raise ValueError(
                    f"{p} does not share the sample's medium and supplement context{where}, so it "
                    f"cannot serve as its {role} background. Analyse a compatible group on its own.")
    host_unknown = list(controls) if want_type == "untransformed" else []

    if (unknown_context or host_unknown) and not context_acknowledged:
        bits = []
        if host_unknown:
            bits.append("host compatibility is unknown for " + ", ".join(sorted(set(host_unknown))))
        if unknown_context:
            bits.append("medium and supplement context is not recorded for " + ", ".join(sorted(set(unknown_context))))
        raise ValueError("; ".join(bits) + ". Check control compatibility to continue.")
    return unknown_context, host_unknown


def _controls_for(kind: str, layout: dict) -> tuple[str | None, list[str]]:
    by_type: dict[str, list[str]] = {}
    for pos, sample in layout.items():
        by_type.setdefault(sample.sample_type, []).append(pos)
    order = ["medium"] if kind == "absorbance" else ["untransformed", "medium"]
    for t in order:
        if by_type.get(t):
            return t, sorted(by_type[t])
    return None, []


def prepared_values(signals: list[SignalData], layout: dict, signal_name: str, correct: bool,
                    threshold_sd: float, drop_below: bool, normalize_by: str | None, min_od: float,
                    controls: list[str] | None = None, normalize_controls: list[str] | None = None,
                    samples: list[str] | None = None, context_acknowledged: bool = False):
    """Values per position after optional correction and normalization, plus what was applied.

    Correction subtracts only the control wells the caller selected, and refuses rather than
    returning raw values under a corrected claim. The normalization channel is validated on its own.
    """
    signal = _signal(signals, signal_name)
    warnings: list[str] = []

    # controls are resolved against the whole assay; only the reported groups are narrowed
    resolved = layout
    if samples:
        chosen = set(samples)
        missing = chosen - {s.id for s in layout.values()}
        if missing:
            raise ValueError(f"samples not assigned to any well in this assay: {', '.join(sorted(missing))}")
        layout = {pos: s for pos, s in layout.items() if s.id in chosen}
        if not layout:
            raise ValueError("the selected samples have no wells in this assay")

    values = {pos: list(v) for pos, v in signal.series.items()}
    measured, _samples_by_id = sample_groups(layout)
    corrected = False
    control_type = None
    used_controls: list[str] = []
    unknown_context: list[str] = []
    host_unknown: list[str] = []

    if correct:
        want = CONTROL_TYPE_FOR_KIND.get(signal.kind)
        if want is None:
            raise ValueError(f"{signal.name} reads {signal.kind}, which has no defined background control")
        picked = sorted(set(controls or ()), key=_well_order)
        unknown_context, host_unknown = check_controls(
            resolved, measured, picked, want, "measured", context_acknowledged,
            name_groups=True, available=set(signal.series))
        values = analysis.background_correct(signal.times, values, picked, threshold_sd, drop_below).corrected
        corrected, control_type, used_controls = True, want, picked

    od_values = None
    normalize_controls_used: list[str] = []
    od_alignment: dict = {}
    if normalize_by:
        od_signal = _signal(signals, normalize_by)
        od_raw = {pos: list(v) for pos, v in od_signal.series.items()}
        if correct:
            od_want = CONTROL_TYPE_FOR_KIND.get(od_signal.kind)
            if od_want is None:
                raise ValueError(f"{od_signal.name} reads {od_signal.kind}, which has no defined background control")
            od_picked = sorted(set(normalize_controls or ()), key=_well_order)
            u2, h2 = check_controls(resolved, measured, od_picked, od_want,
                                    "normalisation", context_acknowledged,
                                    name_groups=True, available=set(od_signal.series))
            unknown_context += u2
            host_unknown += h2
            od_raw = analysis.background_correct(od_signal.times, od_raw, od_picked).corrected
            normalize_controls_used = od_picked
        od_values, od_why = {}, {}
        for pos in values:
            od_values[pos], od_why[pos] = analysis.resample_onto(od_signal.times, od_raw.get(pos, []), signal.times)
        # missingness differs per well, so the counts are per well and the total carries its own
        # denominator rather than one well's counts standing in for all of them
        per_well = {pos: analysis.alignment_counts(w) for pos, w in od_why.items()}
        keys = ("target_points", "points_matched_exactly", "points_interpolated",
                "points_missing_outside_support", "points_missing_source_reading",
                "points_missing_bracket_reading")
        od_alignment = {
            "normalisation_signal": od_signal.name,
            "normalisation_unit": od_signal.unit,
            "timestamps_shared": list(od_signal.times) == list(signal.times),
            "aligned_by": "linear interpolation within measured support",
            "wells": len(per_well),
            "per_well_counts": per_well,
            "totals_across_wells": {k: sum(c[k] for c in per_well.values()) for k in keys},
        }

    if unknown_context:
        warnings.append("Medium and supplement context is not recorded for "
                        + ", ".join(sorted(set(unknown_context)))
                        + ". Confirmed by the user for this request.")
    if host_unknown:
        warnings.append("Host compatibility is not established by metadata for "
                        + ", ".join(sorted(set(host_unknown)))
                        + "; matching medium does not establish a shared chassis. "
                        "Confirmed by the user for this request.")

    provenance = {
        "corrected": corrected,
        "control_type": control_type,
        "control_wells": used_controls,
        "normalisation_control_wells": normalize_controls_used,
        "context_unknown_wells": sorted(set(unknown_context)),
        # medium blanks contain no cells, so no host applies to them; only a reporter background
        # rests on an unestablished shared chassis
        "host_compatibility": "unknown" if host_unknown else "not applicable",
        "context_acknowledged_by_user": bool(context_acknowledged),
        "normalisation_alignment": od_alignment,
        "signal_unit": signal.unit,
    }
    return signal, values, od_values, corrected, control_type, used_controls, layout, warnings, provenance


def sample_groups(layout: dict) -> tuple[dict[str, list[str]], dict]:
    groups: dict[str, list[str]] = {}
    samples: dict = {}
    for pos in sorted(layout, key=_well_order):
        sample = layout[pos]
        groups.setdefault(sample.id, []).append(pos)
        samples[sample.id] = sample
    return groups, samples


def _well_order(pos: str) -> tuple[str, int]:
    return pos[0], int(pos[1:]) if pos[1:].isdigit() else 0


def study_record(snap: dict, base_iri: str, version: int | None = None, recipe_manifest: str = "") -> StudyRecord:
    """The SBOL view of a study snapshot; `version` is the published version it belongs to."""
    query = f"?version={version}" if version else ""
    assays, used_by = [], {}
    for a in snap["assays"]:
        raw = a["raw_file"]
        fmt = FORMAT_IRIS.get(raw["media_type"], raw["media_type"])
        sample_ids = sorted(set(a["layout"].values()))
        assays.append(AssayRecord(a["id"], a["name"], RawFile(f"{base_iri}/api/assays/{a['id']}/raw{query}", raw["sha256"], raw["size"], fmt), sample_ids))
        for pos, sid in a["layout"].items():
            used_by.setdefault(sid, set()).add(pos)
    samples = []
    for s in snap["samples"]:
        positions = sorted(used_by.get(s["id"], ()), key=_well_order)
        comps = [ComponentRef(c["iri"], c["role"], c["label"], c.get("amount"), c.get("unit")) for c in s["components"]]
        samples.append(SampleRecord(s["id"], s["name"], ",".join(positions), comps))
    st = snap["study"]
    creators = [" ".join(x for x in (a["given_name"], a.get("family_name", "")) if x) for a in st.get("authors", [])]
    return StudyRecord(st["id"], st["title"], st["description"], assays, samples, str(version or 1),
                       creators, LICENSES.get(st.get("license"), ""), recipe_manifest or "")


NON_CHEMICAL_ROLES = frozenset({"strain", "design", "plasmid", "vector"})


def check_channel_roles(reporter, biomass, workflow: str) -> None:
    """Refuse channel pairings BOB's two-channel workflows cannot interpret.

    A reporter output read against a biomass proxy needs two different channels in the roles each
    was measured for. The restriction is BOB's, not a claim that other designs are
    impossible; raw plotting of any channel is unaffected.
    """
    if reporter.name == biomass.name:
        raise ValueError(
            f"{reporter.name!r} cannot be both the reporter and the biomass channel; the "
            f"{workflow} reads one reporter against a separate biomass proxy")
    for channel, role, want, article in ((reporter, "reporter", "fluorescence", "a"),
                                         (biomass, "biomass proxy", "absorbance", "an")):
        if channel.kind != want:
            raise ValueError(
                f"{channel.name!r} is a {channel.kind} channel, and the {workflow} "
                f"reads the {role} from {article} {want} channel. Raw plotting of {channel.kind} "
                f"channels stays available; only this calculation is restricted.")


def rate_inputs(signals, layout, signal_name: str, biomass_name: str, positions: list[str],
                biomass_controls: list[str], reporter_controls: list[str],
                context_acknowledged: bool = False):
    """Background-subtract a well group against explicitly chosen control wells, never inferred ones."""
    by_name = {s.name: s for s in signals}
    for want in (signal_name, biomass_name):
        if want not in by_name:
            raise ValueError(f"no signal named {want!r} in this assay")
    sig, bio = by_name[signal_name], by_name[biomass_name]

    check_channel_roles(sig, bio, "rate workflow")

    known = set(layout)
    for label, group in (("wells", positions), ("biomass controls", biomass_controls), ("reporter controls", reporter_controls)):
        missing = [p for p in group if p not in known]
        if missing:
            raise ValueError(f"{label} not assigned in the plate map: {', '.join(sorted(missing))}")
        if not group:
            raise ValueError(f"select at least one well for {label}")
    for pos in biomass_controls:
        if layout[pos].sample_type != "medium":
            raise ValueError(f"{pos} is {layout[pos].sample_type!r}; biomass background needs medium-only wells")
    for pos in reporter_controls:
        if layout[pos].sample_type != "untransformed":
            raise ValueError(f"{pos} is {layout[pos].sample_type!r}; reporter background needs untransformed cells, and a medium well is not a substitute")

    overlap = (set(positions) & set(biomass_controls)) | (set(positions) & set(reporter_controls))
    if overlap:
        raise ValueError(f"a well cannot be both a measured sample and its own control: {', '.join(sorted(overlap))}")

    chosen = {layout[p].id for p in positions}
    if len(chosen) > 1:
        names = sorted({layout[p].name for p in positions})
        raise ValueError(f"selected wells span more than one sample ({', '.join(names)}); fit one experimental group at a time")

    # compare only the chemical context, with amounts and units: a different engineered-strain IRI
    # is not evidence of a different chassis, since the parent host may simply not be recorded
    def _context(sample):
        # exclude the genetic roles rather than listing the chemical ones, so a role such as
        # inducer is compared rather than silently ignored
        return {
            (c.role, c.iri, c.amount, c.unit)
            for c in getattr(sample, "components", [])
            if c.role not in NON_CHEMICAL_ROLES
        }

    sample = layout[positions[0]]
    wanted = _context(sample)
    unknown_context = []
    mismatches = []
    for label, group in (("biomass", biomass_controls), ("reporter", reporter_controls)):
        for pos in group:
            have = _context(layout[pos])
            if not hasattr(layout[pos], "components") or not hasattr(sample, "components"):
                unknown_context.append(pos)
            elif not wanted or not have:
                unknown_context.append(pos)
            elif have != wanted:
                mismatches.append((pos, label))
    if mismatches:
        detail = "; ".join(f"{pos} does not match the sample's medium and supplement context for the {label} background" for pos, label in mismatches)
        raise ValueError(detail)

    # a layout assignment does not prove a measurement exists, and the loops below index
    # series[p] directly, so an unread selection would crash instead of refusing
    for group, channel, label in ((biomass_controls, bio, "biomass control"),
                                  (reporter_controls, sig, "reporter control"),
                                  (positions, bio, "measured"), (positions, sig, "measured")):
        unread = [p for p in group if p not in channel.series]
        if unread:
            raise ValueError(
                f"the selected {label} wells have no readings in {channel.name}: "
                f"{', '.join(sorted(unread))}. A well assigned in the plate map is not necessarily "
                f"measured in every channel, and the selection is not silently shrunk to the wells "
                f"that were read; select wells this channel actually recorded.")

    def _mean_at(values, group, k):
        vals = [values[p][k] for p in group if values[p][k] is not None]
        return sum(vals) / len(vals) if vals else None

    def _corrected(values, group, controls, n_times):
        out = []
        for k in range(n_times):
            bg = _mean_at(values, controls, k)
            vals = [values[p][k] for p in group if values[p][k] is not None]
            out.append(None if bg is None or not vals else sum(vals) / len(vals) - bg)
        return out

    y = _corrected(sig.series, positions, reporter_controls, len(sig.times))
    b_own = _corrected(bio.series, positions, biomass_controls, len(bio.times))

    # the two channels need not share a time grid; interpolate biomass onto the reporter's
    # timestamps, and refuse any reporter time outside the biomass's own measured support
    aligned = list(sig.times) == list(bio.times)
    times, trimmed = list(sig.times), 0
    if aligned:
        b = b_own
    else:
        known = [(tt, v) for tt, v in zip(bio.times, b_own) if v is not None]
        if len(known) < 2:
            raise ValueError("biomass has too few readings to align onto the reporter timestamps")
        lo, hi = known[0][0], known[-1][0]
        keep = [i for i, tt in enumerate(sig.times) if lo - 1e-9 <= tt <= hi + 1e-9]
        if len(keep) < 4:
            raise ValueError("reporter and biomass timestamps overlap on fewer than four points")
        trimmed = len(sig.times) - len(keep)
        times = [sig.times[i] for i in keep]
        y = [y[i] for i in keep]
        kt = [k for k, _ in known]
        kv = [v for _, v in known]
        b = [float(_np.interp(tt, kt, kv)) for tt in times]

    # a reporter-negative control must share the sample's chassis, and nothing in the model maps an
    # engineered strain to its parent host, so host compatibility is never established by metadata
    host_unknown = sorted(set(reporter_controls))

    provenance = {
        "reporter_signal": sig.name,
        "biomass_signal": bio.name,
        "timestamps_shared": aligned,
        "biomass_aligned_by": "none" if aligned else "linear interpolation within measured support",
        "timestamps_trimmed_outside_biomass_support": trimmed,
        "time_origin_s": float(times[0]),
        "time_origin_provenance": "absolute seconds since the run started, as stored",
        "wells": sorted(positions),
        "biomass_control_wells": sorted(biomass_controls),
        "reporter_control_wells": sorted(reporter_controls),
        "biomass_control_n": len(biomass_controls),
        "reporter_control_n": len(reporter_controls),
        "single_control_well": len(biomass_controls) < 2 or len(reporter_controls) < 2,
        "context_unknown_wells": sorted(set(unknown_context)),
        "context_checked": not unknown_context,
        "context_acknowledged_by_user": bool(context_acknowledged),
        "host_compatibility": "unknown",
        "host_unknown_wells": host_unknown,
        "host_unknown_reason": "no parent-host mapping is recorded, so a shared chassis cannot be established from the strain identifiers",
        "context_unknown_reason": (
            "this assay version is frozen and its stored samples carry no component metadata"
            if unknown_context and not hasattr(sample, "components")
            else "no medium, supplement or inducer components are recorded"
            if unknown_context else ""
        ),
        "replicate_wells_averaged": len(positions),
        "aggregation": "fit to the mean of the selected replicate observations, not the mean of per-well rates",
    }
    return times, y, b, sig, bio, provenance


_PRESET_CONTROLS = {
    "growth_curve": ("biomass",),
    "reporter_trajectory": ("reporter",),
    "reporter_per_biomass": ("biomass", "reporter"),
    "mean_over_run": ("reporter",),
}


def preset_inputs(signals, layout, preset: str, positions: list[str],
                  biomass_controls: list[str], reporter_controls: list[str],
                  reporter_name: str | None, biomass_name: str | None,
                  context_acknowledged: bool = False):
    """Background-subtract against the wells the user actually chose, per preset.

    A preset asks only for the controls its measurement needs: a biomass curve needs medium-only
    wells and no host at all, while a corrected reporter needs matched untransformed cells.
    """
    if preset not in _PRESET_CONTROLS:
        raise ValueError(f"unknown preset {preset!r}")
    needs = _PRESET_CONTROLS[preset]
    by_name = {s.name: s for s in signals}
    wanted = {"biomass": biomass_name, "reporter": reporter_name}
    for role in needs:
        nm = wanted[role]
        if not nm or nm not in by_name:
            raise ValueError(f"{preset} needs a {role} channel that exists in this assay")

    if "biomass" in needs and "reporter" in needs:
        check_channel_roles(by_name[reporter_name], by_name[biomass_name], f"{preset} workflow")
    else:
        for role, want, article in (("biomass", "absorbance", "an"), ("reporter", "fluorescence", "a")):
            if role not in needs:
                continue
            channel = by_name[wanted[role]]
            if channel.kind != want:
                raise ValueError(
                    f"{channel.name!r} is a {channel.kind} channel, and the {preset} "
                    f"workflow reads the {'biomass proxy' if role == 'biomass' else role} from "
                    f"{article} {want} channel. Raw plotting of {channel.kind} channels stays "
                    f"available; only this calculation is restricted.")

    known = set(layout)
    if not positions:
        raise ValueError("select at least one well")
    missing = [p for p in positions if p not in known]
    if missing:
        raise ValueError(f"wells not assigned in the plate map: {', '.join(sorted(missing))}")
    if len({layout[p].id for p in positions}) > 1:
        raise ValueError("selected wells span more than one sample; fit one experimental group at a time")

    groups = {"biomass": biomass_controls, "reporter": reporter_controls}
    want_type = {"biomass": "medium", "reporter": "untransformed"}
    for role in needs:
        group = groups[role]
        if not group:
            raise ValueError(f"{preset} needs explicit {want_type[role]} control wells")
        bad = [p for p in group if p not in known]
        if bad:
            raise ValueError(f"control wells not assigned in the plate map: {', '.join(sorted(bad))}")
        overlap = set(positions) & set(group)
        if overlap:
            raise ValueError(f"a well cannot be both measured and its own control: {', '.join(sorted(overlap))}")
        for p in group:
            if layout[p].sample_type != want_type[role]:
                raise ValueError(f"{p} is {layout[p].sample_type!r}; the {role} background needs {want_type[role]!r} wells")

    sample = layout[positions[0]]
    ctx = {(c.role, c.iri, c.amount, c.unit) for c in getattr(sample, "components", []) if c.role not in NON_CHEMICAL_ROLES}
    unknown_context, host_unknown = [], []
    for role in needs:
        for p in groups[role]:
            have = {(c.role, c.iri, c.amount, c.unit) for c in getattr(layout[p], "components", []) if c.role not in NON_CHEMICAL_ROLES}
            if not ctx or not have:
                unknown_context.append(p)
            elif have != ctx:
                raise ValueError(f"{p} does not share the sample's medium and supplement context, so it cannot serve as its {role} background")
        if role == "reporter":
            host_unknown.extend(groups[role])

    if (unknown_context or host_unknown) and not context_acknowledged:
        bits = []
        if host_unknown:
            bits.append("host compatibility is unknown for " + ", ".join(sorted(set(host_unknown))))
        if unknown_context:
            bits.append("medium and supplement context is not recorded for " + ", ".join(sorted(set(unknown_context))))
        raise ValueError("; ".join(bits) + ". Check control compatibility to continue.")

    for role in needs:
        channel = by_name[wanted[role]]
        for group, label in ((groups[role], f"{role} control"), (positions, "measured")):
            unread = [p for p in group if p not in channel.series]
            if unread:
                raise ValueError(
                    f"the selected {label} wells have no readings in {channel.name}: "
                    f"{', '.join(sorted(unread))}. A well assigned in the plate map is not "
                    f"necessarily measured in every channel, and the selection is not silently "
                    f"shrunk to the wells that were read; select wells this channel actually recorded.")

    def _series(sig, group):
        out = []
        for k in range(len(sig.times)):
            ctrl = [sig.series[p][k] for p in group if sig.series[p][k] is not None]
            vals = [sig.series[p][k] for p in positions if sig.series[p][k] is not None]
            if not vals or (group and not ctrl):
                out.append(None)
            else:
                out.append(sum(vals) / len(vals) - (sum(ctrl) / len(ctrl) if group else 0.0))
        return out

    result = {"times": list(by_name[wanted[needs[0]]].times)}
    alignment = {"timestamps_shared": None, "biomass_aligned_by": "not applicable"}
    if "biomass" in needs:
        b = by_name[biomass_name]
        result["biomass"] = _series(b, biomass_controls)
        result["biomass_unit"] = b.unit
        result["biomass_times"] = list(b.times)
    if "reporter" in needs:
        r = by_name[reporter_name]
        result["reporter"] = _series(r, reporter_controls)
        result["reporter_raw"] = _series(r, [])
        result["reporter_unit"] = r.unit
        result["times"] = list(r.times)
    if "biomass" in needs and "reporter" in needs:
        own_times, own = result["biomass_times"], result["biomass"]
        same = list(own_times) == list(result["times"])
        alignment["timestamps_shared"] = same
        # equal lengths are not equal acquisition times, so pair by timestamp or not at all
        values, why = analysis.resample_onto(own_times, own, result["times"])
        alignment["biomass_aligned_by"] = ("none, both channels share their timestamps" if same
                                           else "linear interpolation within measured support")
        alignment["biomass_alignment"] = analysis.alignment_counts(why)
        result["biomass"] = values
        result["biomass_alignment_per_point"] = why
    result["provenance"] = {
        "wells": sorted(positions),
        "biomass_control_wells": sorted(biomass_controls) if "biomass" in needs else [],
        "reporter_control_wells": sorted(reporter_controls) if "reporter" in needs else [],
        "controls_required": list(needs),
        "context_unknown_wells": sorted(set(unknown_context)),
        "host_compatibility": "unknown" if host_unknown else "not applicable",
        "context_acknowledged_by_user": bool(context_acknowledged),
        "replicate_wells_averaged": len(positions),
        "aggregation": "mean of the selected replicate wells at each time point",
        "time_origin_s": float(result["times"][0]) if result["times"] else 0.0,
        "time_origin_provenance": "absolute seconds since the run started, as stored",
        "reporter_signal": reporter_name if "reporter" in needs else "",
        "biomass_signal": biomass_name if "biomass" in needs else "",
        **alignment,
    }
    return result
