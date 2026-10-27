import datetime as dt

import pytest
from pydantic import ValidationError

from bob import fixtures
from bob.mappings import MappingSpec, load_builtin, parse_file
from bob.mappings.engine import MappingError, parse_duration


def test_gen5_mapping_reads_synthetic_plate(plate_bytes):
    run = parse_file(plate_bytes, load_builtin("biotek-gen5-kinetic"))
    assert [s.name for s in run.signals] == ["OD600", "CFP", "YFP"]
    assert run.metadata["instrument_model"] == "Synergy HTX"
    od, cfp, yfp = run.signals
    assert od.kind == "absorbance" and od.unit == "OD" and od.optics == {"wavelength": "600"}
    assert yfp.kind == "fluorescence" and yfp.optics == {"excitation": "500/27", "emission": "540/25"}
    assert len(yfp.times) == fixtures.N_READS and yfp.times[:2] == [543.0, 1143.0]
    assert len(yfp.values) == 96
    assert yfp.values["A2"][12] == 100.0 + 50.0 * 12
    assert yfp.temperatures[0] == 37.0


@pytest.mark.parametrize("delimiter,encoding", [("\t", "cp1252"), (",", "cp1252"), ("\t", "utf-8-sig"), ("\t", "utf-16")])
def test_gen5_text_export_reads_like_the_excel_one(plate_bytes, delimiter, encoding):
    excel = parse_file(plate_bytes, load_builtin("biotek-gen5-kinetic"))
    data = fixtures.synthetic_gen5_text(delimiter).decode("cp1252").encode(encoding)
    text = parse_file(data, load_builtin("biotek-gen5-kinetic-text"))
    assert text.metadata == excel.metadata and text.warnings == []
    for a, b in zip(excel.signals, text.signals, strict=True):
        assert (a.name, a.label, a.kind, a.unit, a.optics) == (b.name, b.label, b.kind, b.unit, b.optics)
        assert (a.times, a.values, a.temperatures) == (b.times, b.values, b.temperatures)


def test_text_mapping_sends_excel_files_to_the_excel_mapping(plate_bytes):
    with pytest.raises(MappingError, match="Excel"):
        parse_file(plate_bytes, load_builtin("biotek-gen5-kinetic-text"))


@pytest.mark.parametrize(
    "cell,seconds",
    [
        (dt.time(0, 7, 30), 450.0),
        ("00:07:30", 450.0),
        ("1 day, 0:07:30", 86850.0),
        ("2 days, 1:00:00", 176400.0),
        (dt.timedelta(days=1, minutes=7, seconds=30), 86850.0),
        (dt.datetime(1900, 1, 1, 0, 7, 30), 86850.0),
        (0.5, 43200.0),
        (None, None),
        ("Time", None),
    ],
)
def test_parse_duration(cell, seconds):
    assert parse_duration(cell) == seconds


def test_non_numeric_readings_are_skipped_and_reported():
    spec = load_builtin("biotek-gen5-kinetic")
    rows = [("YFP:500/27,540/25",), (), (None, "Time", "T° YFP", "A1", "A2"), (None, "00:10:00", 37, 5, "OVRFLW"), ()]
    from bob.mappings.engine import parse_rows

    run = parse_rows(rows, spec)
    assert run.signals[0].values == {"A1": [5.0], "A2": [None]}
    assert "OVRFLW" in run.warnings[0]


def test_gen5_default_read_names_are_classified_by_optics_and_kept_distinct():
    from bob.mappings.engine import parse_rows

    spec = load_builtin("biotek-gen5-kinetic")
    header = (None, "Time", "T°", "A1")
    rows = [
        ("Read 1:600",), (), header, (None, "00:10:00", 37, 0.2), (),
        ("Read 1:700",), (), header, (None, "00:10:00", 37, 0.1), (),
        ("Read 2:485,528",), (), header, (None, "00:10:00", 37, 900), (),
    ]
    run = parse_rows(rows, spec)
    assert [(s.name, s.kind) for s in run.signals] == [
        ("Read 1:600", "absorbance"),
        ("Read 1:700", "absorbance"),
        ("Read 2", "fluorescence"),
    ]


