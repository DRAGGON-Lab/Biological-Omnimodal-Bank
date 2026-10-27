"""Resolves the sample designs an Assay workbook names on SynBioHub into the parts BOB records.

The role constants, `Supplement`, `SampleDesign`, `_name_from_uri`, `_has_role`, `_concentration`,
and `resolve` are the lab's own code from SynBioSuite's uploader, kept as written so the group
recognizes them; `parts` and `resolve_designs` turn the result into BOB sample parts.
"""

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import sbol2

from bob import synbiohub

# NCIT role codes that classify a sample-design module. Role URIs aren't uniform
# (medium uses ``NCIT:C48164``, the strain/chassis use ``NCIT_C97158``/``NCIT_C14419``),
# so callers match with ``endswith`` rather than splitting on a separator. A design's
# strain is modeled as an *engineered strain* (C97158) that carries the plasmid(s) as
# functional components and nests the host *chassis* (C14419) one level down; BOB's
# strain part is that chassis, so :func:`resolve` descends into the engineered strain to it.
MEDIUM_ROLE = "C48164"    # growth medium
STRAIN_ROLE = "C97158"    # engineered strain: its functional components are the plasmids
CHASSIS_ROLE = "C14419"   # host chassis nested in the strain -> BOB's "strain" part


# --------------------------------------------------------------------------- #
# The one design-domain object type + resolving it from SBOL
# --------------------------------------------------------------------------- #
@dataclass
class Supplement:
    """A chemical added to a sample design, with its concentration."""

    chemical: str  # name
    uri: str
    concentration: float


@dataclass
class SampleDesign:
    """A sample design resolved from SBOL: media, strain, plasmids, supplements.

    ``media``/``strain`` are ``(name, uri)``; ``strain`` is the host **chassis**
    (role C14419), nested inside the engineered strain (C97158) whose functional
    components are the plasmids. Each field becomes one BOB sample part.
    """

    id: str  # the design name
    uri: str
    media: Optional[Tuple[str, str]] = None
    strain: Optional[Tuple[str, str]] = None
    plasmids: List[Tuple[str, str]] = field(default_factory=list)
    supplements: List[Supplement] = field(default_factory=list)


def _name_from_uri(uri: str) -> str:
    """displayId at the end of a SynBioHub URI (handles a trailing ``/1`` version)."""
    parts = uri.rstrip("/").split("/")
    return parts[-2] if parts[-1].isdigit() else parts[-1]


def _has_role(module_definition, codes) -> bool:
    """True if any of the module's roles ends with one of ``codes``."""
    codes = (codes,) if isinstance(codes, str) else codes
    return any(
        str(role).rstrip("/").endswith(code)
        for role in module_definition.roles
        for code in codes
    )


def _concentration(module_definition) -> Optional[float]:
    """The concentration value if the module carries one, else None."""
    for key, values in module_definition.properties.items():
        if str(key).endswith("concentration") and values:
            return float(values[0])
    return None


class UnsupportedDesign(ValueError):
    """The design was read, but its composition cannot be recorded faithfully."""


