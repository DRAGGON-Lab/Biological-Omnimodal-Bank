"""Apply a `bob-mapping/1` spec to an instrument export."""

import csv
import datetime as dt
import io
import math
import multiprocessing
import re
from dataclasses import dataclass, field

import openpyxl
from openpyxl.utils.datetime import to_excel

from bob.mappings.spec import MappingSpec

# Caps stop a tiny file that touches column XFD or a million rows from exhausting memory.
MAX_COLUMNS = 512
MAX_ROWS = 200_000
_POSITION = re.compile(r"^[A-Z]{1,2}\d{1,3}$")
_DURATION = re.compile(r"^(?:(?P<days>\d+) days?, )?(?P<h>\d+):(?P<m>\d{2}):(?P<s>\d{2}(?:\.\d+)?)$")


class MappingError(ValueError):
    pass


@dataclass
class ParsedSignal:
    name: str
    label: str
    kind: str
    unit: str
    optics: dict[str, str]
    times: list[float]
    values: dict[str, list[float | None]]
    temperatures: list[float | None] = field(default_factory=list)

    @property
    def positions(self) -> list[str]:
        return list(self.values)


@dataclass
class ParsedRun:
    mapping_key: str
    metadata: dict[str, str]
    signals: list[ParsedSignal]
    warnings: list[str] = field(default_factory=list)

    @property
    def positions(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.signals:
            seen.update(dict.fromkeys(s.values))
        return list(seen)


def parse_duration(cell) -> float | None:
    """Seconds since the run started. Gen5 writes times past 24 h as '1 day, 0:07:30'."""
    if cell is None or cell == "":
        return None
    if isinstance(cell, dt.timedelta):
        return cell.total_seconds()
    if isinstance(cell, dt.time):
        return cell.hour * 3600 + cell.minute * 60 + cell.second + cell.microsecond / 1e6
    if isinstance(cell, dt.datetime):
        # openpyxl shifts serials under 60 by a day for Excel's 1900 leap-year bug; to_excel undoes it.
        return to_excel(cell) * 86400.0
    if isinstance(cell, (int, float)):
        return float(cell) * 86400.0
    match = _DURATION.match(str(cell).strip())
    if not match:
        return None
    days = int(match["days"] or 0)
    return days * 86400 + int(match["h"]) * 3600 + int(match["m"]) * 60 + float(match["s"])


def _number(cell) -> float | None:
    if isinstance(cell, bool):
        return None
    try:
        value = float(cell) if isinstance(cell, (int, float)) else float(str(cell).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _text(cell) -> str:
    if cell is None:
        return ""
    if isinstance(cell, dt.datetime) and cell.time() == dt.time(0):
        return cell.date().isoformat()
    return str(cell).strip()


def _cell(row: tuple, column: int):
    return row[column - 1] if column - 1 < len(row) else None


def _select_sheet(wb, spec: MappingSpec):
    if spec.source.sheet_pattern:
        for name in wb.sheetnames:
            if re.search(spec.source.sheet_pattern, name):
                return wb[name]
        raise MappingError(f"no sheet matches {spec.source.sheet_pattern!r}")
    if spec.source.sheet_index >= len(wb.sheetnames):
        raise MappingError(f"workbook has no sheet {spec.source.sheet_index}")
    return wb[wb.sheetnames[spec.source.sheet_index]]


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Gen5 writes text exports in the Windows code page, where the degree sign is one byte.
        return data.decode("cp1252", errors="replace")


def _delimited_rows(data: bytes) -> tuple[list[tuple], str]:
    if data.startswith(b"PK"):
        raise MappingError("this is an Excel workbook; choose the mapping for Excel exports")
    text = _decode(data)
    delimiter = "\t" if "\t" in text else ","
    rows = []
    try:
        for r in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            rows.append(tuple(c if c.strip() else None for c in r[:MAX_COLUMNS]))
            if len(rows) > MAX_ROWS:
                raise MappingError(f"file has more than {MAX_ROWS} rows")
    except csv.Error as exc:
        raise MappingError(f"not a readable text export: {exc}") from exc
    return rows, delimiter


def parse_file(data: bytes, spec: MappingSpec) -> ParsedRun:
    if spec.source.format == "delimited":
        rows, delimiter = _delimited_rows(data)
        return parse_rows(rows, spec, split_labels=delimiter == ",")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise MappingError(f"not a readable .xlsx workbook: {exc}") from exc
    try:
        ws = _select_sheet(wb, spec)
        # Read-only mode trusts the file's recorded sheet size, which some writers get wrong.
        ws.reset_dimensions()
        rows = []
        for r in ws.iter_rows(values_only=True, max_col=MAX_COLUMNS):
            rows.append(tuple(r))
            if len(rows) > MAX_ROWS:
                raise MappingError(f"sheet has more than {MAX_ROWS} rows")
    except MappingError:
        raise
    except Exception as exc:
        raise MappingError(f"the workbook could not be read: {exc}") from exc
    finally:
        wb.close()
    return parse_rows(rows, spec)


def _isolated_worker(conn, data: bytes, spec_json: dict) -> None:
    try:
        conn.send(("ok", parse_file(data, MappingSpec.model_validate(spec_json))))
    except MappingError as exc:
        conn.send(("mapping_error", str(exc)))
    except Exception as exc:
        conn.send(("mapping_error", f"could not read the file: {exc}"))
    finally:
        conn.close()


def parse_file_isolated(data: bytes, spec: MappingSpec, timeout_s: float) -> ParsedRun:
    """Parse in a child process that is killed after `timeout_s`.

    A user-written mapping can carry a regex with catastrophic backtracking, and Python's `re`
    cannot be interrupted from inside the process that runs it.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_isolated_worker, args=(child, data, spec.to_json()), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout_s):
            proc.kill()
            raise MappingError(f"mapping {spec.key!r} took longer than {timeout_s:.0f} s on this file; check its patterns")
        kind, payload = parent.recv()
    except EOFError as exc:
        raise MappingError(f"mapping {spec.key!r} stopped without a result") from exc
    finally:
        parent.close()
        proc.join(5)
    if kind != "ok":
        raise MappingError(payload)
    return payload


def _rejoin_label(header: list[str], label: str) -> list[str]:
    """Put back together the temperature column a comma export split at the commas of its optics label."""
    if any(h.endswith(label) for h in header):
        return header
    extra = label.count(",")
    for t in range(len(header) - extra):
        joined = ",".join(header[t:t + extra + 1])
        if header[t] and joined.endswith(label):
            return header[:t] + [joined] + header[t + extra + 1:]
    return header


def parse_rows(rows: list[tuple], spec: MappingSpec, split_labels: bool = False) -> ParsedRun:
    """`split_labels` is for comma-separated exports, which cut a label such as 'Read 1:569,593' into cells."""
    bl = spec.blocks
    label_re = re.compile(bl.label_pattern)
    position_re = re.compile(bl.position_pattern)
    temp_re = re.compile(bl.temperature_header_pattern) if bl.temperature_header_pattern else None
    wanted = {label.lower(): key for key, label in spec.metadata.fields.items()}

    metadata: dict[str, str] = {}
    signals: list[ParsedSignal] = []
    warnings: list[str] = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if split_labels:
            label = ",".join(t for t in (_text(c) for c in row[bl.label_column - 1:]) if t)
        else:
            label = _text(_cell(row, bl.label_column))
        match = label_re.match(label) if label else None
        header_row = rows[i + bl.header_offset] if match and i + bl.header_offset < len(rows) else None
        header = [_text(c) for c in header_row] if header_row else []
        if split_labels and match and "," in label:
            header = _rejoin_label(header, label)
        if match and bl.time_header in header:
            signal, i = _read_block(rows, i, label, match, header, spec, position_re, temp_re, warnings)
            signals.append(signal)
            continue
        if not signals:
            key = _text(_cell(row, spec.metadata.key_column)).lower()
            if key in wanted and wanted[key] not in metadata:
                metadata[wanted[key]] = _text(_cell(row, spec.metadata.value_column))
        i += 1

    if not signals:
        raise MappingError(f"no measurement blocks found using mapping {spec.key!r}")
    seen: dict[str, int] = {}
    for s in signals:
        seen[s.name] = seen.get(s.name, 0) + 1
    for s in signals:
        if seen[s.name] > 1:
            s.name = s.label
    taken: dict[str, int] = {}
    for s in signals:
        taken[s.name] = taken.get(s.name, 0) + 1
        if taken[s.name] > 1:
            s.name = f"{s.name} ({taken[s.name]})"
    return ParsedRun(mapping_key=spec.key, metadata=metadata, signals=signals, warnings=warnings)


def _read_block(rows, start, label, match, header, spec, position_re, temp_re, warnings):
    groups = match.groupdict()
    name = (groups.get("signal") or label).strip()
    optics_text = (groups.get("optics") or "").strip()
    rule = next(
        (r for r in spec.signals if re.search(r.match, name) and (r.optics_match is None or re.search(r.optics_match, optics_text))),
        None,
    )
    if rule is None:
        raise MappingError(f"no signal rule matches block {label!r}")
    optics: dict[str, str] = {}
    if rule.optics_pattern and optics_text:
        om = re.match(rule.optics_pattern, optics_text)
        optics = {k: v for k, v in (om.groupdict() if om else {}).items() if v}
    if optics_text and not optics:
        optics = {"raw": optics_text}

    time_col = header.index(spec.blocks.time_header)
    pos_cols = {j: h for j, h in enumerate(header) if h and j != time_col and position_re.match(h) and _POSITION.match(h)}
    duplicates = sorted({h for h in pos_cols.values() if list(pos_cols.values()).count(h) > 1})
    if duplicates:
        raise MappingError(f"block {label!r} lists position {duplicates[0]} more than once")
    temp_col = next((j for j, h in enumerate(header) if temp_re and temp_re.match(h)), None)
    if not pos_cols:
        raise MappingError(f"block {label!r} has no position columns")
    # a narrower plate shape must not quietly drop wells the file measured
    discarded = [h for j, h in enumerate(header)
                 if h and j != time_col and j not in pos_cols and _POSITION.match(h)]
    if discarded:
        raise MappingError(
            f"block {label!r} has {len(discarded)} well columns this plate shape leaves out, "
            f"starting at {discarded[0]}: the readings in them would be discarded without being "
            f"reported. Choose a plate shape that covers every well the file measured.")

    times: list[float] = []
    temps: list[float | None] = []
    values: dict[str, list[float | None]] = {h: [] for h in pos_cols.values()}
    unreadable = 0
    empty = 0
    j = start + spec.blocks.header_offset + 1
    while j < len(rows):
        row = rows[j]
        t = parse_duration(row[time_col] if time_col < len(row) else None)
        if t is None:
            if any(_number(row[c]) is not None for c in pos_cols if c < len(row)):
                warnings.append(f"{name}: a row with readings but no time stopped the block at row {j + 1}; later rows were not read")
            break
        j += 1
        if all(col >= len(row) or row[col] in (None, "") for col in pos_cols):
            # Gen5 lists every planned read, so a run stopped early ends in time points without readings.
            empty += 1
            continue
        times.append(t)
        temps.append(_number(row[temp_col]) if temp_col is not None and temp_col < len(row) else None)
        for col, pos in pos_cols.items():
            v = _number(row[col]) if col < len(row) else None
            if v is None and col < len(row) and row[col] not in (None, ""):
                unreadable += 1
            values[pos].append(v)
    if not times:
        raise MappingError(f"block {label!r} has no readings")
    if empty:
        warnings.append(f"{name}: {empty} time points without readings were left out; a run stopped early lists the reads it never made")
    if unreadable:
        warnings.append(f"{name}: {unreadable} non-numeric readings (for example OVRFLW) were skipped")
    return ParsedSignal(name, label, rule.kind, rule.unit, optics, times, values, temps), j
