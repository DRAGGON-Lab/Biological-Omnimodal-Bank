"""Text types for request bodies.

Control characters are removed because they are invalid in XML, and one of them in any name
breaks the whole study's SBOL export.
"""

import re
from typing import Annotated

from pydantic import AfterValidator, Field

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CONTROL_AND_BREAKS = re.compile(r"[\x00-\x1f\x7f]")


def clean_line(value: str) -> str:
    return _CONTROL_AND_BREAKS.sub(" ", value).strip()


def clean_text(value: str) -> str:
    return _CONTROL.sub("", value).strip()


def _required(value: str) -> str:
    value = clean_line(value)
    if not value:
        raise ValueError("must not be blank")
    return value


def _required_text(value: str) -> str:
    value = clean_text(value)
    if not value:
        raise ValueError("must not be blank")
    return value


Name = Annotated[str, Field(max_length=200), AfterValidator(_required)]
RequiredText = Annotated[str, Field(max_length=10_000), AfterValidator(_required_text)]
ShortName = Annotated[str, Field(max_length=120), AfterValidator(_required)]
Label = Annotated[str, Field(max_length=200), AfterValidator(clean_line)]
Description = Annotated[str, Field(max_length=10_000), AfterValidator(clean_text)]
IRI_PATTERN = r"^$|^(?:[Hh][Tt][Tt][Pp][Ss]?://|[Uu][Rr][Nn]:)[^\s\"<>{}|\\^`\x00-\x1f\x7f]+$"


def _orcid(value: str) -> str:
    """Accepts 0000-0002-1825-0097 or its https://orcid.org/ form and returns the bare iD."""
    value = clean_line(value)
    if not value:
        return ""
    m = re.fullmatch(r"(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", value)
    if not m:
        raise ValueError("must look like 0000-0002-1825-0097")
    digits = m.group(1).replace("-", "")
    total = 0
    for d in digits[:-1]:
        total = (total + int(d)) * 2
    check = (12 - total % 11) % 11
    if digits[-1] != ("X" if check == 10 else str(check)):
        raise ValueError("is not a valid ORCID iD (its last digit does not match)")
    return m.group(1)


Orcid = Annotated[str, Field(max_length=60), AfterValidator(_orcid)]
