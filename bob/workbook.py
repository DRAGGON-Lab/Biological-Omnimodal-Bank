"""Reads an Excel-to-SBOL Assay workbook: its assays, which sample design sat in each well, the
SynBioHub IRI of each design, and the signals it names. The workbook is what SynBioSuite sends
with an experiment upload.

Columns are found by their header text, so a template whose columns move still reads.
"""

import io
import string
from dataclasses import dataclass, field

from openpyxl import load_workbook


class WorkbookError(ValueError):
    pass


@dataclass
class WorkbookAssay:
    id: str
    name: str
    description: str = ""
    temperature: str = ""
    platform: str = ""
    wells: dict[str, str] = field(default_factory=dict)


@dataclass
class WorkbookSignal:
    name: str
    description: str = ""
    color: str = ""


@dataclass
class AssayWorkbook:
    assays: list[WorkbookAssay]
    designs: dict[str, str]
    # In the reader's read order: the first row names the first channel the plate file holds.
    signals: list[WorkbookSignal] = field(default_factory=list)


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _rows(ws) -> list[dict[str, str]]:
    rows = ws.iter_rows(values_only=True)
    header = [_text(h).lower() for h in next(rows, ())]
    out = []
    for row in rows:
        values = {header[i]: _text(v) for i, v in enumerate(row) if i < len(header) and header[i]}
        if any(values.values()):
            out.append(values)
    return out


def _sheet(wb, name: str):
    for ws in wb.worksheets:
        if ws.title.strip().lower() == name:
            return ws
    return None


def _position(row: str, column: str, where: str) -> str:
    try:
        r, c = int(float(row)), int(float(column))
    except ValueError as exc:
        raise WorkbookError(f"{where}: Row and Column must be numbers, not {row!r} and {column!r}") from exc
    if not 1 <= r <= 26 or not 1 <= c <= 48:
        raise WorkbookError(f"{where}: row {r}, column {c} is outside a plate")
    return f"{string.ascii_uppercase[r - 1]}{c}"


def read(data: bytes) -> AssayWorkbook:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise WorkbookError("The workbook could not be opened as .xlsx or .xlsm") from exc
    assay_ws, sample_ws = _sheet(wb, "assay"), _sheet(wb, "sample")
    if assay_ws is None or sample_ws is None:
        raise WorkbookError("This is not an Excel-to-SBOL Assay workbook: it needs the sheets 'assay' and 'sample'")

    assays: dict[str, WorkbookAssay] = {}
    for n, r in enumerate(_rows(assay_ws), start=2):
        aid = r.get("assay id") or r.get("assay name")
        if not aid:
            raise WorkbookError(f"assay sheet, row {n}: the assay has no ID")
        if aid in assays:
            raise WorkbookError(f"assay sheet, row {n}: assay ID {aid!r} appears twice")
        assays[aid] = WorkbookAssay(aid, r.get("assay name") or aid, r.get("assay description", ""), r.get("temperature", ""), r.get("technology platform", ""))
    if not assays:
        raise WorkbookError("The assay sheet lists no assays")

    for n, r in enumerate(_rows(sample_ws), start=2):
        where = f"sample sheet, row {n}"
        aid, design = r.get("assay id", ""), r.get("sample design", "")
        if aid not in assays:
            raise WorkbookError(f"{where}: assay ID {aid!r} is not on the assay sheet")
        if not design:
            continue
        pos = _position(r.get("row", ""), r.get("column", ""), where)
        if pos in assays[aid].wells and assays[aid].wells[pos] != design:
            raise WorkbookError(f"{where}: well {pos} of assay {aid} is given two sample designs")
        assays[aid].wells[pos] = design

    designs = {}
    design_ws = _sheet(wb, "sbh_sampledesigns_collection")
    if design_ws is not None:
        for r in _rows(design_ws):
            if r.get("name") and r.get("uri"):
                designs[r["name"]] = r["uri"]
    signals: list[WorkbookSignal] = []
    signal_ws = _sheet(wb, "signal")
    if signal_ws is not None:
        for n, r in enumerate(_rows(signal_ws), start=2):
            name = r.get("signal name") or r.get("signal id", "")
            if not name:
                continue
            if any(s.name == name for s in signals):
                raise WorkbookError(f"signal sheet, row {n}: signal {name!r} appears twice")
            signals.append(WorkbookSignal(name[:80], r.get("signal description", "")[:200], r.get("signal color", "")[:32]))
    return AssayWorkbook(list(assays.values()), designs, signals)
