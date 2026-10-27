from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import access, recipes as recipe_core
from bob.models import Assay, FigureRecipe, User
from bob.security import current_user, get_db

router = APIRouter(prefix="/api", tags=["recipes"])

_CONTROL_TYPE = {"biomass_control_id": "medium", "reporter_control_id": "untransformed"}
_CHANNEL_KIND = {"reporter_signal": "fluorescence", "biomass_signal": "absorbance"}


def _assay_source(db: Session, user: User, assay_id: str, version: int | None):
    from bob.api.assays import _source
    return _source(db, user, assay_id, version)


def _validate_against_source(cfg: dict, signals, layout: dict) -> dict:
    """Check every selection against the resolved assay, and return server-derived units."""
    by_name = {s.name: s for s in signals}
    for key, kind in _CHANNEL_KIND.items():
        want = cfg.get(key)
        if not want:
            continue
        sig = by_name.get(want)
        if sig is None:
            raise ValueError(f"this assay has no channel named {want!r}")
        if sig.kind != kind:
            raise ValueError(f"{want} reads {sig.kind}, which cannot serve as the {key.split('_')[0]} channel")

    assigned: dict[str, dict] = {}
    for sample in layout.values():
        sid = getattr(sample, "id", None)
        if sid:
            assigned.setdefault(sid, {"type": getattr(sample, "sample_type", None), "n": 0})
            assigned[sid]["n"] += 1
    for key in ("sample_id",) + tuple(_CONTROL_TYPE):
        sid = cfg.get(key)
        if not sid:
            continue
        info = assigned.get(sid)
        if info is None:
            raise ValueError(f"the selected {key.replace('_', ' ')} is not assigned to any well in this assay")
        want_type = _CONTROL_TYPE.get(key, "sample")
        if info["type"] != want_type:
            raise ValueError(f"the selected {key.replace('_', ' ')} is {info['type']!r}, but this role needs {want_type!r}")
    return {
        "reporter_unit": getattr(by_name.get(cfg.get("reporter_signal")), "unit", None),
        "biomass_unit": getattr(by_name.get(cfg.get("biomass_signal")), "unit", None),
    }


def _staleness(db: Session, user: User, rec: FigureRecipe) -> str:
    if not rec.assay_id:
        return "this recipe has no source assay"
    row = db.get(Assay, rec.assay_id)
    if row is None:
        return "the assay this recipe was saved from no longer exists"
    version = (rec.source or {}).get("snapshot_version")
    try:
        signals, layout = _assay_source(db, user, rec.assay_id, version)
    except Exception:
        return "the saved source could not be resolved"
    saved_raw = (rec.source or {}).get("raw_file_sha256")
    raw = getattr(getattr(row, "artifact", None), "sha256", None)
    if saved_raw and raw and raw != saved_raw:
        return "the assay's raw input file changed since this recipe was saved"
    now = recipe_core.source_fingerprint(layout)
    if rec.layout_fingerprint and now != rec.layout_fingerprint:
        return ("the plate layout or sample metadata changed since this recipe was saved, "
                "so re-running it would not reproduce the saved figure")
    spec = recipe_core.PRESETS.get(rec.preset) or {}
    if rec.schema_version != recipe_core.SCHEMA_VERSION:
        return f"this recipe was saved under schema version {rec.schema_version}"
    if spec.get("method") and (rec.source or {}).get("analysis_method") != spec["method"]:
        return "the analysis this preset runs has changed since this recipe was saved"
    if spec.get("method_version") and (rec.source or {}).get("analysis_method_version") != spec["method_version"]:
        return (f"this recipe was saved under analysis version {(rec.source or {}).get('analysis_method_version')}, "
                f"and that analysis is now version {spec['method_version']}")
    try:
        units = _validate_against_source(rec.config or {}, signals, layout)
    except ValueError as exc:
        return str(exc)
    for key in ("reporter_unit", "biomass_unit"):
        saved = (rec.source or {}).get(key)
        if saved and units.get(key) and saved != units[key]:
            return f"the {key.replace('_', ' ')} is {units[key]} now but {saved} when this recipe was saved"
    return ""


def _serialise(r: FigureRecipe, stale: str = "") -> dict:
    spec = recipe_core.PRESETS.get(r.preset, {})
    return {
        "id": r.id, "study_id": r.study_id, "assay_id": r.assay_id, "name": r.name,
        "preset": r.preset, "preset_label": spec.get("label", r.preset),
        "measurement": " ".join(x for x in (spec.get("measurement", ""), spec.get("caveat", "")) if x),
        "schema_version": r.schema_version, "config": r.config, "source": r.source,
        "layout_fingerprint": r.layout_fingerprint, "preview": r.preview,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "stale_reason": stale, "reproducible": not stale,
    }


@router.get("/presets")
def list_presets(user: User = Depends(current_user)):
    return {"presets": [{"key": k, **v, "needs": list(v["needs"])} for k, v in recipe_core.PRESETS.items()]}


