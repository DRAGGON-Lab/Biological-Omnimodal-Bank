import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import access, recipes as recipe_core, isa_export, ro_crate, services, versions
from bob.api import serialize
from bob.text import IRI_PATTERN, Description, Label, Name, Orcid, RequiredText, ShortName
from bob.models import Investigation, Membership, Sample, Study, StudyEvent, StudyVersion, User, Workspace, now
from bob.sbol_export import export_study
from bob.security import current_user, get_db

router = APIRouter(prefix="/api", tags=["projects"])

VISIBILITY_MOVED = "Visibility is changed by publishing or withdrawing the study (POST /api/studies/{id}/publish or /withdraw)."
NEEDS_AUTHORS = "A published study needs at least one author, so it can be cited."
PUBLISHED_NO_DELETE = "This study has been published, so it cannot be deleted; readers may have cited it. Withdraw it instead."


class InvestigationIn(BaseModel):
    title: Name
    description: Description = ""


class InvestigationPatch(BaseModel):
    title: Name | None = None
    description: Description | None = None


class AuthorIn(BaseModel):
    given_name: ShortName
    family_name: Label = ""
    orcid: Orcid = ""
    affiliation: Label = ""


class StudyIn(BaseModel):
    title: Name
    description: Description = ""
    visibility: str | None = None


class StudyPatch(BaseModel):
    title: Name | None = None
    description: Description | None = None
    authors: list[AuthorIn] | None = Field(None, max_length=100)
    visibility: str | None = None


class PublishIn(BaseModel):
    license: Literal["CC-BY-4.0", "CC0-1.0"]
    authors: list[AuthorIn] | None = Field(None, max_length=100)


class WithdrawIn(BaseModel):
    reason: RequiredText


class ComponentIn(BaseModel):
    role: Literal["strain", "plasmid", "inducer", "supplement", "medium", "design", "other"] = "strain"
    # http(s) or urn only: SBOL export writes it as an RDF resource, and clients render it as a link.
    iri: str = Field("", max_length=1000, pattern=IRI_PATTERN)
    label: Label = ""
    amount: float | None = Field(None, ge=0, allow_inf_nan=False)
    unit: str | None = Field(None, max_length=40)
    sbol_version: str | None = Field(None, max_length=8)
    sbol_class: str | None = Field(None, max_length=60)


class SampleIn(BaseModel):
    name: Name
    sample_type: Literal["sample", "medium", "untransformed"] = "sample"
    description: Description = ""
    components: list[ComponentIn] = Field(default_factory=list, max_length=100)


class SamplePatch(BaseModel):
    name: Name | None = None
    sample_type: Literal["sample", "medium", "untransformed"] | None = None
    description: Description | None = None
    components: list[ComponentIn] | None = Field(None, max_length=100)


def _apply(obj, patch: BaseModel, skip: tuple = ()) -> None:
    for key, value in patch.model_dump(exclude_unset=True).items():
        if key not in skip and value is not None:
            setattr(obj, key, value.strip() if isinstance(value, str) else value)


def _released(st: Study) -> str:
    return serialize.iso(st.versions[0].created_at)[:10] if st.versions else ""


def _never_published(st: Study) -> None:
    # Publishing is one-way: a published study is public or withdrawn from then on.
    if st.visibility != "private":
        raise HTTPException(409, PUBLISHED_NO_DELETE)


