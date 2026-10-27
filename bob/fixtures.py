"""A synthetic Gen5 kinetic export whose correct results can be worked out by hand.

Layout (13 reads, every 600 s):
  A1-A3  "Consortium X"   OD 0.1+0.01k, YFP 100+50k offset by -10/0/+10, CFP 200+20k
  B1-B3  "Strain Y"       OD 0.1+0.01k, YFP 100+25k, CFP 200
  G1-G3  untransformed    OD 0.1+0.01k, YFP 100,     CFP 200
  H1-H3  medium only      OD 0.1,       YFP 80,      CFP 150
  other wells             OD 0.09,      YFP 60,      CFP 140
So after subtracting the untransformed wells, Consortium X YFP is 50k with replicate SD 10, and
its mean over the run (k = 0..12) is 300.
"""

import datetime as dt
import io

import openpyxl
import sbol2

ROWS = "ABCDEFGH"
N_READS = 13
STEP_S = 600
PLATE = [f"{r}{c}" for r in ROWS for c in range(1, 13)]

CONSORTIUM = ["A1", "A2", "A3"]
STRAIN_Y = ["B1", "B2", "B3"]
UNTRANSFORMED = ["G1", "G2", "G3"]
MEDIUM = ["H1", "H2", "H3"]
REPLICATE_OFFSET = {"A1": -10.0, "A2": 0.0, "A3": 10.0}


def _od(pos: str, k: int) -> float:
    if pos in MEDIUM:
        return 0.1
    if pos in CONSORTIUM + STRAIN_Y + UNTRANSFORMED:
        return round(0.1 + 0.01 * k, 4)
    return 0.09


def _yfp(pos: str, k: int) -> float:
    if pos in CONSORTIUM:
        return 100.0 + 50.0 * k + REPLICATE_OFFSET[pos]
    if pos in STRAIN_Y:
        return 100.0 + 25.0 * k
    if pos in UNTRANSFORMED:
        return 100.0
    if pos in MEDIUM:
        return 80.0
    return 60.0


def _cfp(pos: str, k: int) -> float:
    if pos in CONSORTIUM:
        return 200.0 + 20.0 * k
    if pos in STRAIN_Y + UNTRANSFORMED:
        return 200.0
    if pos in MEDIUM:
        return 150.0
    return 140.0