def _block(*data_rows, header=("Time", "T°", "A1", "A2")):
    return [("YFP:500/27,540/25",), (), (None, *header), *[(None, *r) for r in data_rows], ()]


def test_midnight_dates_in_metadata_drop_the_time():
    from bob.mappings.engine import parse_rows

    rows = [("Date", dt.datetime(2017, 9, 23)), ("Time", dt.time(22, 33, 38)), *_block(("00:10:00", 37, 1, 2))]
    assert parse_rows(rows, load_builtin("biotek-gen5-kinetic")).metadata["run_date"] == "2017-09-23"


def test_non_finite_text_readings_are_unreadable():
    from bob.mappings.engine import parse_rows

    run = parse_rows(_block(("00:10:00", 37, "NaN", "inf"), ("00:20:00", 37, "1e999", 5)), load_builtin("biotek-gen5-kinetic"))
    assert run.signals[0].values == {"A1": [None, None], "A2": [None, 5.0]}


def test_duplicate_positions_are_refused():
    from bob.mappings.engine import parse_rows

    with pytest.raises(MappingError, match="more than once"):
        parse_rows(_block(("00:10:00", 37, 1, 2), header=("Time", "T°", "A1", "A1")), load_builtin("biotek-gen5-kinetic"))


def test_a_loose_position_pattern_never_yields_empty_or_odd_positions():
    from bob.mappings.engine import parse_rows

    spec = load_builtin("biotek-gen5-kinetic").to_json()
    spec["blocks"]["position_pattern"] = "^[A-P]?[0-9]{0,2}$"
    rows = _block(("00:10:00", 37, 1, 2, 3), header=("Time", "T°", "A1", "A2", ""))
    run = parse_rows(rows, MappingSpec.model_validate(spec))
    assert list(run.signals[0].values) == ["A1", "A2"]


def test_readings_after_a_blank_time_are_reported():
    from bob.mappings.engine import parse_rows

    run = parse_rows(_block(("00:10:00", 37, 1, 2), (None, 37, 3, 4), ("00:30:00", 37, 5, 6)), load_builtin("biotek-gen5-kinetic"))
    assert run.signals[0].times == [600.0] and "no time" in run.warnings[0]


def test_a_stopped_run_keeps_only_the_reads_it_made():
    from bob.mappings.engine import parse_rows

    spec = load_builtin("biotek-gen5-kinetic")
    run = parse_rows(_block(("00:10:00", 37, 1, 2), ("00:20:00", 37, None, 4), ("0:00:00", None, None, None), ("0:00:00", None, None, None)), spec)
    (yfp,) = run.signals
    assert yfp.times == [600.0, 1200.0] and yfp.values == {"A1": [1.0, None], "A2": [2.0, 4.0]}
    assert run.warnings == ["YFP: 2 time points without readings were left out; a run stopped early lists the reads it never made"]
    with pytest.raises(MappingError, match="no readings"):
        parse_rows(_block(("0:00:00", None, None, None)), spec)


def test_corrupt_sheet_xml_is_a_mapping_error(plate_bytes):
    import io
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(plate_bytes))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for item in src.infolist():
            data = src.read(item.filename)
            z.writestr(item, data[: len(data) // 2] if item.filename == "xl/worksheets/sheet1.xml" else data)
    with pytest.raises(MappingError):
        parse_file(out.getvalue(), load_builtin("biotek-gen5-kinetic"))


def test_file_without_blocks_is_rejected():
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append(["just", "a", "table"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(MappingError):
        parse_file(buf.getvalue(), load_builtin("biotek-gen5-kinetic"))


def test_spec_rejects_bad_key_and_runaway_patterns():
    base = load_builtin("biotek-gen5-kinetic").to_json()
    with pytest.raises(ValidationError):
        MappingSpec.model_validate({**base, "key": "Has Spaces"})
    with pytest.raises(ValidationError):
        MappingSpec.model_validate({**base, "blocks": {**base["blocks"], "label_pattern": "a" * 201}})
    with pytest.raises(ValidationError):
        MappingSpec.model_validate({**base, "modality": "telepathy"})
