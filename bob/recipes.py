"""Named plotting presets and the study-linked figure recipes that save their selections."""

from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = 1

PRESETS: dict[str, dict] = {
    "growth_curve": {
        "method_version": "1",
        "method": "series-background-corrected",
        "label": "Growth curve",
        "measurement": "Biomass signal over time, background corrected against medium-only wells.",
        "caveat": "",
        "needs": ("biomass_signal", "sample_id", "biomass_control_id"),
    },
    "reporter_trajectory": {
        "method_version": "1",
        "method": "series-raw-and-corrected",
        "label": "Reporter trajectory",
        "measurement": "Reporter signal over time. Raw and background-corrected traces are shown distinctly.",
        "caveat": "",
        "needs": ("reporter_signal", "sample_id", "reporter_control_id"),
    },
    "reporter_per_biomass": {
        "method_version": "2",
        "method": "series-ratio",
        "label": "Reporter per biomass",
        "measurement": "Background-corrected reporter divided by the chosen biomass proxy.",
        "caveat": "A ratio, not a production rate and not molecules per cell.",
        "needs": ("reporter_signal", "biomass_signal", "sample_id", "biomass_control_id", "reporter_control_id"),
    },
    "rate_profiles": {
        "method_version": "1",
        "method": "gaussian-basis-inverse",
        "label": "Growth and production profiles",
        "measurement": "Growth rate and a reporter-production proxy from the Gaussian-basis inverse model.",
        "caveat": "Not the direct estimator used in the tutorials.",
        "needs": ("reporter_signal", "biomass_signal", "sample_id", "biomass_control_id", "reporter_control_id"),
    },
    "mean_over_run": {
        "method_version": "1",
        "method": "mean-over-run",
        "label": "Mean over run",
        "measurement": "Arithmetic mean of the retained background-corrected readings over the run.",
        "caveat": "Not an endpoint, not a growth rate, not a time-weighted mean.",
        "needs": ("reporter_signal", "sample_id", "reporter_control_id"),
    },
}

_SELECTION_KEYS = (
    "reporter_signal", "biomass_signal", "sample_id", "biomass_control_id", "reporter_control_id",
    "correct", "normalize_by", "min_od", "threshold_sd", "drop_below", "delta", "gamma", "lam",
)
# identity is per assay, and an acknowledgement is about one set of wells, so neither travels
_NOT_REUSABLE = ("sample_id", "biomass_control_id", "reporter_control_id")


def layout_fingerprint(layout: dict) -> str:
    """Hash the sample identity, type and chemical context of every assigned well."""
    rows = []
    for pos in sorted(layout):
        entry = layout[pos] or {}
        comps = sorted(tuple(c) for c in entry.get("components") or [])
        rows.append([pos, entry.get("sample_id"), entry.get("sample_name"), entry.get("sample_type"), comps])
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def source_fingerprint(layout: dict) -> str:
    """Fingerprint a layout of resolved sample objects, as the API surfaces receive it."""
    rows = {}
    for pos, sample in layout.items():
        rows[pos] = {
            "sample_id": getattr(sample, "id", None),
            "sample_name": getattr(sample, "name", None),
            "sample_type": getattr(sample, "sample_type", None),
            "components": [(c.role, c.iri, c.amount, c.unit, getattr(c, "label", ""))
                           for c in getattr(sample, "components", [])],
        }
    return layout_fingerprint(rows)


def normalise_config(preset: str, raw: dict) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    cfg: dict = {"preset": preset, "schema_version": SCHEMA_VERSION}
    for k in _SELECTION_KEYS:
        if raw.get(k) not in (None, ""):
            cfg[k] = raw[k]
    missing = [n for n in PRESETS[preset]["needs"] if cfg.get(n) in (None, "")]
    if missing:
        raise ValueError(f"{PRESETS[preset]['label']} needs {', '.join(missing)}")
    return cfg


def for_reuse(cfg: dict) -> dict:
    out = {k: v for k, v in cfg.items() if k not in _NOT_REUSABLE}
    out["schema_version"] = SCHEMA_VERSION
    return out


MAX_PREVIEW_POINTS = 40
MAX_PREVIEW_SERIES = 4


