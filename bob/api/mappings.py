import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bob import access, services
from bob.api import serialize
from bob.mappings import MappingSpec
from bob.mappings.builder import POSITION_STYLES, SIGNAL_KINDS, MappingForm, form_from_spec, to_spec
from bob.models import InstrumentMapping, Membership, MappingStar, User
from bob.security import current_user, get_db

router = APIRouter(prefix="/api", tags=["mappings"])


class MappingIn(BaseModel):
    spec: dict | None = None
    form: dict | None = None
    # saving a key the workspace already uses adds an immutable version; the form path makes the
    # caller say so, because the GUI shows which version it is about to create
    new_version: bool = False


def _spec_from_body(body: MappingIn) -> MappingSpec:
    if (body.spec is None) == (body.form is None):
        raise HTTPException(422, "Send either a mapping spec or the guided form, not both")
    try:
        if body.form is not None:
            return to_spec(MappingForm.model_validate(body.form))
        return MappingSpec.model_validate(body.spec)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise HTTPException(422, f"Mapping is not valid: {problems}") from exc
    except ValueError as exc:
        raise HTTPException(422, f"Mapping is not valid: {exc}") from exc


def _stars(db: Session, mapping_id: str, user: User) -> tuple[int, bool]:
    count = db.scalar(select(func.count()).select_from(MappingStar).where(MappingStar.mapping_id == mapping_id))
    mine = db.scalar(select(MappingStar.id).where(MappingStar.mapping_id == mapping_id, MappingStar.user_id == user.id))
    return count, mine is not None


@router.get("/mappings")
def list_mappings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    my_workspaces = select(Membership.workspace_id).where(Membership.user_id == user.id)
    rows = db.scalars(
        select(InstrumentMapping)
        .where(InstrumentMapping.workspace_id.is_(None) | InstrumentMapping.workspace_id.in_(my_workspaces))
        .order_by(InstrumentMapping.builtin.desc(), InstrumentMapping.name, InstrumentMapping.version.desc())
    )
    return [serialize.mapping(m, *_stars(db, m.id, user)) for m in rows]


@router.get("/mappings/{mapping_id}")
def get_mapping(mapping_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = access.visible_mapping(db, user, mapping_id)
    return serialize.mapping(m, *_stars(db, m.id, user), with_spec=True)


@router.post("/workspaces/{workspace_id}/mappings", status_code=201)
def create_mapping(workspace_id: str, body: MappingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.workspace(db, user, workspace_id, "editor")
    spec = _spec_from_body(body)
    existing = db.scalar(
        select(func.max(InstrumentMapping.version))
        .where(InstrumentMapping.workspace_id == workspace_id, InstrumentMapping.key == spec.key)
    )
    if existing and body.form is not None and not body.new_version:
        raise HTTPException(409, f"This workspace already has {spec.key!r} at version {existing}. "
                                f"Saving keeps that version and adds version {existing + 1}; "
                                f"confirm to continue, or change the identifier.")
    if db.scalar(select(InstrumentMapping.id).where(InstrumentMapping.builtin.is_(True), InstrumentMapping.key == spec.key)):
        raise HTTPException(409, f"The key {spec.key!r} belongs to a built-in mapping; choose another key for your copy")
    m = services.save_mapping(db, workspace_id, spec, user)
    db.commit()
    return serialize.mapping(m, 0, False, with_spec=True)


@router.post("/mappings/{mapping_id}/star")
def star(mapping_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = access.visible_mapping(db, user, mapping_id)
    if not _stars(db, m.id, user)[1]:
        db.add(MappingStar(mapping_id=m.id, user_id=user.id))
        db.commit()
    count, starred = _stars(db, m.id, user)
    return {"stars": count, "starred": starred}


@router.delete("/mappings/{mapping_id}/star")
def unstar(mapping_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = access.visible_mapping(db, user, mapping_id)
    row = db.scalar(select(MappingStar).where(MappingStar.mapping_id == m.id, MappingStar.user_id == user.id))
    if row:
        db.delete(row)
        db.commit()
    count, starred = _stars(db, m.id, user)
    return {"stars": count, "starred": starred}


@router.get("/mapping-form/options")
def mapping_form_options(user: User = Depends(current_user)):
    """What the guided form offers, so the GUI never hard-codes a pattern or a unit list."""
    return {
        "position_styles": [{"value": k, "label": label} for k, (_, label) in POSITION_STYLES.items()],
        "kinds": SIGNAL_KINDS,
        "units": {"absorbance": ["OD", "AU"], "fluorescence": ["RFU"], "luminescence": ["RLU"], "other": []},
        "formats": [{"value": "xlsx", "label": "Excel workbook (.xlsx)"},
                    {"value": "delimited", "label": "Text export (.txt or .csv, tab- or comma-separated)"}],
    }


@router.get("/mappings/{mapping_id}/form")
def mapping_as_form(mapping_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Read a mapping back into form answers so it can start a new one."""
    m = access.visible_mapping(db, user, mapping_id)
    spec = MappingSpec.model_validate(m.spec)
    return {"form": form_from_spec(spec).model_dump(mode="json"),
            "template_signal_rules": len(spec.signals),
            "advanced": _advanced_notes(spec)}


def _advanced_notes(spec: MappingSpec) -> list[str]:
    """Say plainly what the guided form cannot represent about this template."""
    notes = []
    if spec.source.sheet_pattern:
        notes.append("it picks its sheet by a name pattern, which the guided form does not offer")
    if len(spec.signals) > 1 and any(r.match == ".*" for r in spec.signals):
        notes.append("its channel rules include catch-all fallbacks; the guided form names each channel exactly")
    return notes


@router.post("/workspaces/{workspace_id}/mappings/preview")
async def preview_mapping(
    workspace_id: str,
    form: str = Form(None, description="The guided form as JSON"),
    spec: str = Form(None, description="A full mapping spec as JSON, for the advanced path"),
    file: UploadFile = File(..., description="One instrument export to check the mapping against"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Check a proposed mapping against a real file. Nothing is saved, and no assay or sample is written."""
    access.workspace(db, user, workspace_id, "editor")
    if (form is None) == (spec is None):
        raise HTTPException(422, "Send either the guided form or a mapping spec, not both")
    try:
        body = MappingIn(form=json.loads(form) if form else None, spec=json.loads(spec) if spec else None)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"The mapping is not valid JSON: {exc}") from exc
    proposed = _spec_from_body(body)
    data = await file.read()
    named = body.spec is not None or bool(json.loads(form).get("channels"))
    return services.preview_mapping(proposed, data, file.filename or "upload",
                                    label_has_optics="(?P<optics>" in proposed.blocks.label_pattern,
                                    channels_named=named)


@router.post("/mapping-form/spec")
def form_as_spec(body: MappingIn, user: User = Depends(current_user)):
    """The spec the guided form currently means, so the advanced editor opens on it rather than a stub."""
    if body.form is None:
        raise HTTPException(422, "Send the guided form")
    return {"spec": _spec_from_body(body).to_json()}
