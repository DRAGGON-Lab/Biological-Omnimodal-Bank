from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import access, services
from bob.api import serialize
from bob.text import ShortName
from bob.models import Artifact, Invitation, Investigation, Membership, Study, User, Workspace
from bob.security import current_user, get_db

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
invitations_router = APIRouter(prefix="/api/invitations", tags=["workspaces"])

Role = Literal["owner", "editor", "viewer"]


class WorkspaceIn(BaseModel):
    name: ShortName


class MemberIn(BaseModel):
    email: str = Field(pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$", max_length=254)
    role: Role = "viewer"


class RoleIn(BaseModel):
    role: Role


def _member(m: Membership) -> dict:
    return {"user_id": m.user_id, "email": m.user.email, "name": m.user.name, "role": m.role}


@router.get("")
def list_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Workspace, Membership.role).join(Membership).where(Membership.user_id == user.id).order_by(Workspace.name)).all()
    return [serialize.workspace(w, r) for w, r in rows]


@router.post("", status_code=201)
def create_workspace(body: WorkspaceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = services.create_workspace(db, user, body.name)
    db.commit()
    return serialize.workspace(ws, "owner")


@router.patch("/{workspace_id}")
def rename_workspace(workspace_id: str, body: WorkspaceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = access.workspace(db, user, workspace_id, "owner")
    ws.name = body.name.strip()
    db.commit()
    return serialize.workspace(ws, "owner")


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = access.workspace(db, user, workspace_id, "owner")
    published = select(Study.id).join(Investigation).where(Investigation.workspace_id == workspace_id, Study.visibility != "private")
    if db.scalar(published.limit(1)):
        raise HTTPException(409, "This workspace holds a published study, so it cannot be deleted. Withdraw the study instead; it stays here so its readers find the withdrawal notice.")
    keys = set(db.scalars(select(Artifact.storage_key).where(Artifact.workspace_id == workspace_id)))
    db.delete(ws)
    db.commit()
    services.purge_unused_artifacts(db, request.app.state.settings, keys)
    return Response(status_code=204)


@router.get("/{workspace_id}/members")
def list_members(workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.workspace(db, user, workspace_id)
    rows = db.scalars(select(Membership).where(Membership.workspace_id == workspace_id))
    return sorted((_member(m) for m in rows), key=lambda m: (m["role"] != "owner", m["name"].lower()))


def _invitation(i: Invitation) -> dict:
    return {
        "id": i.id,
        "workspace_id": i.workspace_id,
        "workspace_name": i.workspace.name,
        "email": i.email,
        "role": i.role,
        "invited_by": i.inviter.name if i.inviter else None,
        "created_at": serialize.iso(i.created_at),
    }


@router.get("/{workspace_id}/invitations")
def list_invitations(workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.workspace(db, user, workspace_id, "owner")
    rows = db.scalars(select(Invitation).where(Invitation.workspace_id == workspace_id).order_by(Invitation.created_at))
    return [_invitation(i) for i in rows]


@router.post("/{workspace_id}/invitations", status_code=202)
def invite(workspace_id: str, body: MemberIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The answer is the same whether or not an account uses the email, so it cannot be used to look up accounts."""
    access.workspace(db, user, workspace_id, "owner")
    email = body.email.strip().lower()
    member = db.scalar(select(Membership).join(User).where(Membership.workspace_id == workspace_id, User.email == email))
    if member is not None:
        raise HTTPException(409, "That person is already a member")
    inv = db.scalar(select(Invitation).where(Invitation.workspace_id == workspace_id, Invitation.email == email))
    if inv is None:
        inv = Invitation(workspace_id=workspace_id, email=email, role=body.role, invited_by=user.id)
        db.add(inv)
    else:
        inv.role, inv.invited_by = body.role, user.id
    db.commit()
    return _invitation(inv)


@router.delete("/{workspace_id}/invitations/{invitation_id}", status_code=204)
def cancel_invitation(workspace_id: str, invitation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.workspace(db, user, workspace_id, "owner")
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.workspace_id != workspace_id:
        raise HTTPException(404, "Invitation not found")
    db.delete(inv)
    db.commit()
    return Response(status_code=204)


def _membership(db: Session, workspace_id: str, user_id: str) -> Membership:
    m = db.scalar(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id))
    if m is None:
        raise HTTPException(404, "Member not found")
    return m


@router.patch("/{workspace_id}/members/{user_id}")
def change_role(workspace_id: str, user_id: str, body: RoleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access.workspace(db, user, workspace_id, "owner")
    m = _membership(db, workspace_id, user_id)
    if m.role == "owner" and body.role != "owner" and services.owner_count(db, workspace_id) == 1:
        raise HTTPException(409, "A workspace needs at least one owner")
    m.role = body.role
    db.commit()
    return _member(m)


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need = "viewer" if user_id == user.id else "owner"
    access.workspace(db, user, workspace_id, need)
    m = _membership(db, workspace_id, user_id)
    if m.role == "owner" and services.owner_count(db, workspace_id) == 1:
        raise HTTPException(409, "A workspace needs at least one owner")
    db.delete(m)
    db.commit()
    return Response(status_code=204)


def _my_invitation(db: Session, user: User, invitation_id: str) -> Invitation:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.email != user.email:
        raise HTTPException(404, "Invitation not found")
    return inv


@invitations_router.get("")
def my_invitations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Invitation).where(Invitation.email == user.email).order_by(Invitation.created_at))
    return [_invitation(i) for i in rows]


@invitations_router.post("/{invitation_id}/accept")
def accept_invitation(invitation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = _my_invitation(db, user, invitation_id)
    ws, role = inv.workspace, inv.role
    if not access.role_in(db, user, ws.id):
        db.add(Membership(workspace_id=ws.id, user_id=user.id, role=role))
    db.delete(inv)
    db.commit()
    return serialize.workspace(ws, access.role_in(db, user, ws.id))


@invitations_router.post("/{invitation_id}/decline", status_code=204)
def decline_invitation(invitation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_my_invitation(db, user, invitation_id))
    db.commit()
    return Response(status_code=204)
