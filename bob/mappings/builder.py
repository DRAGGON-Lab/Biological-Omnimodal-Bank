"""Build a `MappingSpec` from ordinary form answers, so no one has to write a regular expression.

The form covers the plate-reader families BOB supports: a Gen5-style block layout in an Excel
sheet, or the same layout as tab- or comma-separated text. Anything outside that uses the advanced
JSON path.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bob.mappings.spec import BlockSpec, MappingSpec, MetadataSpec, SignalRule, SourceSpec

POSITION_STYLES = {
    # a visible well name, not a pattern the user types
    "a1-96": (r"^[A-H](?:[1-9]|1[0-2])$", "A1 to H12, a 96-well plate"),
    "a1-384": (r"^[A-P](?:[1-9]|1[0-9]|2[0-4])$", "A1 to P24, up to a 384-well plate"),
}
SIGNAL_KINDS = ["absorbance", "fluorescence", "luminescence", "other"]
_OPTICS_PATTERNS = (r"^(?P<wavelength>\d+)$", r"^(?P<excitation>[\d/]+),(?P<emission>[\d/]+)$")


class ChannelForm(BaseModel):
    """One measurement block: the instrument's own label, and what that channel measured.

    There is no display name here. A mapping cannot rename a channel, since the parser takes the
    name from the file; renaming happens per assay at import. Extra keys are refused rather than
    ignored, so a name sent here fails loudly instead of disappearing.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    kind: Literal["absorbance", "fluorescence", "luminescence", "other"]
    unit: str = Field("", max_length=24)


class MappingForm(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    emoji: str | None = Field(None, max_length=8)
    description: str = ""
    format: Literal["xlsx", "delimited"] = "xlsx"
    sheet_index: int = Field(0, ge=0)
    label_column: int = Field(1, ge=1)
    header_offset: int = Field(2, ge=1)
    time_header: str = Field("Time", min_length=1, max_length=80)
    position_style: Literal["a1-96", "a1-384"] = "a1-384"
    temperature_column: bool = True
    label_has_optics: bool = True
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)
    channels: list[ChannelForm] = Field(default_factory=list)


def split_label(label: str, label_has_optics: bool) -> tuple[str, str]:
    if label_has_optics and ":" in label:
        head, _, tail = label.partition(":")
        return head.strip(), tail.strip()
    return label.strip(), ""


def _exact(text: str) -> str:
    return f"^{re.escape(text)}$"


def _optics_pattern(optics: str) -> str | None:
    """Keep the instrument's own wavelengths as named optics where they are in a standard shape."""
    return next((p for p in _OPTICS_PATTERNS if re.match(p, optics)), None)


def _rules(form: MappingForm) -> list[SignalRule]:
    if not form.channels:
        # discovery: read every block so its label can be shown back, claiming no kind or unit
        return [SignalRule(match=".*", kind="other", unit="")]
    rules = []
    for ch in form.channels:
        signal, optics = split_label(ch.label, form.label_has_optics)
        if not signal:
            raise ValueError(f"channel label {ch.label!r} has nothing before its colon")
        rules.append(SignalRule(
            match=_exact(signal),
            optics_match=_exact(optics) if optics else None,
            kind=ch.kind,
            unit=ch.unit,
            optics_pattern=_optics_pattern(optics) if optics else None,
        ))
    return rules


def to_spec(form: MappingForm) -> MappingSpec:
    label_pattern = r"^(?P<signal>[^:]+):(?P<optics>.+)$" if form.label_has_optics else r"^(?P<signal>.+)$"
    return MappingSpec(
        key=form.key,
        name=form.name,
        emoji=form.emoji,
        modality="plate_reader",
        description=form.description,
        source=SourceSpec(format=form.format, sheet_index=form.sheet_index),
        metadata=form.metadata,
        blocks=BlockSpec(
            label_column=form.label_column,
            label_pattern=label_pattern,
            header_offset=form.header_offset,
            time_header=form.time_header,
            position_pattern=POSITION_STYLES[form.position_style][0],
            temperature_header_pattern="^T°" if form.temperature_column else None,
        ),
        signals=_rules(form),
    )


def form_from_spec(spec: MappingSpec) -> MappingForm:
    """Read a template back into form answers, so a built-in mapping can start one."""
    bl = spec.blocks
    style = next((k for k, (pattern, _) in POSITION_STYLES.items() if pattern == bl.position_pattern), "a1-384")
    return MappingForm(
        key=spec.key,
        name=spec.name,
        emoji=spec.emoji,
        description=spec.description,
        format=spec.source.format,
        sheet_index=spec.source.sheet_index,
        label_column=bl.label_column,
        header_offset=bl.header_offset,
        time_header=bl.time_header,
        position_style=style,
        temperature_column=bl.temperature_header_pattern is not None,
        label_has_optics="(?P<optics>" in bl.label_pattern,
        metadata=spec.metadata,
        channels=[],
    )
