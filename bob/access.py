"""Every data lookup goes through here, so no route can reach a record without a role check.

Records outside the caller's workspaces answer 404, not 403, so their existence does not leak.
"""

import datetime as dt

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bob.models import Assay, InstrumentMapping, Investigation, Membership, Sample, Study, User, Workspace

RANK = {"viewer": 1, "editor": 2, "owner": 3}


def role_in(db: Session, user: User, workspace_id: str) -> str | None:
    return db.scalar(select(Membership.role).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id))


def _check(role: str | None, need: str, what: str) -> None:
    if role is None:
        raise HTTPException(404, f"{what} not found")
    if RANK[role] < RANK[need]:
        raise HTTPException(403, f"This needs the {need} role in the workspace; you are a {role}")


def workspace(db: Session, user: User, workspace_id: str, need: str = "viewer") -> Workspace:
    ws = db.get(Workspace, workspace_id)
    _check(role_in(db, user, workspace_id) if ws else None, need, "Workspace")
    return ws


def investigation(db: Session, user: User, investigation_id: str, need: str = "viewer") -> Investigation:
    inv = db.get(Investigation, investigation_id)
    _check(role_in(db, user, inv.workspace_id) if inv else None, need, "Investigation")
    return inv


def study_workspace_id(study: Study) -> str:
    return study.investigation.workspace_id


def study(db: Session, user: User, study_id: str, need: str = "viewer") -> Study:
    st = db.get(Study, study_id)
    if st is None:
        raise HTTPException(404, "Study not found")
    role = role_in(db, user, study_workspace_id(st))
    if need == "viewer" and role is None and st.visibility == "public":
        return st
    if role is None and st.visibility == "withdrawn":
        # A published study never just disappears: readers who follow a citation learn what happened.
        raise HTTPException(410, {"message": "This study was withdrawn.", "withdrawn": withdrawal(st)})
    _check(role, need, "Study")
    return st


def withdrawal(st: Study) -> dict:
    at = st.withdrawn_at
    return {
        "title": st.title,
        "withdrawn_at": (at if at.tzinfo else at.replace(tzinfo=dt.timezone.utc)).isoformat() if at else None,
        "reason": st.withdraw_reason,
        "versions": len(st.versions),
    }


def assay(db: Session, user: User, assay_id: str, need: str = "viewer") -> Assay:
    a = db.get(Assay, assay_id)
    if a is None:
        raise HTTPException(404, "Assay not found")
    study(db, user, a.study_id, need)
    return a


def sample(db: Session, user: User, sample_id: str, need: str = "viewer") -> Sample:
    s = db.get(Sample, sample_id)
    if s is None:
        raise HTTPException(404, "Sample not found")
    study(db, user, s.study_id, need)
    return s


def visible_mapping(db: Session, user: User, mapping_id: str) -> InstrumentMapping:
    m = db.get(InstrumentMapping, mapping_id)
    if m is None or (m.workspace_id and role_in(db, user, m.workspace_id) is None):
        raise HTTPException(404, "Mapping not found")
    return m
