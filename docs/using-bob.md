# Using BOB

BOB organizes data as workspace → investigation → study → sample and assay. A study links samples and their biological design references to immutable instrument uploads, parsed signals, well assignments, analysis settings, and publication history.

## Import

Upload a supported plate-reader file to a study and select an instrument mapping. BOB keeps the original bytes, records their SHA-256 digest, and stores the mapping version used to interpret them. The workbook check endpoint previews an Excel-to-SBOL import without writing data.

## Analysis

Analysis workflows require explicit sample and control wells. Results report correction choices, source file identity, mapping identity, method version, parameters, and warnings. Saved figure recipes retain enough source information to detect later layout, metadata, unit, or method changes.

## Publication and versions

Only a workspace owner can publish. Publication requires authors and a data license. Published studies are server-public: any signed-in user can read and download them, but only workspace members can edit them.

Every later change to a published study records a new version. Requests using `?version=N` resolve measurements, layouts, source metadata, and raw files from that frozen version even if the live assay is later replaced or removed.

## Exports

- SBOL 2.3 connects assays and samples to their design identities.
- ISA-JSON describes investigation, study, assay, process, and material structure.
- RO-Crate packages metadata, standards documents, analysis recipes, and original raw files.

Exports of a published study use the requested frozen version. Verify access and licensing before distributing a crate because it contains raw uploads.