def resolve(shop: sbol2.PartShop, name: str, uri: str) -> SampleDesign:
    """Get a sample design from SBH and resolve it into a :class:`SampleDesign`.

    One recursive pull, then a purely local walk of the design's modules: classify
    each as medium (role C48164), engineered strain (C97158), or supplement (no
    role but a concentration, whose functional component is the chemical). The
    engineered strain's functional components are the plasmids, and its nested
    chassis (C14419) is the host strain BOB records -- so the strain field is
    that chassis, not the engineered-strain wrapper.
    """
    # one recursive pull brings the whole design tree (design + medium + strain +
    # chassis) in a single round-trip; plasmids/chemicals ride as URI references
    document = sbol2.Document()
    shop.pull(uri, document, recursive=True)
    by_uri = {md.identity: md for md in document.moduleDefinitions}
    design = SampleDesign(id=name, uri=uri)
    media, strains, chassis_direct = [], [], []
    for module in by_uri[uri].modules:
        sub = by_uri[str(module.definition)]
        if _has_role(sub, MEDIUM_ROLE):
            media.append(sub)
        elif _has_role(sub, STRAIN_ROLE):
            strains.append(sub)
        elif _has_role(sub, CHASSIS_ROLE):
            chassis_direct.append(sub)
        elif (concentration := _concentration(sub)) is not None:
            for fc in sub.functionalComponents:
                uri_ = str(fc.definition)
                design.supplements.append(Supplement(_name_from_uri(uri_), uri_, concentration))
        else:
            raise UnsupportedDesign(
                "design {0}: module {1!r} is neither a medium, an engineered strain, a host "
                "chassis nor a supplement with a concentration, so its contribution to the "
                "sample is unknown".format(name, sub.displayId)
            )

    if len(media) > 1:
        raise UnsupportedDesign(
            "design {0} names more than one medium ({1}); BOB records one growth medium per "
            "sample, though mixed media exist"
            .format(name, ", ".join(sorted(m.displayId for m in media)))
        )
    if media:
        design.media = (media[0].displayId, media[0].identity)

    if strains and chassis_direct:
        raise UnsupportedDesign(
            "design {0} mixes an engineered strain ({1}) with a bare host chassis ({2}); BOB "
            "records one or the other, because which cells carry the plasmids would "
            "otherwise be a guess".format(
                name, ", ".join(sorted(s.displayId for s in strains)),
                ", ".join(sorted(c.displayId for c in chassis_direct)))
        )
    if len(strains) > 1:
        raise UnsupportedDesign(
            "design {0} holds {1} engineered strains ({2}); BOB records one engineered strain per sample, "
            "so a multi-strain consortium is refused, because flattening every plasmid beside every host "
            "loses which strain carries which plasmid".format(
                name, len(strains), ", ".join(sorted(s.displayId for s in strains)))
        )
    if len(chassis_direct) > 1:
        raise UnsupportedDesign(
            "design {0} holds {1} host chassis ({2}) with no engineered strain; BOB records "
            "one host per sample, though mixed cultures exist".format(name, len(chassis_direct),
                              ", ".join(sorted(c.displayId for c in chassis_direct)))
        )

    if strains:
        sub = strains[0]
        # the engineered strain carries the plasmids as functional components;
        # BOB's strain is the chassis (C14419) nested one level inside it
        design.plasmids = [
            (_name_from_uri(str(fc.definition)), str(fc.definition))
            for fc in sub.functionalComponents
        ]
        nested = [by_uri[str(c.definition)] for c in sub.modules
                  if str(c.definition) in by_uri
                  and _has_role(by_uri[str(c.definition)], CHASSIS_ROLE)]
        if not nested:
            raise UnsupportedDesign(
                "engineered strain {0!r} in design {1} has no chassis (role {2}) submodule, so "
                "its host is unknown".format(sub.displayId, name, CHASSIS_ROLE)
            )
        if len(nested) > 1:
            raise UnsupportedDesign(
                "engineered strain {0!r} in design {1} nests {2} host chassis ({3}); which one "
                "the sample grew in is ambiguous".format(
                    sub.displayId, name, len(nested),
                    ", ".join(sorted(c.displayId for c in nested)))
            )
        design.strain = (nested[0].displayId, nested[0].identity)
    elif chassis_direct:
        # a bare chassis is a real design: an untransformed host control carries no plasmid
        design.strain = (chassis_direct[0].displayId, chassis_direct[0].identity)
    return design


class SynBioHubShop(sbol2.PartShop):
    """A PartShop that fetches through BOB's SynBioHub client: bounded wait, no redirects."""

    def pull(self, uris, doc, recursive=True):
        r = synbiohub.request_sbol(f"{uris.rstrip('/')}/{'sbol' if recursive else 'sbolnr'}", self.key or None)
        doc.appendString(r.content, overwrite=True)


def _part(role: str, name: str, iri: str, sbol_class: str, amount: float | None = None) -> dict:
    return {"role": role, "iri": iri, "label": name, "amount": amount, "unit": None, "sbol_version": "2", "sbol_class": sbol_class}


def parts(design: SampleDesign) -> list[dict]:
    """The design link first, then what it resolved to; functional components point at ComponentDefinitions."""
    out = [_part("design", design.id, design.uri, "ModuleDefinition")]
    if design.media:
        out.append(_part("medium", *design.media, "ModuleDefinition"))
    if design.strain:
        out.append(_part("strain", *design.strain, "ModuleDefinition"))
    out += [_part("plasmid", name, iri, "ComponentDefinition") for name, iri in design.plasmids]
    out += [_part("supplement", s.chemical, s.uri, "ComponentDefinition", s.concentration) for s in design.supplements]
    return out


@dataclass
class Resolution:
    parts: list[dict]
    error: str = ""
    unsupported: bool = False


CACHE_S = 900
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def _resolve_one(instance: str, token: str | None, name: str, iri: str) -> Resolution:
    key = (iri, hashlib.sha256((token or "").encode()).hexdigest())
    with _cache_lock:
        hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return Resolution([{**p, "label": name} if p["role"] == "design" else p for p in hit[1]])
    shop = SynBioHubShop(instance)
    shop.key = token or ""
    try:
        found = parts(resolve(shop, name, iri))
    except synbiohub.SynBioHubError as exc:
        return Resolution([], str(exc))
    except KeyError as exc:
        return Resolution([], f"its SBOL from SynBioHub lacks {exc.args[0]}")
    except UnsupportedDesign as exc:
        return Resolution([], str(exc), unsupported=True)
    except (ValueError, sbol2.SBOLError) as exc:
        return Resolution([], str(exc))
    with _cache_lock:
        _cache[key] = (time.monotonic(), found)
    return Resolution(found)


def resolve_designs(designs: dict[str, str], instances: tuple[str, ...], tokens: dict[str, str | None]) -> dict[str, Resolution]:
    """Each named design's parts, or why they could not be read. Only configured SynBioHubs are asked."""
    out: dict[str, Resolution] = {}
    jobs = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, iri in designs.items():
            instance = next((i for i in instances if iri.startswith(i + "/")), None)
            if instance is None:
                out[name] = Resolution([], f"{iri} is not on a SynBioHub this BOB server is set up to read")
                continue
            jobs[name] = pool.submit(_resolve_one, instance, tokens.get(instance), name, iri)
        for name, job in jobs.items():
            out[name] = job.result()
    return out
