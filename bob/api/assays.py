import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import access, analysis, rates, recipes, services, versions, workbook_import
from bob.api import synbiohub as synbiohub_api
from bob.api import serialize
from bob.models import Assay, FrozenAssay, InstrumentMapping, StudyEvent, User
from bob.security import current_user, get_db

router = APIRouter(prefix="/api", tags=["assays"])

Version = Query(None, ge=1, description="A published version of the study; the live assay when omitted")


class LayoutIn(BaseModel):
    assignments: dict[str, str | None]


def _mapping_name(db: Session, a: Assay) -> str | None:
    return db.scalar(select(InstrumentMapping.name).where(InstrumentMapping.id == a.mapping_id)) if a.mapping_id else None


def _published(db: Session, user: User, assay_id: str, number: int):
    """The study, version, and snapshot entry of an assay as published in version `number`."""
    frozen = db.get(FrozenAssay, assay_id)
    live = db.get(Assay, assay_id) if frozen is None else None
    if frozen is None and live is None:
        raise HTTPException(404, "Assay not found")
    st = access.study(db, user, frozen.study_id if frozen else live.study_id)
    v = versions.get(db, st, number)
    return st, v, versions.snapshot_assay(v, assay_id)


def _source(db: Session, user: User, assay_id: str, number: int | None):
    """Measurements and plate layout of the live assay, or of one published version of it."""
    if number is None:
        a = access.assay(db, user, assay_id)
        return versions.live_signals(a), services.live_layout(a)
    _st, v, snap = _published(db, user, assay_id, number)
    return versions.frozen_signals(versions.frozen(db, assay_id)), services.snapshot_layout(snap, v.snapshot["samples"])