@router.get("/workspaces/{workspace_id}/investigations")
def list_investigations(workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.workspace(db, user, workspace_id)
    rows = db.scalars(select(Investigation).where(Investigation.workspace_id == workspace_id).order_by(Investigation.created_at.desc()))
    return [serialize.investigation(i) for i in rows]


@router.post("/workspaces/{workspace_id}/investigations", status_code=201)
def create_investigation(workspace_id: str, body: InvestigationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.workspace(db, user, workspace_id, "editor")
    inv = Investigation(workspace_id=workspace_id, title=body.title.strip(), description=body.description.strip(), created_by=user.id)
    db.add(inv)
    db.commit()
    return serialize.investigation(inv)


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.investigation(access.investigation(db, user, investigation_id))


@router.patch("/investigations/{investigation_id}")
def update_investigation(investigation_id: str, body: InvestigationPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = access.investigation(db, user, investigation_id, "editor")
    _apply(inv, body)
    db.commit()
    return serialize.investigation(inv)


@router.delete("/investigations/{investigation_id}", status_code=204)
def delete_investigation(investigation_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = access.investigation(db, user, investigation_id, "editor")
    if any(st.visibility != "private" for st in inv.studies):
        raise HTTPException(409, "This investigation holds a published study, so it cannot be deleted. Withdraw the study instead.")
    db.delete(inv)
    db.commit()
    services.purge_unused_artifacts(db, request.app.state.settings)
    return Response(status_code=204)


@router.get("/investigations/{investigation_id}/studies")
def list_studies(investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = access.investigation(db, user, investigation_id)
    return [serialize.study(s) for s in sorted(inv.studies, key=lambda s: s.created_at, reverse=True)]


def _editable(user: User):
    return (
        select(Investigation, Workspace)
        .join(Workspace, Investigation.workspace_id == Workspace.id)
        .join(Membership, (Membership.workspace_id == Workspace.id) & (Membership.user_id == user.id))
        .where(Membership.role.in_(("owner", "editor")))
    )


@router.get("/investigations")
def my_investigations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Investigations the caller can add studies to, for apps that create studies in BOB."""
    rows = db.execute(_editable(user).order_by(Workspace.name, Investigation.title)).all()
    return [{**serialize.investigation(i), "workspace_name": w.name} for i, w in rows]


@router.get("/studies")
def my_studies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Studies the caller can add data to, for apps that send data to BOB."""
    rows = db.execute(
        _editable(user).add_columns(Study).join(Study, Study.investigation_id == Investigation.id).order_by(Workspace.name, Investigation.title, Study.title)
    ).all()
    return [{**serialize.study(s), "investigation_title": i.title, "workspace_name": w.name} for i, w, s in rows]


def _last_activity(s: Study):
    return max([s.created_at] + [a.created_at for a in s.assays] + [v.created_at for v in s.versions])


@router.get("/workspaces/{workspace_id}/overview")
def workspace_overview(workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Counts and the most recently active studies of a workspace, for the home page."""
    access.workspace(db, user, workspace_id)
    investigations = db.scalars(select(Investigation).where(Investigation.workspace_id == workspace_id)).all()
    studies = [s for inv in investigations for s in inv.studies]
    recent = sorted(studies, key=_last_activity, reverse=True)[:6]
    return {
        "investigations": len(investigations),
        "studies": len(studies),
        "samples": sum(len(s.samples) for s in studies),
        "assays": sum(len(s.assays) for s in studies),
        "published": sum(1 for s in studies if s.visibility == "public"),
        "recent": [{**serialize.study(s), "investigation_title": s.investigation.title, "last_activity": serialize.iso(_last_activity(s))} for s in recent],
    }


@router.get("/published")
def published_studies(limit: int = Query(20, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Studies published on this server, most recently versioned first. Public means readable by any signed-in user."""
    rows = db.scalars(select(Study).where(Study.visibility == "public")).all()
    rows = sorted(rows, key=lambda s: s.versions[-1].created_at if s.versions else s.created_at, reverse=True)[:limit]
    return [{**serialize.study(s), "version_created_at": serialize.iso(s.versions[-1].created_at) if s.versions else None} for s in rows]


@router.post("/investigations/{investigation_id}/studies", status_code=201)
def create_study(investigation_id: str, body: StudyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.visibility not in (None, "private"):
        raise HTTPException(422, "A new study starts private. " + VISIBILITY_MOVED)
    inv = access.investigation(db, user, investigation_id, "editor")
    st = Study(investigation_id=inv.id, title=body.title.strip(), description=body.description.strip())
    db.add(st)
    db.commit()
    db.refresh(st)
    return serialize.study(st)


@router.get("/studies/{study_id}")
def get_study(study_id: str, version: int | None = Query(None, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    if version is None:
        return serialize.study(st)
    return serialize.study_version(st, versions.get(db, st, version))


@router.patch("/studies/{study_id}")
def update_study(study_id: str, body: StudyPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.visibility is not None:
        raise HTTPException(422, VISIBILITY_MOVED)
    st = access.study(db, user, study_id, "editor")
    if body.authors is not None and not body.authors and st.visibility == "public":
        raise HTTPException(422, NEEDS_AUTHORS)
    versions.ensure_first(db, st)
    _apply(st, body, skip=("visibility",))
    versions.record(db, st, user, "Edited the study details")
    db.commit()
    return serialize.study(st)


@router.delete("/studies/{study_id}", status_code=204)
def delete_study(study_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id, "editor")
    _never_published(st)
    db.delete(st)
    db.commit()
    services.purge_unused_artifacts(db, request.app.state.settings)
    return Response(status_code=204)


@router.post("/studies/{study_id}/publish")
def publish_study(study_id: str, body: PublishIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id, "owner")
    if body.authors is not None:
        st.authors = [a.model_dump() for a in body.authors]
    if not st.authors:
        raise HTTPException(422, NEEDS_AUTHORS)
    versions.ensure_first(db, st)
    note = "Published" if not st.versions else ("License set" if st.visibility == "public" else "Published again")
    st.visibility, st.license = "public", body.license
    st.withdrawn_at, st.withdraw_reason = None, ""
    db.add(StudyEvent(study_id=st.id, kind="published", detail=body.license, user_id=user.id))
    versions.record(db, st, user, note)
    db.commit()
    db.refresh(st)
    return serialize.study(st)


@router.post("/studies/{study_id}/withdraw")
def withdraw_study(study_id: str, body: WithdrawIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id, "owner")
    if st.visibility != "public":
        raise HTTPException(409, "Only a public study can be withdrawn")
    versions.ensure_first(db, st)
    reason = body.reason.strip()
    st.visibility, st.withdrawn_at, st.withdraw_reason = "withdrawn", now(), reason
    db.add(StudyEvent(study_id=st.id, kind="withdrawn", detail=reason, user_id=user.id))
    db.commit()
    db.refresh(st)
    return serialize.study(st)


@router.get("/studies/{study_id}/versions")
def list_versions(study_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    versions.ensure_first(db, st)
    rows = db.scalars(select(StudyVersion).where(StudyVersion.study_id == st.id).order_by(StudyVersion.number.desc()))
    return [serialize.version(v) for v in rows]


@router.get("/studies/{study_id}/events")
def list_events(study_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    if access.role_in(db, user, access.study_workspace_id(st)) is None:
        raise HTTPException(403, "Only members of the study's workspace can see its publication record")
    rows = db.scalars(select(StudyEvent).where(StudyEvent.study_id == st.id).order_by(StudyEvent.created_at.desc()))
    return [serialize.event(e) for e in rows]


def _recipe_manifest_json(snap: dict) -> str:
    """The one payload the three export formats share, serialized deterministically."""
    return json.dumps(recipe_core.manifest_from_snapshot(snap), indent=2, ensure_ascii=False, sort_keys=True)


def _snapshot(db: Session, st: Study, version: int | None) -> tuple[dict, int | None]:
    """The requested version, or the live study; a live public study is its latest version."""
    if version is not None:
        return versions.get(db, st, version).snapshot, version
    latest = versions.latest(db, st) if st.visibility == "public" else None
    return versions.snapshot(db, st), latest.number if latest else None


@router.get("/studies/{study_id}/samples")
def list_samples(study_id: str, version: int | None = Query(None, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    if version is not None:
        return [serialize.snapshot_sample(s, st.id) for s in versions.get(db, st, version).snapshot["samples"]]
    return [serialize.sample(s) for s in sorted(st.samples, key=lambda s: (s.sample_type != "sample", s.name.lower()))]


@router.post("/studies/{study_id}/samples", status_code=201)
def create_sample(study_id: str, body: SampleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id, "editor")
    versions.ensure_first(db, st)
    s = Sample(study_id=st.id, name=body.name.strip(), sample_type=body.sample_type, description=body.description.strip())
    db.add(s)
    services.set_sample_components(s, [c.model_dump() for c in body.components])
    versions.record(db, st, user, f"Added sample {s.name}")
    db.commit()
    db.refresh(s)
    return serialize.sample(s)


@router.patch("/samples/{sample_id}")
def update_sample(sample_id: str, body: SamplePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = access.sample(db, user, sample_id, "editor")
    versions.ensure_first(db, s.study)
    _apply(s, body, skip=("components",))
    if body.components is not None:
        services.set_sample_components(s, [c.model_dump() for c in body.components])
    sample_id, name = s.id, s.name
    versions.record(db, s.study, user, f"Edited sample {name}")
    db.commit()
    return serialize.sample(db.get(Sample, sample_id))


@router.delete("/samples/{sample_id}", status_code=204)
def delete_sample(sample_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = access.sample(db, user, sample_id, "editor")
    st, name = s.study, s.name
    versions.ensure_first(db, st)
    db.delete(s)
    versions.record(db, st, user, f"Removed sample {name}")
    db.commit()
    return Response(status_code=204)


@router.get("/investigations/{investigation_id}/isa")
def investigation_isa(investigation_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = access.investigation(db, user, investigation_id)
    ws = db.get(Workspace, inv.workspace_id)
    base_iri = request.app.state.settings.base_iri
    blocks = []
    for st in inv.studies:
        snap, number = _snapshot(db, st, None)
        block = isa_export.study_block(snap, base_iri, _released(st), number)
        # each study carries its own manifest here too, so the aggregate export is not a
        # narrower record than the per-study one
        blocks.append(isa_export.with_recipe_manifest(block, _recipe_manifest_json(snap)))
    doc = isa_export.export_investigation(inv, ws.name, base_iri, blocks)
    filename = services.slugify(inv.title, "investigation")
    return JSONResponse(doc, headers={"Content-Disposition": f'attachment; filename="{filename}.isa.json"'})


@router.get("/studies/{study_id}/isa")
def study_isa(study_id: str, request: Request, version: int | None = Query(None, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    snap, number = _snapshot(db, st, version)
    block = isa_export.study_block(snap, request.app.state.settings.base_iri, _released(st), number)
    block = isa_export.with_recipe_manifest(block, _recipe_manifest_json(snap))
    doc = isa_export.export_study(block)
    filename = services.slugify(snap["study"]["title"], "study") + (f"-v{number}" if number else "")
    return JSONResponse(doc, headers={"Content-Disposition": f'attachment; filename="{filename}.isa.json"'})


@router.get("/studies/{study_id}/sbol")
def study_sbol(study_id: str, request: Request, version: int | None = Query(None, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    base_iri = request.app.state.settings.base_iri
    snap, number = _snapshot(db, st, version)
    text = export_study(services.study_record(snap, base_iri, number, _recipe_manifest_json(snap)), base_iri)
    filename = services.slugify(snap["study"]["title"], "study") + (f"-v{number}" if number else "")
    return Response(text, media_type="application/rdf+xml", headers={"Content-Disposition": f'attachment; filename="{filename}.sbol.xml"'})



@router.get("/studies/{study_id}/ro-crate")
def study_ro_crate(study_id: str, request: Request, version: int | None = Query(None, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    settings = request.app.state.settings
    snap, number = _snapshot(db, st, version)
    released = _released(st)
    slug = services.slugify(snap["study"]["title"], "study") + (f"-v{number}" if number else "")
    isa_name, sbol_name = f"{slug}.isa.json", f"{slug}.sbol.xml"
    recipe_name = f"{slug}.recipes.json"
    manifest_json = _recipe_manifest_json(snap)
    block = isa_export.with_recipe_manifest(
        isa_export.study_block(snap, settings.base_iri, released, number), manifest_json)
    isa = isa_export.export_study(block)
    sbol = export_study(services.study_record(snap, settings.base_iri, number, manifest_json), settings.base_iri)
    link = f"{settings.base_iri}/#/study/{st.id}" + (f"/v/{number}" if number else "")
    documents = {isa_name: json.dumps(isa, indent=2, ensure_ascii=False).encode(),
                 sbol_name: sbol.encode(), recipe_name: manifest_json.encode()}
    sizes = {name: len(data) for name, data in documents.items()}
    meta = ro_crate.metadata(snap, base_iri=settings.base_iri, released=released, created=now().date().isoformat(), version=number, link=link, documents=sizes)
    raw = {}
    for a in snap["assays"]:
        art = versions.artifact(db, a["raw_file"]["artifact_id"])
        path = settings.artifact_dir / art.storage_key
        if not path.exists():
            raise HTTPException(410, f"The raw file of assay {a['name']} is missing from storage")
        raw[f"assays/{a['id']}/dataset/{a['raw_file']['filename']}"] = path.read_bytes()
    data = ro_crate.package(meta, documents, raw)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{slug}.ro-crate.zip"'})