def _clock(seconds: int):
    if seconds >= 86400:
        return str(dt.timedelta(seconds=seconds))
    return dt.time(seconds // 3600, (seconds // 60) % 60, seconds % 60)


GEN5_BLOCKS = [("OD600:600", 450, _od), ("CFP:420/50,485/20", 493, _cfp), ("YFP:500/27,540/25", 543, _yfp)]


def synthetic_gen5_text(delimiter: str = "\t") -> bytes:
    """The same run as Gen5's text export, in the Windows code page Gen5 writes. A comma-separated
    export leaves labels such as 'CFP:420/50,485/20' unquoted, so they split across cells."""
    lines = [[], ["Software Version", "2.07.17"], [], ["Plate Number", "Plate 1"], ["Date", "2026-09-29"], ["Time", "03:00:00"],
             ["Reader Type:", "Synergy HTX"], ["Reader Serial Number:", "SYNTHETIC"], ["Plate Type", "96 flat bottom"], []]
    for label, offset, fn in GEN5_BLOCKS:
        lines += [[label], [], ["Time", f"T° {label}", *PLATE]]
        for k in range(N_READS):
            lines.append([str(dt.timedelta(seconds=offset + k * STEP_S)), "37", *[str(fn(p, k)) for p in PLATE]])
        lines.append([])
    return "\r\n".join(delimiter.join(cells) for cells in lines).encode("cp1252")


def synthetic_gen5_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plate 1 - Sheet1"
    ws.append([])
    ws.append(["Software Version", "2.07.17"])
    ws.append([])
    ws.append(["Plate Number", "Plate 1"])
    ws.append(["Date", "2026-09-29"])
    ws.append(["Time", "03:00:00"])
    ws.append(["Reader Type:", "Synergy HTX"])
    ws.append(["Reader Serial Number:", "SYNTHETIC"])
    ws.append(["Plate Type", "96 flat bottom"])
    ws.append([])
    for label, offset, fn in GEN5_BLOCKS:
        ws.append([label])
        ws.append([])
        ws.append([None, "Time", f"T° {label}", *PLATE])
        for k in range(N_READS):
            ws.append([None, _clock(offset + k * STEP_S), 37, *[fn(p, k) for p in PLATE]])
        ws.append([])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SYNBIOHUB = "https://synbiohub.test"
DESIGN_IRI = SYNBIOHUB + "/user/lab/designs/{}/1"
SIGNAL_SHEET = [("OD600", "Optical density at 600nm", "black"), ("CFP", "CFP fluorescence", "cyan"), ("YFP", "YFP fluorescence", "yellow")]
MEDIUM_ROLE = "http://identifiers.org/ncit/NCIT:C48164"
STRAIN_ROLE = "http://purl.obolibrary.org/obo/NCIT_C97158"
CHASSIS_ROLE = "http://identifiers.org/ncit/NCIT:C14419"
CONCENTRATION = "https://wiki.synbiohub.org/wiki/Terms/Flapjack#concentration"


def synthetic_design_sbol() -> dict[str, bytes]:
    """What SynBioHub answers for each synthetic design's recursive SBOL, built the way the lab's
    templates model a sample design: medium, engineered strain nesting its chassis, supplements."""
    sbol2.Config.setOption(sbol2.ConfigOptions.VALIDATE.value, False)
    sbol2.Config.setOption(sbol2.ConfigOptions.VALIDATE_ONLINE.value, False)
    sbol2.Config.setOption(sbol2.ConfigOptions.SBOL_TYPED_URIS.value, False)
    sbol2.setHomespace(SYNBIOHUB + "/user/lab/designs")

    def md(doc, display_id, role=None):
        m = sbol2.ModuleDefinition(display_id, "1")
        if role:
            m.roles = [role]
        doc.addModuleDefinition(m)
        return m

    def use(parent, child):
        parent.modules.create(f"{child.displayId}_module").definition = child.identity

    out = {}
    for design in ("consortium_x", "host_only", "medium_only"):
        doc = sbol2.Document()
        top = md(doc, design)
        use(top, md(doc, "m9", MEDIUM_ROLE))
        if design != "medium_only":
            strain = md(doc, "strain_x" if design == "consortium_x" else "host_strain", STRAIN_ROLE)
            use(strain, md(doc, "host", CHASSIS_ROLE))
            if design == "consortium_x":
                strain.functionalComponents.create("pYFP_fc").definition = SYNBIOHUB + "/user/lab/designs/pYFP/1"
            use(top, strain)
        if design == "consortium_x":
            iptg = md(doc, "iptg_001")
            iptg.concentration = sbol2.TextProperty(iptg, CONCENTRATION, "0", "1", None, "0.001")
            iptg.functionalComponents.create("IPTG_fc").definition = SYNBIOHUB + "/user/lab/designs/IPTG/1"
            use(top, iptg)
        out[top.identity] = doc.writeString().encode("utf-8")
    return out


def synthetic_assay_workbook(assay_ids: tuple[str, ...] = ("plate_1",), signals: list[tuple[str, str, str]] | None = None,
                             design_iri: str = DESIGN_IRI) -> bytes:
    """An Excel-to-SBOL Assay workbook for the synthetic plate: each assay places the same three
    sample designs where the plate holds them (consortium, untransformed host, medium)."""
    wb = openpyxl.Workbook()
    wb.active.title = "welcome"
    wb.active.append([None, "Template Type", "Assay"])
    assay = wb.create_sheet("assay")
    assay.append(["Assay Name", "Assay ID", "Previous Version (URI)", "Assay Description", "Measurement Type", "Technology Type",
                  "Technology Platform", "Protocols", "Temperature", "PubMed ID", "DOI"])
    sample = wb.create_sheet("sample")
    sample.append(["Sample Name", "Sample ID", "Row", "Column", "Assay ID", "Sample Design"])
    for aid in assay_ids:
        assay.append([f"Plate {aid}", aid, None, "Synthetic kinetic run", None, None, "Synergy HTX", None, 30])
        for design, wells in (("consortium_x", CONSORTIUM), ("host_only", UNTRANSFORMED), ("medium_only", MEDIUM)):
            for pos in wells:
                sample.append([f"Sample_{pos}_{aid}", f"Sample_{pos}_{aid}", ROWS.index(pos[0]) + 1, int(pos[1:]), aid, design])
    designs = wb.create_sheet("SBH_sampledesigns_collection")
    designs.sheet_state = "hidden"
    designs.append(["Name", "URI"])
    for design in ("consortium_x", "host_only", "medium_only"):
        designs.append([design, design_iri.format(design)])
    if signals is not None:
        sheet = wb.create_sheet("signal")
        sheet.append(["Signal Name", "Signal ID", "Previous Version (URI)", "Signal Description", "Signal Color", "Data Source", "PubMed ID", "DOI"])
        for name, description, color in signals:
            sheet.append([name, name, None, description, color])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