@router.get("/studies/{study_id}/assays")
def list_assays(study_id: str, version: int | None = Version, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    if version is not None:
        v = versions.get(db, st, version)
        return [serialize.snapshot_assay(a, st.id, version) for a in reversed(v.snapshot["assays"])]
    return [serialize.assay(a, _mapping_name(db, a)) for a in sorted(st.assays, key=lambda a: a.created_at, reverse=True)]


@router.post("/studies/{study_id}/assays", status_code=201)
def upload_assay(
    study_id: str,
    request: Request,
    name: str = Form(""),
    mapping_key: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # A plain def runs in the worker pool, so parsing a large workbook cannot stall other requests.
    st = access.study(db, user, study_id, "editor")
    versions.ensure_first(db, st)
    data = file.file.read(services.MAX_UPLOAD_BYTES + 1)
    assay = services.import_assay(db, request.app.state.settings, st, name, mapping_key, file.filename or "upload.xlsx", data, user)
    assay_id = assay.id
    versions.record(db, st, user, f"Added assay {assay.name}")
    db.commit()
    assay = db.get(Assay, assay_id)
    return serialize.assay(assay, _mapping_name(db, assay))


@router.get("/assays/{assay_id}")
def get_assay(assay_id: str, version: int | None = Version, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if version is not None:
        st, _v, snap = _published(db, user, assay_id, version)
        return serialize.snapshot_assay(snap, st.id, version)
    a = access.assay(db, user, assay_id)
    return serialize.assay(a, _mapping_name(db, a))


@router.delete("/assays/{assay_id}", status_code=204)
def delete_assay(assay_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = access.assay(db, user, assay_id, "editor")
    st, name = a.study, a.name
    versions.ensure_first(db, st)
    db.delete(a)
    versions.record(db, st, user, f"Removed assay {name}")
    db.commit()
    services.purge_unused_artifacts(db, request.app.state.settings)
    return Response(status_code=204)


@router.get("/assays/{assay_id}/raw")
def raw_file(assay_id: str, request: Request, version: int | None = Version, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if version is not None:
        _st, _v, snap = _published(db, user, assay_id, version)
        art = versions.artifact(db, snap["raw_file"]["artifact_id"])
    else:
        art = access.assay(db, user, assay_id).artifact
    path = request.app.state.settings.artifact_dir / art.storage_key
    if not path.exists():
        raise HTTPException(410, "The raw file is missing from storage")
    return FileResponse(path, media_type=art.media_type, filename=art.filename)


def _layout_out(a: Assay) -> dict:
    positions = sorted(a.wells, key=lambda w: (w.position[0], int(w.position[1:]) if w.position[1:].isdigit() else 0))
    samples = sorted(a.study.samples, key=lambda s: (s.sample_type != "sample", s.name.lower()))
    return {
        "assay_id": a.id,
        "positions": [{"position": w.position, "sample_id": w.sample_id} for w in positions],
        "samples": [serialize.sample(s) for s in samples],
    }


@router.get("/assays/{assay_id}/layout")
def get_layout(assay_id: str, version: int | None = Version, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if version is not None:
        st, v, snap = _published(db, user, assay_id, version)
        return {
            "assay_id": assay_id,
            "positions": [{"position": p, "sample_id": snap["layout"].get(p)} for p in snap["positions"]],
            "samples": [serialize.snapshot_sample(s, st.id) for s in v.snapshot["samples"]],
        }
    return _layout_out(access.assay(db, user, assay_id))


@router.put("/assays/{assay_id}/layout")
def put_layout(assay_id: str, body: LayoutIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = access.assay(db, user, assay_id, "editor")
    versions.ensure_first(db, a.study)
    wells = {w.position: w for w in a.wells}
    study_samples = {s.id for s in a.study.samples}
    for position, sample_id in body.assignments.items():
        if position not in wells:
            raise HTTPException(422, f"Assay has no position {position}")
        if sample_id is not None and sample_id not in study_samples:
            raise HTTPException(422, f"Sample {sample_id} does not belong to this study")
        wells[position].sample_id = sample_id
    versions.record(db, a.study, user, f"Changed the plate layout of {a.name}")
    db.commit()
    return _layout_out(db.get(Assay, assay_id))


@router.get("/assays/{assay_id}/series")
def series(
    assay_id: str,
    signal: str,
    correct: bool = True,
    threshold_sd: float = Query(2.0, ge=0),
    drop_below: bool = False,
    normalize_by: str | None = None,
    min_od: float = Query(0.05, ge=0),
    controls: str = "",
    normalize_controls: str = "",
    samples: str = "",
    context_acknowledged: bool = False,
    version: int | None = Version,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    signals, layout = _source(db, user, assay_id, version)
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    try:
        sig, values, od, corrected, control_type, controls_used, layout, warnings, provenance = services.prepared_values(
            signals, layout, signal, correct, threshold_sd, drop_below, normalize_by or None, min_od,
            split(controls), split(normalize_controls), split(samples), context_acknowledged
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    controls = controls_used
    if od is not None:
        values = {
            pos: [(v / o) if (v is not None and o is not None and o > 0 and o >= min_od) else None for v, o in zip(vals, od[pos])]
            for pos, vals in values.items()
        }
    groups, samples = services.sample_groups(layout)
    if not groups:
        warnings.append("No wells are assigned to samples yet. Assign wells in the plate map to see grouped curves.")
    out = []
    for g in analysis.grouped_series(sig.times, values, groups):
        s = samples[g.group]
        out.append(
            {
                "group": s.name,
                "sample_id": s.id,
                "sample_type": s.sample_type,
                "positions": g.positions,
                "times_h": [t / 3600 for t in g.times],
                "mean": g.mean,
                "sd": g.sd,
                "n": g.n,
            }
        )
    unit = f"{sig.unit}/{normalize_by}" if od is not None else sig.unit
    return {
        "signal": sig.name,
        "unit": unit,
        "corrected": corrected,
        "normalized_by": normalize_by if od is not None else None,
        "control_type": control_type,
        "control_positions": controls,
        "groups": out,
        "provenance": provenance,
        "warnings": warnings,
    }


@router.get("/assays/{assay_id}/mean-expression")
def mean_expression(
    assay_id: str,
    signal: str,
    correct: bool = True,
    normalize_by: str | None = None,
    min_od: float = Query(0.05, ge=0),
    controls: str = "",
    normalize_controls: str = "",
    samples: str = "",
    context_acknowledged: bool = False,
    version: int | None = Version,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    signals, layout = _source(db, user, assay_id, version)
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    try:
        sig, values, od, corrected, _ct, _cu, layout, warnings, provenance = services.prepared_values(
            signals, layout, signal, correct, 2.0, False, normalize_by or None, min_od,
            split(controls), split(normalize_controls), split(samples), context_acknowledged
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    per_well = {pos: analysis.mean_expression(sig.times, vals, od.get(pos) if od else None, min_od) for pos, vals in values.items() if pos in layout}
    groups, samples_by_id = services.sample_groups(layout)
    stats = analysis.group_stats(per_well, groups)
    return {
        "signal": sig.name,
        "corrected": corrected,
        "normalized_by": normalize_by if od is not None else None,
        "groups": [{"group": samples_by_id[gid].name, "sample_id": gid, "sample_type": samples_by_id[gid].sample_type, **st} for gid, st in stats.items()],
        "wells": per_well,
        "provenance": provenance,
        "warnings": warnings,
    }


@router.get("/assays/{assay_id}/preset-series")
def preset_series(
    assay_id: str,
    preset: str,
    wells: str,
    biomass_signal: str | None = None,
    signal: str | None = None,
    biomass_controls: str = "",
    reporter_controls: str = "",
    context_acknowledged: bool = False,
    version: int | None = Version,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    signals, layout = _source(db, user, assay_id, version)
    row = db.get(Assay, assay_id)
    split = lambda s: [p.strip() for p in s.split(",") if p.strip()]
    try:
        out = services.preset_inputs(signals, layout, preset, split(wells),
                                     split(biomass_controls), split(reporter_controls),
                                     signal, biomass_signal, context_acknowledged)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    t0 = out["times"][0] if out["times"] else 0.0
    body = {
        "preset": preset,
        "assay_id": assay_id,
        "snapshot_version": version,
        "source_fingerprint": recipes.source_fingerprint(layout),
        "analysis_method": recipes.PRESETS[preset]["method"],
        "analysis_method_version": recipes.PRESETS[preset]["method_version"],
        "times_h": [(x - t0) / 3600 for x in out["times"]],
        "absolute_times_s": out["times"],
        "provenance": out["provenance"],
        "source": {
            "assay_id": assay_id,
            "assay_name": row.name,
            "snapshot_version": version,
            "raw_file_name": getattr(getattr(row, "artifact", None), "filename", None),
            "raw_file_sha256": getattr(getattr(row, "artifact", None), "sha256", None),
            "mapping_id": row.mapping_id,
            "mapping_key": row.mapping_key,
            "mapping_version": row.mapping_version,
        },
        "warnings": [],
    }
    if "biomass_alignment_per_point" in out:
        body["biomass_alignment_per_point"] = out["biomass_alignment_per_point"]
    for key in ("biomass", "reporter", "reporter_raw"):
        if key in out:
            body[key] = out[key]
    for key in ("biomass_unit", "reporter_unit"):
        if key in out:
            body[key] = out[key]
    if preset == "reporter_per_biomass":
        b, r = out.get("biomass") or [], out.get("reporter") or []
        body["ratio"] = [
            (rv / bv) if (rv is not None and bv is not None and bv > 0) else None
            for rv, bv in zip(r, b)
        ]
        body["ratio_unit"] = f"{out.get('reporter_unit')}/{out.get('biomass_unit')}"
        body["warnings"].append("A ratio of corrected reporter to biomass. Not a production rate and not molecules per cell.")
    if preset == "mean_over_run":
        vals = [v for v in (out.get("reporter") or []) if v is not None]
        body["mean"] = (sum(vals) / len(vals)) if vals else None
        body["n_points"] = len(vals)
        body["mean_unit"] = out.get("reporter_unit")
        body["aggregation"] = "arithmetic mean of retained corrected readings over the run"
        body["warnings"].append("Arithmetic mean of retained readings. Not an endpoint, not a growth rate, not a time-weighted mean.")
    pv = out["provenance"]
    if pv["context_unknown_wells"]:
        body["warnings"].append("Medium and supplement context is not recorded for " + ", ".join(pv["context_unknown_wells"]) + ".")
    if pv["host_compatibility"] == "unknown":
        body["warnings"].append("Host compatibility is not established by metadata; confirmed by the user for this request.")
    if pv["replicate_wells_averaged"] > 1:
        body["warnings"].append("Replicate wells were averaged before plotting, so this is a figure of mean observations.")
    return body


@router.get("/assays/{assay_id}/rates")
def rates_profile(
    assay_id: str,
    signal: str,
    biomass_signal: str,
    wells: str,
    biomass_controls: str,
    reporter_controls: str,
    delta: float = Query(1.0, gt=0),
    lam: float | None = None,
    gamma: float = Query(0.0, ge=0),
    context_acknowledged: bool = False,
    version: int | None = Version,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    signals, layout = _source(db, user, assay_id, version)
    row = db.get(Assay, assay_id)
    raw_sha = getattr(getattr(row, "artifact", None), "sha256", None)
    split = lambda s: [p.strip() for p in s.split(",") if p.strip()]
    try:
        times, y, b, sig, bio, provenance = services.rate_inputs(
            signals, layout, signal, biomass_signal, split(wells), split(biomass_controls), split(reporter_controls), context_acknowledged
        )
        growth = rates.growth_rate(times, b, delta=delta, lam=lam)
        production = rates.production_rate(times, y, b, gamma=gamma, delta=delta, lam=lam)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    warnings = []
    if provenance["host_unknown_wells"] and not context_acknowledged:
        raise HTTPException(status_code=422, detail=(
            "Host compatibility is unknown for reporter controls "
            + ", ".join(provenance["host_unknown_wells"])
            + f" ({provenance['host_unknown_reason']}). Matching medium does not establish a shared chassis. "
            + "Confirm these controls are the same host to continue."
        ))
    if provenance["context_unknown_wells"] and not context_acknowledged:
        raise HTTPException(status_code=422, detail=(
            "Medium, supplement and inducer context is not recorded for "
            + ", ".join(provenance["context_unknown_wells"])
            + f" ({provenance['context_unknown_reason']}). Confirm these controls share the sample's conditions to continue."
        ))
    if provenance["context_unknown_wells"]:
        warnings.append(
            "Medium and supplement context is not recorded for " + ", ".join(provenance["context_unknown_wells"])
            + ". Confirm these controls share the sample's conditions before trusting the background."
        )
    warnings.append(
        "Host compatibility is not verified by metadata: matching medium does not establish that the "
        "reporter controls share the sample's chassis. Confirmed by the user for this request."
    )
    if provenance["replicate_wells_averaged"] > 1:
        warnings.append("Replicate wells were averaged before fitting, so this is a fit to mean observations, not a mean of per-well rates.")
    if provenance["single_control_well"]:
        warnings.append("Fewer than two control wells on a channel; the control spread cannot be estimated.")
    for label, fit in (("growth", growth), ("production", production)):
        if not fit.converged:
            warnings.append(f"The {label} fit did not converge: {fit.diagnostics.get('solver_message', '')}")
        if fit.diagnostics.get("lambda_selection_rule_is_heuristic"):
            warnings.append(f"The {label} regularisation used the near-exact-residual heuristic, not an L-curve corner.")
        if fit.diagnostics.get("lambda_at_scan_boundary"):
            warnings.append(f"The {label} regularisation landed on the edge of the scanned range.")
        if fit.diagnostics.get("lambda_degenerate"):
            warnings.append(f"The {label} L-curve had no clear corner.")

    def profile(fit, unit):
        return {
            "times_h": fit.times,
            "rate": fit.rate,
            "fitted": fit.fitted,
            "unit": unit,
            "lambda": fit.lam,
            "converged": fit.converged,
            "diagnostics": fit.diagnostics,
        }

    return {
        "assay_id": assay_id,
        "source": {
            "assay_id": assay_id,
            "snapshot_version": version,
            "reporter_signal": sig.name,
            "reporter_unit": sig.unit,
            "biomass_signal": bio.name,
            "biomass_unit": bio.unit,
            "raw_file_sha256": raw_sha,
        },
        "method": rates.METHOD,
        "method_version": rates.METHOD_VERSION,
        "source_fingerprint": recipes.source_fingerprint(layout),
        "parameters": {"delta_h": delta, "lambda": lam, "gamma_per_h": gamma},
        "provenance": dict(provenance, snapshot_version=version, layout_source=('frozen snapshot version ' + str(version)) if version else 'live layout'),
        "observed": {"times_h": [(t - times[0]) / 3600 for t in times], "absolute_times_s": times, "reporter": y, "biomass": b},
        "growth": profile(growth, "1/h"),
        "production": profile(production, f"{sig.unit}/({bio.unit}*h)"),
        "warnings": warnings,
    }


class WorkbookForm:
    """The fields the import and its check share."""

    def __init__(
        self,
        workbook: UploadFile = File(..., description="An Excel-to-SBOL Assay workbook (.xlsx or .xlsm)"),
        plates: list[UploadFile] = File(..., description="One plate-reader file per assay in the workbook"),
        plate_assays: str = Form("", description='JSON {"plate file name": "workbook assay ID"}; needed unless one plate meets one assay'),
        mapping_key: str = Form("biotek-gen5-kinetic"),
        synbiohub_collection: str = Form("", description="The SynBioHub collection the workbook's SBOL was sent to, recorded with the study"),
        synbiohub_token: str = Form("", description="A SynBioHub token for reading this workbook's designs; used for this request only, never stored"),
        synbiohub_instance: str = Form("", description="The SynBioHub the token belongs to, when no collection says so"),
    ):
        self.workbook, self.plates, self.mapping_key = workbook, plates, mapping_key
        self.collection, self.token, self.instance = synbiohub_collection.strip(), synbiohub_token.strip(), synbiohub_instance.strip().rstrip("/")
        try:
            self.pairing = json.loads(plate_assays) if plate_assays.strip() else None
        except ValueError as exc:
            raise HTTPException(422, "plate_assays must be JSON") from exc
        if self.pairing is not None and not (isinstance(self.pairing, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in self.pairing.items())):
            raise HTTPException(422, 'plate_assays must map plate file names to assay IDs, like {"plate1.xlsx": "assay_1"}')
        if self.collection and not self.collection.startswith(("https://", "http://")):
            raise HTTPException(422, "synbiohub_collection must be a web address")


def _read(f: UploadFile) -> bytes:
    data = f.file.read(services.MAX_UPLOAD_BYTES + 1)
    if len(data) > services.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{f.filename}: files over 50 MB are not accepted yet")
    return data


def _tokens(request: Request, db: Session, user: User, form: WorkbookForm) -> tuple[dict[str, str | None], str]:
    """The token for each configured SynBioHub, and a note when the token sent along could not be placed."""
    instances = request.app.state.settings.synbiohub_instances
    tokens = {i: synbiohub_api.stored_token(request, db, user, i) for i in instances}
    if not form.token:
        return tokens, ""
    named = form.instance or next((i for i in instances if form.collection.startswith(i + "/")), "")
    if named not in instances:
        where = named or "an unnamed SynBioHub (send synbiohub_instance)"
        return tokens, f"The SynBioHub token sent with the import was not used: it is for {where}, not a SynBioHub this BOB server is set up to read"
    tokens[named] = form.token
    return tokens, ""


def _plan(request: Request, db: Session, user: User, st, form: WorkbookForm) -> workbook_import.Plan:
    name = services.safe_filename(form.workbook.filename or "workbook.xlsx")
    data = _read(form.workbook)
    plates = [(services.safe_filename(f.filename or f"plate{i}.xlsx"), _read(f)) for i, f in enumerate(form.plates, start=1)]
    tokens, note = _tokens(request, db, user, form)
    plan = workbook_import.plan(db, request.app.state.settings, st, data, name, plates, form.pairing, form.mapping_key, tokens)
    if note:
        plan.warnings.insert(0, note)
    return plan


@router.post("/studies/{study_id}/workbook/check")
def check_workbook(study_id: str, request: Request, form: WorkbookForm = Depends(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Everything importing this workbook would do, with nothing saved."""
    st = access.study(db, user, study_id, "editor")
    return workbook_import.describe(_plan(request, db, user, st, form))


@router.post("/studies/{study_id}/workbook", status_code=201)
def upload_workbook(study_id: str, request: Request, form: WorkbookForm = Depends(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id, "editor")
    versions.ensure_first(db, st)
    plan = _plan(request, db, user, st, form)
    if plan.problems:
        raise HTTPException(422, "; ".join(plan.problems))
    result = workbook_import.apply(db, request.app.state.settings, st, plan, user)
    replaced = any(a["action"] == "replace" for a in result["assays"])
    if result["changed"]:
        db.add(StudyEvent(study_id=st.id, kind="workbook", detail=f"{plan.filename} (sha256 {plan.sha256})", user_id=user.id))
    if form.collection:
        db.add(StudyEvent(study_id=st.id, kind="synbiohub", detail=form.collection[:1000], user_id=user.id))
    if result["changed"]:
        versions.record(db, st, user, f"Imported workbook {plan.filename}")
    db.commit()
    if replaced:
        services.purge_unused_artifacts(db, request.app.state.settings)
    return result