@router.get("/studies/{study_id}/recipes")
def list_recipes(study_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.study(db, user, study_id, "viewer")
    rows = db.scalars(select(FigureRecipe).where(FigureRecipe.study_id == study_id).order_by(FigureRecipe.created_at)).all()
    # the same assessment as the single view, so the two surfaces cannot disagree
    return {"recipes": [_serialise(r, _staleness(db, user, r)) for r in rows]}


@router.post("/studies/{study_id}/recipes", status_code=201)
def create_recipe(study_id: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.study(db, user, study_id, "editor")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="a recipe needs a name")
    assay_id = body.get("assay_id")
    if not assay_id:
        raise HTTPException(status_code=422, detail="a recipe needs the assay it was built from")
    row = db.get(Assay, assay_id)
    if row is None or row.study_id != study_id:
        raise HTTPException(status_code=422, detail="that assay does not belong to this study")
    version = body.get("snapshot_version")
    captured = (body.get("source_fingerprint") or "").strip()
    if not captured:
        raise HTTPException(status_code=422, detail=(
            "a recipe must carry the source fingerprint the analysis returned, so run the figure again"))
    try:
        cfg = recipe_core.normalise_config(body.get("preset", ""), body.get("config") or {})
        signals, layout = _assay_source(db, user, assay_id, version)
        units = _validate_against_source(cfg, signals, layout)
        preview = recipe_core.normalise_preview(body.get("preview"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    spec = recipe_core.PRESETS[cfg["preset"]]
    # another tab or user can move a well between the analysis and this save, so the figure is
    # saved against the source it was computed from or not at all
    if captured != recipe_core.source_fingerprint(layout):
        raise HTTPException(status_code=422, detail=(
            "the plate layout or sample metadata changed after this figure was computed, "
            "so run it again before saving it"))
    for key, want in (("analysis_method", spec["method"]), ("analysis_method_version", spec["method_version"])):
        asserted = body.get(key)
        if asserted not in (None, "") and str(asserted) != str(want):
            raise HTTPException(status_code=422, detail=(
                f"this figure was computed by {key.replace('_', ' ')} {asserted!r}, and this preset "
                f"now runs {want!r}, so run it again before saving it"))
    source = {
        "study_id": study_id, "assay_id": assay_id, "snapshot_version": version,
        "raw_file_sha256": getattr(getattr(row, "artifact", None), "sha256", None),
        # derived here, never taken from the caller
        "analysis_method": spec["method"],
        "analysis_method_version": spec["method_version"],
        "reporter_unit": units["reporter_unit"], "biomass_unit": units["biomass_unit"],
    }
    if db.scalar(select(FigureRecipe).where(FigureRecipe.study_id == study_id, FigureRecipe.name == name)):
        raise HTTPException(status_code=409, detail=f"this study already has a recipe named {name!r}")
    rec = FigureRecipe(study_id=study_id, assay_id=assay_id, name=name, preset=cfg["preset"],
                       schema_version=cfg["schema_version"], config=cfg, source=source,
                       layout_fingerprint=captured,
                       preview=preview, created_by=user.id)
    db.add(rec)
    # recipes are published study content now, so saving one into a public study makes a version
    # through the existing mechanism, in the same transaction; the prior cited version is untouched
    from bob import versions
    db.flush()
    row = db.get(Assay, assay_id)
    versions.record(db, row.study, user, f"Saved figure recipe {name!r}")
    db.commit()
    db.refresh(rec)
    return _serialise(rec, _staleness(db, user, rec))


@router.get("/recipes/{recipe_id}")
def open_recipe(recipe_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = db.get(FigureRecipe, recipe_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="no such recipe")
    access.study(db, user, rec.study_id, "viewer")
    return _serialise(rec, _staleness(db, user, rec))


@router.get("/recipes/{recipe_id}/reuse")
def reuse_template(recipe_id: str, assay_id: str = Query(...),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A starting point for another assay: roles kept, identities and acknowledgement dropped."""
    rec = db.get(FigureRecipe, recipe_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="no such recipe")
    access.study(db, user, rec.study_id, "viewer")
    if db.get(Assay, assay_id) is None:
        raise HTTPException(status_code=404, detail="no such assay")
    access.assay(db, user, assay_id, "viewer")

    signals, layout = _assay_source(db, user, assay_id, None)
    names = {s.name: s for s in signals}
    template = recipe_core.for_reuse(rec.config or {})
    problems = []
    for key, kind in _CHANNEL_KIND.items():
        want = template.get(key)
        if not want:
            continue
        sig = names.get(want)
        if sig is None:
            problems.append(f"this assay has no channel named {want!r}; choose one")
            template[key] = None
        elif sig.kind != kind:
            problems.append(f"{want} reads {sig.kind} here, which cannot serve as the {key.split('_')[0]} channel")
            template[key] = None
        else:
            saved = (rec.source or {}).get(key.replace("_signal", "_unit"))
            if saved and sig.unit != saved:
                problems.append(f"{want} reads in {sig.unit} here but {saved} in the saved recipe; confirm the channel before running")
                template[key] = None
    by_type: dict[str, list] = {}
    for sample in layout.values():
        sid, st = getattr(sample, "id", None), getattr(sample, "sample_type", None)
        if sid and not any(s["id"] == sid for s in by_type.setdefault(st, [])):
            by_type[st].append({"id": sid, "name": getattr(sample, "name", sid)})
    for st, label in (("sample", "a sample"), ("medium", "a medium control"), ("untransformed", "an untransformed control")):
        if not by_type.get(st):
            problems.append(f"this assay has no {label} assigned in its plate map")
    return {
        "source_recipe": {"id": rec.id, "name": rec.name, "preset": rec.preset,
                          "assay_id": rec.assay_id, "snapshot_version": (rec.source or {}).get("snapshot_version")},
        "target_assay_id": assay_id,
        "template": template,
        "choices": by_type,
        "signals": [{"name": s.name, "unit": s.unit, "kind": s.kind} for s in signals],
        "problems": problems,
        "requires_fresh_acknowledgement": True,
    }
