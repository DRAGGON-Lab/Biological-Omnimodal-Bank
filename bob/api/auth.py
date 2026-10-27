from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from bob import services
from bob.api import serialize
from bob.ratelimit import LOGIN_FAILURES_PER_CLIENT, LOGIN_FAILURES_PER_EMAIL, SIGNUPS_PER_CLIENT, client_key
from bob.text import ShortName
from bob.models import ApiToken, Invitation, Membership, User, Workspace
from bob.security import current_user, get_db, hash_password, new_api_token, start_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY_HASH = hash_password("bob-timing-equalizer")


class SignupIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    name: ShortName
    password: str = Field(min_length=8, max_length=256)


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    name: ShortName | None = None
    current_password: str | None = None
    new_password: str | None = Field(None, min_length=8, max_length=256)
    revoke_tokens: bool = True


class TokenIn(BaseModel):
    name: ShortName


class AppLoginIn(BaseModel):
    email: str
    password: str
    app: ShortName = "API client"


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)):
    if not request.app.state.settings.allow_signup:
        raise HTTPException(403, "Sign-up is closed on this server. Ask an administrator for an account.")
    limiter, client = request.app.state.limiter, "signup:" + client_key(request)
    limiter.check(client, SIGNUPS_PER_CLIENT)
    limiter.record(client, SIGNUPS_PER_CLIENT)
    user, _ = services.create_user(db, body.email, body.name, body.password)
    db.commit()
    start_session(request, user)
    return {"user": serialize.user(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = _authenticate(body, request, db)
    start_session(request, user)
    return {"user": serialize.user(user)}


def _authenticate(body, request: Request, db: Session) -> User:
    email = body.email.strip().lower()
    limiter = request.app.state.limiter
    keys = (("login-email:" + email, LOGIN_FAILURES_PER_EMAIL), ("login-client:" + client_key(request), LOGIN_FAILURES_PER_CLIENT))
    for key, rule in keys:
        limiter.check(key, rule)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        # Spend the same hashing time as a real check, so response time does not reveal which emails exist.
        verify_password(_DUMMY_HASH, body.password)
    if user is None or not verify_password(user.password_hash, body.password):
        for key, rule in keys:
            limiter.record(key, rule)
        raise HTTPException(401, "Email or password is incorrect")
    return user


@router.post("/token", status_code=201)
def app_login(body: AppLoginIn, request: Request, db: Session = Depends(get_db)):
    """Sign-in for other apps, such as SynBioSuite: returns an API token, listed and revocable under Account settings."""
    user = _authenticate(body, request, db)
    token, digest = new_api_token()
    row = ApiToken(user_id=user.id, name=body.app.strip(), token_hash=digest)
    db.add(row)
    db.commit()
    return {"token": token, "token_id": row.id, "user": serialize.user(user)}


@router.post("/logout", status_code=204)
def logout(request: Request):
    request.session.clear()
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
def logout_everywhere(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.session_version += 1
    db.commit()
    request.session.clear()
    return Response(status_code=204)


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Workspace, Membership.role).join(Membership).where(Membership.user_id == user.id).order_by(Workspace.name)).all()
    pending = db.scalar(select(func.count()).select_from(Invitation).where(Invitation.email == user.email))
    return {
        "user": serialize.user(user),
        "workspaces": [{"id": w.id, "name": w.name, "slug": w.slug, "role": r} for w, r in rows],
        "invitations": pending,
    }


@router.patch("/me")
def update_me(body: ProfileIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip()
    if body.new_password is not None:
        if not body.current_password or not verify_password(user.password_hash, body.current_password):
            raise HTTPException(403, "Current password is incorrect")
        user.password_hash = hash_password(body.new_password)
        user.session_version += 1
        if body.revoke_tokens:
            db.execute(delete(ApiToken).where(ApiToken.user_id == user.id))
    db.commit()
    if body.new_password is not None and request.session:
        start_session(request, user)
    return {"user": serialize.user(user)}


@router.get("/tokens")
def list_tokens(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc()))
    return [serialize.token(t) for t in rows]


@router.post("/tokens", status_code=201)
def create_token(body: TokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    token, digest = new_api_token()
    row = ApiToken(user_id=user.id, name=body.name.strip(), token_hash=digest)
    db.add(row)
    db.commit()
    return {"id": row.id, "name": row.name, "token": token}


@router.delete("/tokens/{token_id}", status_code=204)
def delete_token(token_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Token not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
