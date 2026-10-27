"""The instrument mapping format, `bob-mapping/1`.

A mapping is pure data: it names where an instrument export keeps its metadata, where each
measurement block starts, and how block labels become BOB signals. It never carries code, so a
mapping shared through the hub cannot execute anything on the server that reads it.
"""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
MAX_PATTERN_LENGTH = 200


def _check_pattern(value: str | None) -> str | None:
    if value is None:
        return value
    if len(value) > MAX_PATTERN_LENGTH:
        raise ValueError(f"pattern longer than {MAX_PATTERN_LENGTH} characters")
    re.compile(value)
    return value


class SourceSpec(BaseModel):
    # "delimited" is a tab- or comma-separated text export, told apart by whether the file has tabs.
    format: Literal["xlsx", "delimited"]
    sheet_index: int = Field(0, ge=0)
    sheet_pattern: str | None = None

    _p = field_validator("sheet_pattern")(_check_pattern)


class MetadataSpec(BaseModel):
    key_column: int = Field(1, ge=1)
    value_column: int = Field(2, ge=1)
    fields: dict[str, str] = Field(default_factory=dict)


class BlockSpec(BaseModel):
    label_column: int = Field(1, ge=1)
    label_pattern: str
    header_offset: int = Field(2, ge=1)
    time_header: str = "Time"
    position_pattern: str
    temperature_header_pattern: str | None = None

    _p = field_validator("label_pattern", "position_pattern", "temperature_header_pattern")(_check_pattern)


class SignalRule(BaseModel):
    """The first rule whose `match` fits the signal name and `optics_match` fits its optics applies."""

    match: str
    optics_match: str | None = None
    kind: Literal["absorbance", "fluorescence", "luminescence", "other"]
    unit: str
    optics_pattern: str | None = None

    _p = field_validator("match", "optics_match", "optics_pattern")(_check_pattern)


class MappingSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal["bob-mapping/1"] = Field("bob-mapping/1", alias="schema")
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    emoji: str | None = Field(None, max_length=8)
    modality: Literal["plate_reader"]
    description: str = ""
    source: SourceSpec
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)
    blocks: BlockSpec
    signals: list[SignalRule] = Field(min_length=1)

    def to_json(self) -> dict:
        return self.model_dump(by_alias=True, mode="json")


def load_builtin(key: str) -> MappingSpec:
    path = BUILTIN_DIR / f"{key}.json"
    return MappingSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))


def builtin_mappings() -> list[MappingSpec]:
    return [MappingSpec.model_validate(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(BUILTIN_DIR.glob("*.json"))]
