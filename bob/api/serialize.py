import datetime as dt

from bob.models import LICENSES, ApiToken, Assay, InstrumentMapping, Investigation, Sample, Study, StudyEvent, StudyVersion, User, Workspace


def iso(value: dt.datetime | None) -> str | None:
    """SQLite hands back naive datetimes; every stored time is UTC, so say so explicitly."""
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)).isoformat()


def user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "created_at": iso(u.created_at)}


def workspace(w: Workspace, role: str | None) -> dict:
    return {"id": w.id, "name": w.name, "slug": w.slug, "role": role, "created_at": iso(w.created_at)}


def token(t: ApiToken) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "created_at": iso(t.created_at),
        "last_used_at": iso(t.last_used_at),
    }


def investigation(i: Investigation) -> dict:
    return {
        "id": i.id,
        "workspace_id": i.workspace_id,
        "title": i.title,
        "description": i.description,
        "created_at": iso(i.created_at),
        "study_count": len(i.studies),
    }


def study(s: Study) -> dict:
    last = s.versions[-1] if s.versions else None
    return {
        "id": s.id,
        "investigation_id": s.investigation_id,
        "workspace_id": s.investigation.workspace_id,
        "title": s.title,
        "description": s.description,
        "visibility": s.visibility,
        "license": s.license,
        "license_url": LICENSES.get(s.license),
        "authors": s.authors or [],
        "published_at": iso(s.versions[0].created_at) if s.versions else None,
        "withdrawn_at": iso(s.withdrawn_at),
        "withdraw_reason": s.withdraw_reason or "",
        "version": None,
        "latest_version": last.number if last else None,
        "created_at": iso(s.created_at),
        "assay_count": len(s.assays),
        "sample_count": len(s.samples),
    }


def study_version(s: Study, v: StudyVersion) -> dict:
    """A study as it was in version `v`; visibility and withdrawal are the study's current state."""
    snap = v.snapshot["study"]
    out = study(s)
    out.update(
        title=snap["title"],
        description=snap["description"],
        license=snap.get("license"),
        license_url=LICENSES.get(snap.get("license")),
        authors=snap.get("authors", []),
        version=v.number,
        version_note=v.note,
        version_created_at=iso(v.created_at),
        assay_count=len(v.snapshot["assays"]),
        sample_count=len(v.snapshot["samples"]),
    )
    return out


def version(v: StudyVersion) -> dict:
    return {"number": v.number, "note": v.note, "created_at": iso(v.created_at), "author": v.author.name if v.author else None}


def event(e: StudyEvent) -> dict:
    return {"kind": e.kind, "detail": e.detail, "user": e.user.name if e.user else None, "created_at": iso(e.created_at)}


def snapshot_sample(s: dict, study_id: str) -> dict:
    return {
        "id": s["id"],
        "study_id": study_id,
        "name": s["name"],
        "sample_type": s["sample_type"],
        "description": s["description"],
        "components": [{"id": None, "amount": None, "unit": None, **c} for c in s["components"]],
    }


def snapshot_assay(a: dict, study_id: str, number: int) -> dict:
    raw = a["raw_file"]
    return {
        "id": a["id"],
        "study_id": study_id,
        "name": a["name"],
        "modality": a["modality"],
        "mapping_key": a["mapping_key"],
        "mapping_version": a["mapping_version"],
        "mapping_name": a["mapping_name"],
        "run_metadata": a["run_metadata"],
        "raw_file": {"filename": raw["filename"], "sha256": raw["sha256"], "size": raw["size"], "url": f"/api/assays/{a['id']}/raw?version={number}"},
        "signals": [{"name": s["name"], "kind": s["kind"], "unit": s["unit"], "description": s.get("description", ""), "color": s.get("color", ""),
                     "optics": s["optics"], "n_times": s["n_times"]} for s in a["signals"]],
        "positions": a["positions"],
        "warnings": a["warnings"],
        "created_at": a["created_at"],
        "version": number,
    }


def sample(s: Sample) -> dict:
    return {
        "id": s.id,
        "study_id": s.study_id,
        "name": s.name,
        "sample_type": s.sample_type,
        "description": s.description,
        "components": [
            {"id": c.id, "role": c.role, "iri": c.iri, "label": c.label, "amount": c.amount, "unit": c.unit, "sbol_version": c.sbol_version, "sbol_class": c.sbol_class}
            for c in s.components
        ],
    }


def assay(a: Assay, mapping_name: str | None = None) -> dict:
    return {
        "id": a.id,
        "study_id": a.study_id,
        "name": a.name,
        "modality": a.modality,
        "mapping_key": a.mapping_key,
        "mapping_version": a.mapping_version,
        "mapping_name": mapping_name or a.mapping_key,
        "run_metadata": a.run_metadata or {},
        "raw_file": {
            "filename": a.artifact.filename,
            "sha256": a.artifact.sha256,
            "size": a.artifact.size,
            "url": f"/api/assays/{a.id}/raw",
        },
        "signals": [{"name": s.name, "kind": s.kind, "unit": s.unit, "description": s.description, "color": s.color, "optics": s.optics, "n_times": len(s.times)}
                    for s in a.signals],
        "positions": sorted((w.position for w in a.wells), key=lambda p: (p[0], int(p[1:]) if p[1:].isdigit() else 0)),
        "warnings": a.warnings or [],
        "created_at": iso(a.created_at),
    }


def mapping(m: InstrumentMapping, stars: int, starred: bool, with_spec: bool = False) -> dict:
    out = {
        "id": m.id,
        "key": m.key,
        "version": m.version,
        "name": m.name,
        "emoji": m.emoji,
        "modality": m.modality,
        "description": m.description,
        "source_format": (m.spec or {}).get("source", {}).get("format", "xlsx"),
        "builtin": m.builtin,
        "workspace_id": m.workspace_id,
        "stars": stars,
        "starred": starred,
    }
    if with_spec:
        out["spec"] = m.spec
    return out
