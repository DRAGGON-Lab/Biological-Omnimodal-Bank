# Development

## Environment

BOB targets Python 3.12. Install `uv`, then run:

```sh
uv sync --group dev
uv run pytest
```

`pyproject.toml` is the dependency declaration and `uv.lock` is the reproducible resolution used by CI and the container. Keep the legacy requirements files synchronized until downstream installations have migrated.

## Checks

```sh
uv run ruff check .
uv run pyright bob/config.py bob/migrate.py
uv run pytest --cov
```

The type-checking boundary intentionally starts with configuration and migrations. Expand it only after the selected module passes without suppressing real errors.

To run PostgreSQL tests, point `BOB_TEST_DATABASE_URL` at a disposable database. The fixture drops and recreates its `public` schema before every test; never use a shared or valuable database.

## Migrations

Create a migration after changing SQLAlchemy models:

```sh
uv run python -m bob.migrate revision "short description"
```

Review generated operations manually on SQLite and PostgreSQL. Production runs migrations through the one-shot Compose service before the application becomes ready.

## Pull requests

- Include regression tests for every defect.
- Preserve authorization through `bob.access` or the effective-access resolver introduced by later access-control work.
- Do not weaken provenance or silently discard measurements.
- Keep API changes backward compatible or document a deprecation period.
- Run the complete checks before requesting review.