def normalise_preview(raw) -> str:
    """Accept only downsampled numeric series, never markup, since a preview is rendered in a page."""
    import json as _json
    if raw in (None, ""):
        return ""
    if isinstance(raw, str):
        if raw.lstrip()[:1] == "<":
            raise ValueError("a preview must be numeric series, not markup")
        try:
            raw = _json.loads(raw)
        except ValueError:
            raise ValueError("a preview must be JSON series data")
    if not isinstance(raw, list) or len(raw) > MAX_PREVIEW_SERIES:
        raise ValueError(f"a preview holds at most {MAX_PREVIEW_SERIES} series")
    out = []
    for s in raw:
        if not isinstance(s, dict):
            raise ValueError("each preview series is an object")
        xs, ys = s.get("x") or [], s.get("y") or []
        if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys):
            raise ValueError("preview x and y must be equal-length lists")
        if len(xs) > MAX_PREVIEW_POINTS:
            raise ValueError(f"a preview series holds at most {MAX_PREVIEW_POINTS} points")
        for v in list(xs) + list(ys):
            if v is not None and not isinstance(v, (int, float)):
                raise ValueError("preview points must be numbers or null")
        out.append({"label": str(s.get("label", ""))[:60], "x": xs, "y": ys})
    return _json.dumps(out)


MANIFEST_FORMAT = "bob-recipe-manifest/1"
PREVIEW_NOTE = ("A stored numeric preview of what the configuration produced when it was saved. "
                "It is not an analysis result, not a verified measurement and not evidence of "
                "biological replication.")
MANIFEST_NOTE = ("Saved analysis configuration linked to a recorded input state. It is not a "
                 "wet-lab assay, a re-executed analysis or proof of biological replication.")
NOT_CAPTURED_NOTE = ("This version was published before BOB captured analysis configuration, so no "
                     "recipe inventory was recorded. This is not a verified statement that the "
                     "study had no saved recipes at the time.")


def stored_entry(rec, status: dict) -> dict:
    """The recipe fields a snapshot freezes, including the assessment made at that moment.

    The status is passed in rather than computed here, because it must be assessed against the
    source the recipe names, which may be an earlier published version than the one being written.
    Nothing here reads a clock, so snapshot equality cannot drift on its own and manufacture a
    version on a no-op edit.
    """
    spec = PRESETS.get(rec.preset) or {}
    return {
        "id": rec.id,
        "name": rec.name,
        "preset": rec.preset,
        "preset_label": spec.get("label", ""),
        "measurement": " ".join(x for x in (spec.get("measurement", ""), spec.get("caveat", "")) if x),
        "schema_version": rec.schema_version,
        "analysis_method": (rec.source or {}).get("analysis_method", ""),
        "analysis_method_version": (rec.source or {}).get("analysis_method_version", ""),
        "config": dict(rec.config or {}),
        # the source references: which assay and version, its raw bytes and the units recorded
        "source": {k: v for k, v in (rec.source or {}).items()
                   if k not in ("analysis_method", "analysis_method_version")},
        "layout_fingerprint": rec.layout_fingerprint or "",
        "preview": rec.preview or "",
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        "source_status": status,
    }


def _check(ok, reason: str = "") -> dict:
    """One check. `ok` is True, False, or None for not checked, which is never read as verified."""
    return {"ok": ok, "reason": reason}


NOT_CHECKED = "not checked in this assessment"


