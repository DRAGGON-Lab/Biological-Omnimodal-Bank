# Changelog

All notable changes are documented here. BOB follows Semantic Versioning for application and API compatibility.

## Unreleased

### Fixed

- Historical preset and rate analyses now resolve source metadata from the same frozen study version as their measurements and layout.

### Added

- Locked `uv` dependency resolution and GitHub Actions checks for lint, scoped typing, SQLite, PostgreSQL, standards validation, and container smoke testing.
- Strict production configuration, file-backed secrets, explicit migration mode, readiness/liveness endpoints, a non-root container, and a TLS/PostgreSQL reference Compose stack.
- One-time interactive PI bootstrap command.
- Versioned repository documentation and contribution/security policies.

### Changed

- Artifact writes use unique, flushed temporary files and atomic replacement to tolerate concurrent identical uploads.

## 1.0.0 - 2026-10-22

- Initial BOB release.
