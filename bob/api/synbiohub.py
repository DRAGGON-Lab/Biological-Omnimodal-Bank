from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import access, services, synbiohub, versions
from bob.models import RemoteAccount, StudyEvent, User
from bob.sbol_export import export_study
from bob.security import current_user, get_db

router = APIRouter(prefix="/api", tags=["synbiohub"])
SERVICE = "synbiohub"


class LoginIn(BaseModel):
    instance: str
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class InstanceIn(BaseModel):
    instance: str


class UploadIn(BaseModel):
    instance: str
    collection: str | None = Field(None, max_length=1000, description="An existing collection's URI; a new collection for the study when omitted")
    overwrite: bool = False


def _instance(request: Request, url: str) -> str:
    url = url.strip().rstrip("/")
    if url not in request.app.state.settings.synbiohub_instances:
        raise HTTPException(422, f"{url} is not a SynBioHub this BOB server is set up to use")
    return url


def _account(db: Session, user: User, instance: str) -> RemoteAccount | None:
    return db.scalar(select(RemoteAccount).where(RemoteAccount.user_id == user.id, RemoteAccount.service == SERVICE, RemoteAccount.instance == instance))


def stored_token(request: Request, db: Session, user: User, instance: str) -> str | None:
    acct = _account(db, user, instance)
    return synbiohub.unseal(request.app.state.settings.secret_key, acct.secret) if acct else None


def _token(request: Request, db: Session, user: User, instance: str, required: bool = True) -> str | None:
    token = stored_token(request, db, user, instance)
    if token is None and required:
        raise HTTPException(409, f"Sign in to SynBioHub at {instance} first (Account settings).")
    return token


def _call(fn, *args, **kw):
    """SynBioHub's own refusals become 502, never 401, which would sign the user out of BOB."""
    try:
        return fn(*args, **kw)
    except synbiohub.SynBioHubError as exc:
        raise HTTPException(400 if exc.status == 401 else 502, str(exc)) from exc


@router.get("/synbiohub")
def status(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for instance in request.app.state.settings.synbiohub_instances:
        acct = _account(db, user, instance)
        usable = acct is not None and synbiohub.unseal(request.app.state.settings.secret_key, acct.secret) is not None
        out.append({"instance": instance, "signed_in": usable, "username": acct.username if usable else None})
    return {"instances": out}


@router.post("/synbiohub/login")
def login(body: LoginIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    instance = _instance(request, body.instance)
    token = _call(synbiohub.login, instance, body.email.strip(), body.password)
    acct = _account(db, user, instance) or RemoteAccount(user_id=user.id, service=SERVICE, instance=instance)
    acct.username, acct.secret = body.email.strip(), synbiohub.seal(request.app.state.settings.secret_key, token)
    db.add(acct)
    db.commit()
    return {"instance": instance, "signed_in": True, "username": acct.username}


@router.post("/synbiohub/logout", status_code=204)
def logout(body: InstanceIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    acct = _account(db, user, _instance(request, body.instance))
    if acct:
        db.delete(acct)
        db.commit()
    return Response(status_code=204)


@router.get("/synbiohub/search")
def search(request: Request, instance: str, q: str = Query(..., min_length=1, max_length=200), user: User = Depends(current_user), db: Session = Depends(get_db)):
    instance = _instance(request, instance)
    return _call(synbiohub.search, instance, _token(request, db, user, instance, required=False), q)


@router.get("/synbiohub/resolve")
def resolve(request: Request, iri: str = Query(..., max_length=1000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    instance = next((i for i in request.app.state.settings.synbiohub_instances if iri.startswith(i + "/")), None)
    if instance is None:
        raise HTTPException(422, "That IRI is not on a SynBioHub this BOB server is set up to use")
    found = _call(synbiohub.metadata, iri, _token(request, db, user, instance, required=False))
    if found is None:
        raise HTTPException(404, "SynBioHub has no design at that IRI")
    return found


@router.get("/synbiohub/collections")
def list_collections(request: Request, instance: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    instance = _instance(request, instance)
    return _call(synbiohub.collections, instance, _token(request, db, user, instance))


@router.post("/studies/{study_id}/synbiohub")
def upload_study(study_id: str, body: UploadIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = access.study(db, user, study_id)
    if access.role_in(db, user, access.study_workspace_id(st)) is None:
        raise HTTPException(403, "Only members of the study's workspace can send it to SynBioHub. Download its SBOL instead.")
    instance = _instance(request, body.instance)
    token = _token(request, db, user, instance)
    settings = request.app.state.settings
    latest = versions.latest(db, st) if st.visibility == "public" else None
    number = latest.number if latest else None
    snap = latest.snapshot if latest else versions.snapshot(db, st)
    sbol = export_study(services.study_record(snap, settings.base_iri, number), settings.base_iri).encode("utf-8")
    filename = services.slugify(st.title, "study") + ".sbol.xml"
    if body.collection:
        if not body.collection.startswith(instance + "/"):
            raise HTTPException(422, "That collection is not on the chosen SynBioHub")
        try:
            synbiohub.submit(instance, token, sbol, filename, root_collection=body.collection, overwrite=body.overwrite)
        except synbiohub.SynBioHubError as exc:
            if exc.status == 400 and "already" in str(exc):
                raise HTTPException(409, "Parts of this study are already in that collection with different content. Choose to replace them.") from exc
            raise HTTPException(400 if exc.status == 401 else 502, str(exc)) from exc
        target = body.collection
    else:
        # A study never published goes up as version 0, so it cannot be mistaken for a published version.
        cid, version = f"bob_{st.id}", str(number or 0)
        try:
            synbiohub.submit(instance, token, sbol, filename, collection_id=cid, version=version, name=st.title, description=st.description, overwrite=body.overwrite)
        except synbiohub.SynBioHubError as exc:
            if exc.status == 400 and "already in use" in str(exc):
                raise HTTPException(409, f"Version {version} of this study is already on SynBioHub. Choose to replace it, or save a new version first.") from exc
            raise HTTPException(400 if exc.status == 401 else 502, str(exc)) from exc
        owner = _account(db, user, instance).username
        target = next((c["uri"] for c in _call(synbiohub.collections, instance, token) if c["display_id"] == f"{cid}_collection" and c["version"] == version), None)
        target = target or f"{instance} (collection {cid}, version {version}, account {owner})"
    db.add(StudyEvent(study_id=st.id, kind="synbiohub", detail=target, user_id=user.id))
    db.commit()
    return {"instance": instance, "collection": target, "version": number}