def assess(entry: dict, *, scope: str, source: dict | None, problem: str = "") -> dict:
    """The same checks `_staleness` makes, recorded one by one with their outcome.

    `source` carries what the resolved source actually holds: its layout fingerprint, raw-file
    digest and channel units. Each check is reported separately so nothing a check did not look at
    is implied to have been verified. The result is frozen into the snapshot.
    """
    rec_src = entry.get("source") or {}
    checks: dict[str, dict] = {}
    if problem or source is None:
        checks["source_resolved"] = _check(False, problem or "the recorded source could not be resolved")
        for name in ("raw_file_sha256", "layout_fingerprint", "units",
                     "recipe_schema_version", "analysis_method", "analysis_method_version"):
            checks[name] = _check(None, NOT_CHECKED)
        return _verdict(scope, checks)

    checks["source_resolved"] = _check(True)

    saved_raw, now_raw = rec_src.get("raw_file_sha256"), source.get("raw_file_sha256")
    if saved_raw and now_raw:
        checks["raw_file_sha256"] = _check(saved_raw == now_raw, "" if saved_raw == now_raw else
                                           "the raw input file of the recorded source differs from "
                                           "the one this recipe was saved against")
    else:
        checks["raw_file_sha256"] = _check(None, NOT_CHECKED)

    saved_fp, now_fp = entry.get("layout_fingerprint") or "", source.get("layout_fingerprint")
    if saved_fp and now_fp:
        same = saved_fp == now_fp
        checks["layout_fingerprint"] = _check(same, "" if same else
                                              "the plate layout or sample metadata of the recorded "
                                              "source differs from the state this recipe was saved against")
    else:
        checks["layout_fingerprint"] = _check(None, "this recipe records no layout fingerprint"
                                              if not saved_fp else NOT_CHECKED)

    # the units of the channels this recipe actually selected, resolved by name. Taking the first
    # channel of a kind compares against the wrong one when a plate carries two of them.
    cfg = entry.get("config") or {}
    channel_units = source.get("channel_units")
    unit_pairs = (("reporter_signal", "reporter_unit"), ("biomass_signal", "biomass_unit"))
    selected = [(cfg.get(ch), rec_src.get(unit)) for ch, unit in unit_pairs if cfg.get(ch)]
    if not selected:
        checks["units"] = _check(None, "this recipe selects no named channel")
    elif channel_units is None:
        checks["units"] = _check(None, NOT_CHECKED + ": the recorded source lists no channels")
    else:
        failures, unchecked = [], []
        for name, saved in selected:
            if name not in channel_units:
                failures.append(f"the recorded channel {name!r} is not present in the recorded source")
            elif not saved:
                unchecked.append(f"this recipe records no unit for {name!r}")
            elif channel_units[name] != saved:
                failures.append(f"{name!r} reads {channel_units[name]} in the recorded source but "
                                f"{saved} when this recipe was saved")
        if failures:
            checks["units"] = _check(False, "; ".join(failures))
        elif unchecked:
            checks["units"] = _check(None, "; ".join(unchecked))
        else:
            checks["units"] = _check(True)

    schema_ok = entry.get("schema_version") == SCHEMA_VERSION
    checks["recipe_schema_version"] = _check(schema_ok, "" if schema_ok else
                                             f"saved under recipe schema version {entry.get('schema_version')}, "
                                             f"and this implementation writes version {SCHEMA_VERSION}")

    spec = PRESETS.get(entry.get("preset")) or {}
    for key, field in (("analysis_method", "method"), ("analysis_method_version", "method_version")):
        want, saved = spec.get(field), entry.get(key)
        if not want:
            checks[key] = _check(None, "this preset is not known to this implementation")
        else:
            same = saved == want
            checks[key] = _check(same, "" if same else
                                 f"saved under {key.replace('_', ' ')} {saved!r}, and this "
                                 f"implementation runs {want!r}")

    return _verdict(scope, checks)


def _verdict(scope: str, checks: dict) -> dict:
    """`resolved` is true only when every check ran AND passed, so absent evidence never reads as
    an all-clear. Completeness is reported separately from whether the source could be found."""
    failed = sorted(n for n, c in checks.items() if c["ok"] is False)
    not_checked = sorted(n for n, c in checks.items() if c["ok"] is None)
    return {
        "scope": scope,
        "source_resolved": checks.get("source_resolved", {}).get("ok") is True,
        "checks_passed": not failed,
        "assessment_complete": not not_checked,
        "resolved": not failed and not not_checked,
        "failed_checks": failed,
        "not_checked": not_checked,
        "checks": checks,
    }


def manifest(entries, *, captured: bool) -> dict:
    """The deterministic payload carried identically by all three export formats.

    Entries arrive already assessed and frozen; this only shapes and orders them.
    """
    out = []
    for entry in entries or ():
        item = dict(entry)
        preview = item.pop("preview", "")
        item["preview"] = {"note": PREVIEW_NOTE, "series": preview or None}
        item.setdefault("source_status", {"resolved": False, "reason": "no assessment was recorded",
                                          "scope": "not assessed"})
        out.append(item)
    return {
        "format": MANIFEST_FORMAT,
        "note": MANIFEST_NOTE,
        "captured": bool(captured),
        "capture_note": "" if captured else NOT_CAPTURED_NOTE,
        "recipes": sorted(out, key=lambda e: str(e.get("id"))),
    }


def manifest_from_snapshot(snap: dict) -> dict:
    """Read the frozen inventory out of a snapshot, live or published, without reassessing it."""
    return manifest(snap.get("recipes") or [], captured="recipes" in snap)
