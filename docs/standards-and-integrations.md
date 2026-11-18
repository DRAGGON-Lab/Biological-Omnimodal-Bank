# Standards and integrations

## SBOL 2.3

BOB represents samples as implementations or collections of implementations and links their components to stored IRIs. Raw-file provenance is represented separately from the SBOL attachment hash so a SHA-256 digest is never mislabeled as SBOL's SHA-1 attachment digest.

## ISA-JSON

Study and investigation exports are validated against the pinned ISA-JSON schemas in `tests/standards/isa-json`. Updating those schemas must be a reviewed change with validator tests.

## RO-Crate

RO-Crate exports contain the ISA-JSON document, SBOL document, analysis-recipe manifest, and original assay files. CI validates the crate and ISA profile using `roc-validator`.

## SynBioHub

BOB contacts only instances listed in `BOB_SYNBIOHUB_INSTANCES`. Redirects are refused. Stored SynBioHub tokens are encrypted using a key derived from the BOB application secret; a lost or changed application secret makes those tokens unreadable.

## SynBioSuite and API clients

External clients authenticate with bearer API tokens and can list studies where their account has editor or owner access. Browser CORS origins are restricted by `BOB_CORS_ORIGINS`; cross-origin requests never receive session-cookie credentials.
